#!/usr/bin/env python3
"""Grade a CUDA PHY CTest log by its printed verdicts, not by exit status.

Several upstream CUDA PHY test programs print a failure verdict and still
return zero, so a green ctest run is not by itself evidence that the
comparisons passed. This reads the log the run produced and fails on any
printed failure. It also asserts that the instrument recorded work: a log
with no verdict lines at all is a failure, not a pass.
"""
from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path

# (name, regex, predicate on the captured group) -- every match must satisfy
# the predicate, and TOLERANCE must appear at least once.
TOLERANCE = re.compile(r"All metrics within tolerance:\s*(\w+)")
AGREEMENT = re.compile(r"Decode agreement:\s*([0-9.]+)%")
# Two shipping spellings, both same-line only: "Byte mismatches: 0" and
# "... 0 byte mismatches". Never span a newline -- the following line
# starts with a timestamp and would be captured as a count.
MISMATCH_SUFFIX = re.compile(r"[Mm]ismatches:[ \t]*(\d+)")
MISMATCH_PREFIX = re.compile(r"(\d+)[ \t]+(?:byte|payload)[ \t]+mismatches", re.I)
ERROR = re.compile(r"^OCUDU ERROR:.*$", re.M)
ABORT = re.compile(r"Subprocess aborted|Assertion .* failed", re.M)


def grade(text: str) -> tuple[list[str], dict[str, int]]:
    problems: list[str] = []

    tolerance = TOLERANCE.findall(text)
    if not tolerance:
        problems.append("no 'All metrics within tolerance' verdict found; the log records no comparison")
    bad = [v for v in tolerance if v.upper() != "YES"]
    if bad:
        problems.append(f"{len(bad)}/{len(tolerance)} tolerance verdicts are not YES: {sorted(set(bad))}")

    agreement = [float(v) for v in AGREEMENT.findall(text)]
    low = [v for v in agreement if v < 100.0]
    if low:
        problems.append(f"{len(low)}/{len(agreement)} decode-agreement reports below 100%: min {min(low)}%")

    mismatches = [int(v) for v in MISMATCH_SUFFIX.findall(text) + MISMATCH_PREFIX.findall(text)]
    nonzero = [v for v in mismatches if v != 0]
    if nonzero:
        problems.append(f"{len(nonzero)} nonzero mismatch counts: max {max(nonzero)}")

    for line in ERROR.findall(text):
        problems.append(f"error line: {line.strip()}")
    for line in ABORT.findall(text):
        problems.append(f"abort: {line.strip()[:120]}")

    counts = {
        "tolerance_verdicts": len(tolerance),
        "decode_agreement_reports": len(agreement),
        "mismatch_counters": len(mismatches),
    }
    return problems, counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    args = parser.parse_args()
    text = args.log.read_text(errors="replace")
    problems, counts = grade(text)
    print("phy_log_counts=" + " ".join(f"{k}={v}" for k, v in counts.items()))
    for problem in problems:
        print("phy_log_problem: " + problem)
    verdict = "pass" if not problems else "fail"
    print(f"phy_log_verdict={verdict}")
    return 0 if verdict == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
