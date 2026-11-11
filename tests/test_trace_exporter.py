"""Producer trace records, honest gaps and actual offline-consumer checks.

Consumer-positive cases explicitly add the existing synthetic controller
fixture. They establish trace ingestion, never pose semantics or live timing.
"""

from contextlib import redirect_stderr, redirect_stdout
import copy
import io
import json
from pathlib import Path
import sys
import unittest

from fixtures import EXAMPLES, load_manifest, make_frame
from tracking_adapter import RecordedPoseAdapter, ValidationError, validate_manifest
from tracking_adapter.__main__ import main
from tracking_adapter.trace import MAX_TRACE_SEQUENCE


DEBUG = Path(__file__).resolve().parents[2] / "debug-units"


def audit_with_declared_synthetic_controllers(bundle):
    """Add a labeled controller fixture; tracking supplies no controller data."""
    if not (DEBUG / "scripts/check_trace.py").is_file():
        raise unittest.SkipTest("Sibling debug auditor is unavailable; consumer compatibility unverified")
    sys.path.insert(0, str(DEBUG / "scripts"))
    from check_trace import audit
    fixture = [json.loads(line) for line in
               (DEBUG / "examples/synthetic-trace.jsonl").read_text(encoding="utf-8").splitlines()]
    fixture[0] = copy.deepcopy(bundle["header"])
    fixture[0]["controller_evidence"] = "Explicitly synthetic existing debug fixture, not adapter output."
    for record in fixture[1:]:
        record["run_id"] = bundle["header"]["run_id"]
    return audit(fixture + copy.deepcopy(bundle["events"]))


