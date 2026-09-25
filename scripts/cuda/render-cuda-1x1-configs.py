#!/usr/bin/env python3
"""Render a shipping profile's configs, then append the CUDA acceleration keys.

The gate already exposes OCUDU_NATIVE_CONFIG_RENDERER, so this composes with
the shipping renderer instead of editing it: that renderer runs first and
produces its usual output, and the acceleration block is appended afterwards.
With OCUDU_NATIVE_GNB_ACCELERATION unset nothing is appended and the rendered
configs are byte-identical to a plain render of the base profile.

The base defaults to the legacy 1x1 renderer. OCUDU_NATIVE_CUDA_BASE_RENDERER
selects another one -- the Sionna rank-1 renderer for the C6 profile -- so that
one composition step serves every profile rather than being copied per profile.
The base must live in scripts/native/, because composing over an arbitrary path
would let a caller substitute the renderer the gate's provenance is recorded
against.
"""
from __future__ import annotations
import os
import runpy
import sys
from pathlib import Path

STAGES = ('disabled', 'low-phy-rx', 'low-phy-tx', 'pusch', 'pdsch', 'prach', 'all')
REPO = Path(__file__).resolve().parents[2]


def acceleration_block(stage: str) -> str:
    if stage not in STAGES:
        raise SystemExit(f'unknown CUDA acceleration stage: {stage}')
    index = STAGES.index(stage)
    # Cumulative: each stage enables everything the stages before it enabled.
    upper = {'pusch_acceleration_mode': 'disabled', 'pdsch_acceleration_mode': 'disabled',
             'prach_acceleration_mode': 'disabled', 'srs_acceleration_mode': 'disabled'}
    lower = {'low_phy_rx_acceleration_mode': 'disabled', 'low_phy_tx_acceleration_mode': 'disabled',
             'low_phy_prach_demodulation_acceleration_mode': 'disabled'}
    order = [('lower', 'low_phy_rx_acceleration_mode'), ('lower', 'low_phy_tx_acceleration_mode'),
             ('upper', 'pusch_acceleration_mode'), ('upper', 'pdsch_acceleration_mode'),
             ('upper', 'prach_acceleration_mode'), ('upper', 'srs_acceleration_mode')]
    for where, key in order[:index]:
        (upper if where == 'upper' else lower)[key] = 'enabled'
    if index >= 5:  # PRACH stage also enables the lower-PHY PRACH demodulator.
        lower['low_phy_prach_demodulation_acceleration_mode'] = 'enabled'
    # Discrete-GPU policy, per the WG documentation: auto selects pinned here,
    # and forced lower-PHY acceleration needs the managed grid's device mapping.
    ul_grid = 'managed' if index >= 1 else 'pinned'
    dl_grid = 'managed' if index >= 2 else 'pinned'
    # J4 (JETSON_MILESTONES.md): OCUDU_NATIVE_CUDA_GRID_MODE=auto|pinned|managed
    # replaces both modes, to compare the platform policy with the forced one.
    # Unset keeps the policy above, so the audited render does not change.
    override = os.environ.get('OCUDU_NATIVE_CUDA_GRID_MODE')
    if override:
        if override not in ('auto', 'pinned', 'managed'):
            raise SystemExit(f'invalid OCUDU_NATIVE_CUDA_GRID_MODE: {override}')
        ul_grid = dl_grid = override
    ru = '\n'.join(f'    {k}: {v}' for k, v in lower.items())
    phy = '\n'.join(f'  {k}: {v}' for k, v in upper.items())
    return (ru, phy + f'\n  ul_cuda_visible_grid_mode: {ul_grid}'
                     f'\n  dl_cuda_visible_grid_mode: {dl_grid}')


def base_renderer() -> Path:
    name = os.environ.get('OCUDU_NATIVE_CUDA_BASE_RENDERER', 'render-legacy-1x1-configs.py')
    if '/' in name or not name.endswith('.py'):
        raise SystemExit(f'OCUDU_NATIVE_CUDA_BASE_RENDERER must be a file name in scripts/native: {name}')
    path = REPO / 'scripts/native' / name
    if not path.is_file():
        raise SystemExit(f'no such base renderer: {path}')
    return path


def main() -> None:
    legacy = base_renderer()
    sys.argv[0] = str(legacy)
    try:
        runpy.run_path(str(legacy), run_name='__main__')
    except SystemExit as exit_code:
        if exit_code.code:
            raise

    stage = os.environ.get('OCUDU_NATIVE_GNB_ACCELERATION')
    if not stage:
        return  # Byte-identical to a plain legacy render.

    output_dir = Path(sys.argv[sys.argv.index('--output-dir') + 1])
    path = output_dir / 'gnb.yaml'
    text = path.read_text()
    if 'expert_phy:' in text or '  expert_cfg:' in text:
        raise SystemExit('rendered gnb.yaml already carries expert settings; reconcile explicitly')
    if text.count('ru_sdr:\n') != 1:
        raise SystemExit('expected exactly one ru_sdr section')
    ru, phy = acceleration_block(stage)
    text = text.replace('ru_sdr:\n', 'ru_sdr:\n  expert_cfg:\n' + ru + '\n', 1)
    path.write_text(text + '\nexpert_phy:\n' + phy + '\n')


if __name__ == '__main__':
    main()
