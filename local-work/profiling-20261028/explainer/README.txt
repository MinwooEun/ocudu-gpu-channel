Spark profiling visual explanation

Open ../profiling-explained.ko.html in a browser. This is a standalone document:
its CSS, JavaScript, SVG diagrams and plotting data are embedded. No server,
installation or internet connection is needed to read or use its controls.
Evidence links require the original profiling directory to remain alongside it.

Start with chapter 00: why the radio path is replaced by numbers, three program
roles, the exact RTX N8 copy-mode p99 origin of 76.7 us, and the already active
Spark direct-input optimization. The separate UE GPU project is out of scope.
Then read chapters 01–03: IQ path, radio time versus wall time, and the common
input/output-space model. Chapters 04–09 cover host/GPU boundaries, CPU work,
scaling, all ten remedy trials, the RTX 5090 audit and the underlying evidence.
The buffer sliders are an explanatory model, explicitly not a measured replay.

Rebuild from the preserved campaign JSON/CSV (Python standard library only):
  python3 explainer/build_explainer.py
Run that command from the profiling directory. The builder does not execute
radio or GPU workloads and does not modify the source evidence.

Browser QA uses Playwright 1.56.1 and Chromium 141, installed only under
/tmp/ocg-html-qa-20261028. Re-run in this workspace with:
  PLAYWRIGHT_BROWSERS_PATH=/tmp/ocg-html-qa-20261028/browsers node explainer/check_browser.cjs
Software rendering is selected to avoid the local GPU initialization stall.
qa/browser-check.json records interactive, offline, evidence-link, print and
responsive checks. Screenshots are representative desktop/mobile QA views.
