#!/usr/bin/env python3
"""Explicit all-host comparison config for the pinned CUDA gNB.

Keep existing text intact and reject existing expert sections rather than
silently overriding an experiment. Used only when explicitly requested.
"""
import re
import sys
from pathlib import Path


STAGES = ('disabled', 'low-phy-rx', 'low-phy-tx', 'pusch', 'pdsch', 'prach', 'all')


def configure(text, stage='disabled'):
    if stage not in STAGES:
        raise ValueError('unknown CUDA acceleration stage: ' + stage)
    if len(re.findall(r'^ru_sdr:\s*$', text, re.M)) != 1:
        raise ValueError('expected one ru_sdr section')
    if re.search(r'^expert_phy:|^  expert_cfg:', text, re.M):
        raise ValueError('existing expert settings require explicit reconciliation')
    ru = '\n'.join('    ' + key + ': disabled' for key in (
        'low_phy_tx_acceleration_mode', 'low_phy_rx_acceleration_mode',
        'low_phy_prach_demodulation_acceleration_mode'))
    phy = '\n'.join('  ' + key + ': disabled' for key in (
        'pusch_acceleration_mode', 'pdsch_acceleration_mode', 'prach_acceleration_mode',
        'srs_acceleration_mode'))
    phy += '\n  ul_cuda_visible_grid_mode: pinned\n  dl_cuda_visible_grid_mode: pinned'
    result = text.replace('ru_sdr:\n', 'ru_sdr:\n  expert_cfg:\n' + ru + '\n', 1) + '\nexpert_phy:\n' + phy + '\n'
    steps = (
        ('low_phy_rx_acceleration_mode',),
        ('low_phy_tx_acceleration_mode',),
        ('pusch_acceleration_mode',),
        ('pdsch_acceleration_mode',),
        ('prach_acceleration_mode', 'low_phy_prach_demodulation_acceleration_mode'),
        ('srs_acceleration_mode',),
    )
    for keys in steps[:STAGES.index(stage)]:
        for key in keys:
            result = result.replace(key + ': disabled', key + ': enabled')
    # Forced lower-PHY CUDA requires device mapping/reading. Pinned grids
    # are the all-host control; managed grids expose those capabilities.
    if STAGES.index(stage) >= 1:
        result = result.replace('ul_cuda_visible_grid_mode: pinned', 'ul_cuda_visible_grid_mode: managed')
    if STAGES.index(stage) >= 2:
        result = result.replace('dl_cuda_visible_grid_mode: pinned', 'dl_cuda_visible_grid_mode: managed')
    return result


def disable(text):
    return configure(text, 'disabled')


if __name__ == '__main__':
    path = Path(sys.argv[1])
    path.write_text(configure(path.read_text(), sys.argv[2] if len(sys.argv) > 2 else 'disabled'))
