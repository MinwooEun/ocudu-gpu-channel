#!/usr/bin/env python3
"""Grade verdicts that the pinned upstream PUSCH tests do not return as exit codes."""
import re
import sys
from pathlib import Path


def verify(text: str) -> None:
    for name in ("pusch_gpu_cpu_comparison_test", "pusch_e2e_pipeline_test"):
        match = re.search(rf'^\d+/\d+ Test: {name}\n(.*?)<end of output>', text, re.M | re.S)
        if match is None:
            raise ValueError(f"missing completed output: {name}")
        output = match.group(1)
        if "[SKIP]" in output or "*** FAIL:" in output:
            raise ValueError(f"GPU path skipped or verdict failed: {name}")
        if name == "pusch_gpu_cpu_comparison_test":
            # A reduced probe is useful for diagnosis, but cannot replace the
            # documented 4 PRB x 2 RX x 6 SINR comparison sweep.
            cases = []
            current = None
            for row in output.splitlines():
                group = re.fullmatch(r"--- PRB=(\d+), Rx Ports=(\d+) ---", row)
                condition = re.fullmatch(r"  SINR= *(\d+) dB:", row)
                if group:
                    current = tuple(map(int, group.groups()))
                if condition:
                    if current is None:
                        raise ValueError("PUSCH condition has no PRB/RX group")
                    cases.append((*current, int(condition[1])))
            expected = {(p, n, s) for p in (3, 4, 5, 6) for n in (1, 2)
                        for s in (5, 10, 15, 20, 25, 30)}
            if len(cases) != 48 or set(cases) != expected:
                raise ValueError("PUSCH comparison did not complete all 48 conditions")
            verdicts = re.findall(r"All metrics within tolerance: (YES|NO)", output)
            if verdicts != ["YES"]:
                raise ValueError(f"PUSCH comparison verdict is not YES: {verdicts}")
            if "No results collected." in output or re.search(r"\bnan\b", output, re.I):
                raise ValueError("PUSCH comparison has missing or nonfinite results")
        else:
            iterations = re.findall(r"^=== Results \((\d+) iterations, \d+ warmup skipped\) ===$",
                                    output, re.M)
            if iterations != ["100"]:
                raise ValueError("PUSCH pipeline did not report its 100 measured iterations")
            if re.search(r"^PASS: Both paths .+, 0 byte mismatches$", output, re.M) is None:
                raise ValueError("missing successful PUSCH pipeline verdict")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} <CTest LastTest.log>")
    try:
        verify(Path(sys.argv[1]).read_text())
    except ValueError as error:
        raise SystemExit(str(error)) from error
    print("cuda_pusch_log_verdicts=pass")
