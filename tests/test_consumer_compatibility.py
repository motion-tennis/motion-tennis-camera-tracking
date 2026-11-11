"""Actual debug-consumer acceptance, independent from exporter unit tests."""

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("tracking_consumer_check", ROOT / "scripts/check_consumer_compatibility.py")
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class ActualDebugConsumerTests(unittest.TestCase):
    def test_exported_poses_rejections_restarts_and_loss_reach_actual_auditor(self):
        debug_root = ROOT.parent / "debug-units"
        if not (debug_root / "scripts/check_trace.py").is_file():
            self.skipTest("Adjacent debug consumer unavailable; no compatibility pass established")
        report = CHECK.check_debug(debug_root)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["consumer"], "debug-units/scripts/check_trace.py:audit")
        self.assertEqual(len(report["cases"]), 7)
        self.assertGreater(report["lost_records"], 0)
        self.assertFalse(report["loss_audit"]["valid_trace"])
        self.assertEqual(report["loss_audit"]["reported_log_drops"], report["lost_records"])


if __name__ == "__main__":
    unittest.main()