class TraceExporterTests(unittest.TestCase):
    def setUp(self):
        self.manifest = load_manifest()
        self.adapter = RecordedPoseAdapter(self.manifest)

    def emit_frame(self):
        raw = make_frame()
        self.assertTrue(self.adapter.offer(raw, now_us=1_005_000))
        result = self.adapter.take(now_us=1_006_000)
        return raw, result

    def test_events_are_trace_v1_at_creation_with_raw_boundaries_and_pose_identity(self):
        raw, output = self.emit_frame()
        bundle = self.adapter.export_trace()[0]
        self.assertTrue(bundle["header"]["tracking_trace"]["complete_source_diagnostics"])
        self.assertEqual(bundle["untimed_metadata"], [])
        events = bundle["events"]
        self.assertEqual([record["event_seq"] for record in events], ["0", "1"])
        for record in events:
            self.assertEqual(record["record_type"], "event")
            self.assertEqual(record["run_id"], self.manifest["run_id"])
            self.assertEqual(record["source_id"], "301")
            self.assertEqual(record["source_session_id"], self.manifest["sender_session_id"])
            self.assertEqual(record["clock_id"], "1")
            self.assertIsNone(record["transaction"])
            self.assertEqual(record["details"]["capture"], raw["capture"])
            self.assertIsNone(record["details"]["capture_uncertainty_us"])
            self.assertTrue(record["details"]["capture_uncertainty_reason"])
            self.assertEqual(record["details"]["clock_mapping_status"], "unavailable")
        emitted = events[-1]
        self.assertEqual(emitted["mono_us"], "1006000")
        self.assertNotEqual(emitted["mono_us"], raw["capture"]["value_us"])
        self.assertEqual(emitted["details"]["observations"], output["observations"])
        self.assertEqual(emitted["details"]["frame_status"], output["frame_status"])
        self.assertEqual(emitted["details"]["message_sequences"],
                         [envelope["message_seq"] for envelope in output["envelopes"]])
        json.dumps(bundle, allow_nan=False)

    def test_actual_auditor_accepts_export_with_explicit_synthetic_controller_fixture(self):
        self.emit_frame()
        bundle = self.adapter.export_trace()[0]
        report = audit_with_declared_synthetic_controllers(bundle)
        self.assertTrue(report["valid_trace"], report["errors"])
        self.assertEqual(report["started_transactions"], 5)
        self.assertEqual(report["event_counts"]["frame_emitted"], 1)

    def test_tracking_only_export_does_not_invent_controller_measurements(self):
        self.emit_frame()
        bundle = self.adapter.export_trace()[0]
        audit_with_declared_synthetic_controllers(bundle)
        from check_trace import audit
        report = audit([bundle["header"]] + bundle["events"])
        self.assertFalse(report["valid_trace"])
        self.assertEqual(report["started_transactions"], 0)
        self.assertEqual(report["errors"], ["trace contains no started measurement transactions"])

    def test_sequences_survive_drain_and_never_restart_at_zero_in_same_session(self):
        self.adapter.offer(make_frame(), now_us=1_005_000)
        first = self.adapter.drain_diagnostics()
        self.adapter.take(now_us=1_006_000)
        second = self.adapter.drain_diagnostics()
        self.assertEqual(first[0]["event_seq"], "0")
        self.assertEqual(second[0]["event_seq"], "1")
        self.assertEqual(self.adapter.drain_diagnostics(), [])

    def test_overflow_preserves_sequence_gaps_and_reports_all_lost_records(self):
        invalid = make_frame()
        invalid["capture"]["timing_valid"] = False
        for index in range(100):
            self.assertFalse(self.adapter.offer(invalid, now_us=1_005_000 + index))
        bundle = self.adapter.export_trace()[0]
        self.assertLessEqual(len(bundle["events"]), 64)
        sequences = [int(event["event_seq"]) for event in bundle["events"]]
        self.assertEqual(sequences, sorted(set(sequences)))
        self.assertGreater(sequences[0], 0)
        dropped = self.adapter.stats["diagnostics_dropped"]
        notices = [event for event in bundle["events"] if event["event"] == "log_drop"]
        self.assertEqual(sum(int(event["details"]["count"]) for event in notices), dropped)
        self.assertEqual(notices[-1]["mono_us"], "1005099")
        report = audit_with_declared_synthetic_controllers(bundle)
        self.assertFalse(report["valid_trace"])
        self.assertEqual(report["reported_log_drops"], dropped)
        self.assertEqual(report["source_sequence_gaps"], dropped)
        self.assertFalse(bundle["header"]["tracking_trace"]["complete_source_diagnostics"])

    def test_rejections_are_correlated_without_copying_invalid_values_into_trace(self):
        invalid = make_frame()
        invalid["people"][0]["joints"][0]["score"] = float("nan")
        self.assertFalse(self.adapter.offer(invalid, now_us=1_005_000))
        bundle = self.adapter.export_trace()[0]
        record = bundle["events"][0]
        self.assertEqual(record["event"], "frame_rejected")
        self.assertEqual(record["details"]["code"], "invalid_quality")
        self.assertEqual(record["details"]["frame_id"], "1")
        self.assertEqual(record["details"]["input_capture"], invalid["capture"])
        self.assertEqual(record["details"]["input_person_ids"], ["1", "2", "3", "4"])
        json.dumps(bundle, allow_nan=False)

    def test_unknown_rejection_time_is_metadata_and_never_fabricated_zero(self):
        self.adapter.offer(make_frame(), now_us=1_005_000)
        self.assertFalse(self.adapter.offer(make_frame(frame_id=2), now_us=1_004_000))
        bundle = self.adapter.export_trace()[0]
        self.assertEqual(len(bundle["events"]), 1)
        self.assertEqual(bundle["events"][0]["mono_us"], "1005000")
        self.assertEqual(bundle["untimed_metadata"][0]["details"]["code"], "clock_regression")
        self.assertIsNone(bundle["untimed_metadata"][0]["mono_us"])
        self.assertFalse(bundle["header"]["tracking_trace"]["complete_source_diagnostics"])

    def test_untimed_metadata_is_bounded_and_its_own_loss_stays_visible(self):
        for _ in range(100):
            self.assertFalse(self.adapter.offer(make_frame(), now_us=None))
        bundle = self.adapter.export_trace()[0]
        self.assertEqual(bundle["events"], [])
        self.assertEqual(len(bundle["untimed_metadata"]), 64)
        source = bundle["header"]["tracking_trace"]["sources"][0]
        self.assertEqual(source["untimed_records_total"], "100")
        self.assertEqual(source["untimed_metadata_dropped_total"], "36")
        self.assertFalse(bundle["header"]["tracking_trace"]["complete_source_diagnostics"])

    def test_supplied_old_and_new_native_times_fence_restarts_without_clock_guessing(self):
        self.adapter.offer(make_frame(), now_us=1_005_000)
        new = load_manifest()
        new["sender_session_id"] = "3" * 32
        new["clock_id"] = 2
        self.adapter.start_session(new, now_us=10, previous_session_now_us=1_006_000)
        bundle = self.adapter.export_trace()[0]
        self.assertEqual(bundle["untimed_metadata"], [])
        flushed = next(event for event in bundle["events"] if event["event"] == "session_frame_flushed")
        started = next(event for event in bundle["events"] if event["event"] == "session_started")
        self.assertEqual((flushed["mono_us"], flushed["clock_id"]), ("1006000", "1"))
        self.assertEqual((started["mono_us"], started["clock_id"]), ("10", "2"))
        self.assertEqual(started["event_seq"], "0")

    def test_new_session_time_does_not_timestamp_old_flush_even_with_same_clock_number(self):
        self.adapter.offer(make_frame(), now_us=1_005_000)
        new = load_manifest()
        new["sender_session_id"] = "3" * 32
        self.adapter.start_session(new, now_us=10)
        bundle = self.adapter.export_trace()[0]
        self.assertTrue(any(record["event"] == "session_frame_flushed" and record["mono_us"] is None
                            for record in bundle["untimed_metadata"]))
        self.assertFalse(bundle["header"]["tracking_trace"]["complete_source_diagnostics"])

    def test_invalid_restart_boundaries_leave_pending_frame_and_session_unchanged(self):
        self.adapter.offer(make_frame(), now_us=1_005_000)
        new = load_manifest()
        new["sender_session_id"] = "3" * 32
        with self.assertRaises(ValidationError):
            self.adapter.start_session(new, now_us=10, previous_session_now_us=1_004_000)
        output = self.adapter.take(now_us=1_006_000)
        self.assertEqual(output["provenance"]["sender_session_id"], self.manifest["sender_session_id"])

    def test_mixed_runs_keep_original_record_identities_and_separate_headers(self):
        self.emit_frame()
        new = load_manifest()
        new.update(sender_session_id="3" * 32, run_id="4" * 32)
        self.adapter.start_session(new)
        frame = make_frame()
        frame["sender_session_id"] = new["sender_session_id"]
        self.adapter.offer(frame, now_us=1_005_000)
        self.adapter.take(now_us=1_006_000)
        bundles = self.adapter.export_trace()
        self.assertEqual([bundle["header"]["run_id"] for bundle in bundles],
                         [self.manifest["run_id"], new["run_id"]])
        for bundle in bundles:
            self.assertTrue(all(event["run_id"] == bundle["header"]["run_id"] for event in bundle["events"]))
        self.assertTrue(all(event["source_session_id"] == self.manifest["sender_session_id"]
                            for event in bundles[0]["events"]))
        self.assertTrue(all(event["source_session_id"] == new["sender_session_id"]
                            for event in bundles[1]["events"]))

    def test_overwritten_old_source_loss_stays_explicit_when_its_native_clock_is_gone(self):
        self.emit_frame()
        new = load_manifest()
        new.update(sender_session_id="3" * 32, run_id="4" * 32)
        self.adapter.start_session(new, now_us=1_006_000)
        bad = make_frame()
        bad["sender_session_id"] = new["sender_session_id"]
        bad["capture"]["timing_valid"] = False
        for index in range(100):
            self.adapter.offer(bad, now_us=1_007_000 + index)
        old = self.adapter.export_trace()[0]
        self.assertEqual(old["events"], [])
        loss = next(record for record in old["untimed_metadata"] if record["event"] == "unreported_log_loss")
        self.assertGreater(int(loss["details"]["count"]), 0)
        self.assertIsNone(loss["mono_us"])
        self.assertFalse(old["header"]["tracking_trace"]["complete_source_diagnostics"])

    def test_trace_sequence_exhaustion_never_wraps_and_new_session_restores_identity(self):
        key = self.adapter._trace.key(self.manifest)
        self.adapter._trace.sessions[key]["next_seq"] = MAX_TRACE_SEQUENCE
        self.emit_frame()
        exhausted = self.adapter.export_trace()[0]
        self.assertEqual(exhausted["events"][0]["event_seq"], str(MAX_TRACE_SEQUENCE))
        self.assertTrue(exhausted["header"]["tracking_trace"]["sources"][0]["sequence_exhausted"])
        self.assertTrue(any(record["event"] == "trace_sequence_exhausted" for record in exhausted["untimed_metadata"]))
        new = load_manifest()
        new["sender_session_id"] = "3" * 32
        self.adapter.start_session(new, now_us=1_007_000)
        records = self.adapter.export_trace()[0]["events"]
        self.assertEqual(records[0]["event_seq"], "0")

    def test_header_uses_explicit_validated_manifest_limits_and_rejects_run_redefinition(self):
        manifest = load_manifest()
        manifest["trace_limits"] = {"response_deadline_us": "25000", "electrical_deadline_us": "35000",
                                    "transaction_timeout_us": "50000"}
        adapter = RecordedPoseAdapter(manifest)
        header = adapter.export_trace()[0]["header"]
        self.assertEqual(header["response_deadline_us"], "25000")
        self.assertEqual(header["trace_limits_source"], "manifest")
        new = copy.deepcopy(manifest)
        new["sender_session_id"] = "3" * 32
        new["trace_limits"]["response_deadline_us"] = "26000"
        with self.assertRaises(ValidationError):
            adapter.start_session(new)
        for limits in ({"response_deadline_us": "0", "electrical_deadline_us": "40000", "transaction_timeout_us": "50000"},
                       {"response_deadline_us": "40000", "electrical_deadline_us": "30000", "transaction_timeout_us": "50000"}):
            manifest["trace_limits"] = limits
            with self.assertRaises(ValidationError):
                validate_manifest(manifest)

    def test_trace_cli_prints_actual_trace_records_and_separate_summary(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main([str(EXAMPLES / "recorded-poses.jsonl"), "--manifest",
                         str(EXAMPLES / "recorded-pose-manifest.json"), "--format", "trace-v1"])
        self.assertEqual(code, 0)
        records = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual(records[0]["record_type"], "run")
        self.assertTrue(all(record["record_type"] == "event" for record in records[1:]))
        self.assertFalse(any(record.get("event") == "transaction_start" for record in records[1:]))
        self.assertEqual(json.loads(stderr.getvalue())["type"], "trace_summary")


if __name__ == "__main__":
    unittest.main()
