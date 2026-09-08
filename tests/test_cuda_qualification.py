import copy
import importlib.util
from pathlib import Path
import unittest


def module(name):
    path = Path(__file__).resolve().parents[1] / 'scripts/native' / name
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class KpiEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.summarize = module('verify-cuda-kpis.py').summarize
        row = dict(rnti=1, pci=1, ul_nof_ok=9, ul_nof_nok=1,
                   dl_nof_ok=10, dl_nof_nok=0, pusch_snr_db=20, ul_mcs=10, dl_mcs=11)
        self.records = [dict(monotonic_seconds=100+i, rows=[copy.deepcopy(row)]) for i in range(60)]

    def test_report_average(self):
        self.assertEqual(self.summarize(self.records)['mean']['ul_bler_percent'], 10)

    def test_missing_reports_or_traffic_fail(self):
        with self.assertRaises(ValueError):
            self.summarize(self.records[:-1])
        self.records[2]['rows'][0].update(ul_nof_ok=0, ul_nof_nok=0)
        with self.assertRaises(ValueError):
            self.summarize(self.records)

    def test_stale_or_missing_sinr_fails(self):
        for value in (None, -99.9, float('nan')):
            self.records[5]['rows'][0]['pusch_snr_db'] = value
            with self.assertRaises(ValueError):
                self.summarize(self.records)

    def test_reconnect_and_report_gap_fail(self):
        self.records[3]['rows'][0]['rnti'] = 2
        with self.assertRaises(ValueError):
            self.summarize(self.records)
        self.records[3]['rows'][0]['rnti'] = 1
        self.records[4]['monotonic_seconds'] += 2
        with self.assertRaises(ValueError):
            self.summarize(self.records)

    def test_forced_grid_prerequisites(self):
        configure = module('disable-gnb-cuda.py').configure
        base = 'ru_sdr:\n  device_driver: zmq\n'
        self.assertIn('ul_cuda_visible_grid_mode: pinned', configure(base))
        self.assertIn('ul_cuda_visible_grid_mode: managed', configure(base, 'low-phy-rx'))
        self.assertIn('dl_cuda_visible_grid_mode: managed', configure(base, 'low-phy-tx'))

    def test_latency_boundary_is_exact_and_missing_nodes_fail(self):
        compare = module('qualify-cuda-stages.py').compare_latency
        reference = dict(gnb0=80, ue0=80)
        self.assertTrue(compare(reference, dict(gnb0=84, ue0=76))[1])
        self.assertFalse(compare(reference, dict(gnb0=85, ue0=80))[1])
        self.assertFalse(compare(reference, dict(gnb0=80, ue0=75))[1])
        self.assertFalse(compare(reference, dict(gnb0=80))[1])


if __name__ == '__main__':
    unittest.main()
