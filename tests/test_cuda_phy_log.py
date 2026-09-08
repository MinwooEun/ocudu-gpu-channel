"""The CUDA gate must grade printed verdicts and complete sweep coverage."""
import importlib.util
from pathlib import Path
import unittest


path = Path(__file__).resolve().parents[1] / "scripts/native/verify-cuda-phy-log.py"
spec = importlib.util.spec_from_file_location("cuda_phy_log", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def successful_log():
    lines = ["436/499 Test: pusch_gpu_cpu_comparison_test"]
    for prb in (3, 4, 5, 6):
        for rx in (1, 2):
            lines.append(f"--- PRB={prb}, Rx Ports={rx} ---")
            lines.extend(f"  SINR={sinr:2d} dB:" for sinr in (5, 10, 15, 20, 25, 30))
    lines.extend([
        "All metrics within tolerance: YES", "<end of output>",
        "441/499 Test: pusch_e2e_pipeline_test",
        "=== Results (100 iterations, 10 warmup skipped) ===",
        "PASS: Both paths decoded all 100 iterations, 0 byte mismatches",
        "<end of output>",
    ])
    return "\n".join(lines)


class VerdictTests(unittest.TestCase):
    def test_complete_sweep_passes(self):
        module.verify(successful_log())

    def test_missing_or_duplicate_condition_fails(self):
        for replacement in ("", "  SINR=10 dB:"):
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                module.verify(successful_log().replace("  SINR= 5 dB:", replacement, 1))

    def test_printed_failure_is_not_exit_code_success(self):
        with self.assertRaises(ValueError):
            module.verify(successful_log().replace("tolerance: YES", "tolerance: NO"))
        with self.assertRaises(ValueError):
            module.verify(successful_log().replace("PASS: Both paths", "*** FAIL: Both paths"))

    def test_gpu_skip_and_nonfinite_metrics_fail(self):
        for marker in ("[SKIP] GPU unavailable", "Max SINR delta: nan dB"):
            with self.subTest(marker=marker), self.assertRaises(ValueError):
                module.verify(successful_log().replace("All metrics", marker + "\nAll metrics"))

    def test_missing_log_or_pipeline_verdict_fails(self):
        with self.assertRaises(ValueError):
            module.verify("")
        with self.assertRaises(ValueError):
            module.verify(successful_log().split("441/499 Test:")[0])
        with self.assertRaises(ValueError):
            module.verify(successful_log().replace("Results (100 iterations", "Results (0 iterations"))


if __name__ == "__main__":
    unittest.main()
