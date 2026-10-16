# Project review — 16 October 2026

Reviewed the pending CPU sample-worker implementation, broker latency summary,
scheduler launchers and analysis, srsUE patch lock, dashboard, and experiment
publication. Validation used an isolated source copy on the RTX 5090 workstation;
existing radio services were not restarted.

## Corrections

- The scheduler dashboard assumed cell B existed even when the launcher selected
  single-cell mode. Setup cards, metrics, charts, scene labels and runtime checks
  now follow the configured cells. The regression executes the shipping JavaScript
  against analyzer output: the original dashboard fails with a missing-cell
  exception, while both modes pass after the correction.
- Long scheduler source paths overflowed the two-column layout at 700 pixels.
  These labels now wrap; browser checks cover both modes at 1440, 700 and 390 pixels.
- Twelve new report pages were absent from documentation navigation, and seven
  report links targeted logs omitted by Git and source uploads. Report logs are
  now explicitly retained and published. Existing artifact bytes and measurements
  are unchanged; all 287 entries in the new artifact hash manifests match.
- The publication regression still expected 71 evidence files after the earlier
  logo change reduced the legacy inventory to 70. It now checks the inventory's
  complete file set and each file's expected hash.
- Backend guidance now distinguishes CPU/CUDA agreement within a tolerance from
  bit-exact serial/parallel CPU output and identifies the separate device kernels.
  Local slides are excluded from Git, source uploads and Docker build inputs.

## Validation

Hardware: NVIDIA GeForce RTX 5090. CPU and CUDA Release builds use the repository's
configured workstation toolchain, CUDA 12.8.1 and target architecture 120.

| Check | Result |
|---|---|
| CPU CTest | 13/13 passed |
| CUDA CTest | 13/13 passed |
| Synthetic GPU sequence | 9/9 stages passed |
| Python suites | 221 passed, 3 skipped; 4,258 subtests passed |
| Frontend regressions | Disconnect, independent gNB feeds, single-/two-cell scheduler rendering passed |
| Chromium dashboard | Both modes at three viewport widths; no page errors or horizontal overflow |
| Shell syntax | 99 scripts passed |
| Documentation | Strict Sphinx build and site checks passed, including legacy routes, links, text and evidence hashes |
| New report artifact manifests | 287 file hashes matched |

The GPU sequence exercises clean and noisy relay paths, interference, multiple
cells, TDL-A fading, correlated MIMO and control updates against a running broker.
The CPU worker tests cover concurrent receiving nodes, uneven ranges, exceptions,
history and profile updates, and bit-exact serial/parallel output. The broker test
compares its printed maximum latency with the receiver's exact timing accumulator.

The three Python skips require a privileged network namespace, a working MuJoCo
offscreen OpenGL context, and the pinned OCUDU source at the fixture's expected
location. Browser checks use synthetic analyzer output and the shipping dashboard;
they do not establish live-radio connectivity.

Detailed logs and browser captures are retained in the workstation workspace under
`validation/review-20261016/`, including `ctest-cpu.log`, `gpu-sequence.log`,
`pytest-final.log`, `dashboard-before.log`, `focused-after.log`, `browser-results.json`,
`shell-check.json`, `docs-build.log` and `site-check.log`.

## Remaining limits

Live OCUDU/srsUE trials, hardware-in-the-loop tests and Docker image builds were
not repeated in this review. The dated scheduler and performance reports retain
their original configurations and outcomes. Their receive starvations and timing
misses still prevent strict zero-miss real-time qualification; this review does
not change that verdict.
