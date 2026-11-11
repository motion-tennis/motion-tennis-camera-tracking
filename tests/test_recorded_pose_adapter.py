"""Acceptance cases for the isolated synthetic/file pose-adapter boundary."""

import base64
import copy
import hashlib
import json
import unittest

from tracking_adapter import RecordedPoseAdapter, ValidationError, validate_manifest
from fixtures import EXAMPLES, MAX_WIRE_UINT64, load_frames, load_manifest, make_frame


class FixtureAndManifestTests(unittest.TestCase):
    def test_saved_fixture_hashes_match_exact_bytes(self):
        evidence = json.loads((EXAMPLES / "fixture-hashes.json").read_text(encoding="utf-8"))
        self.assertIs(evidence["synthetic"], True)
        self.assertEqual(set(evidence["files"]),
                         {"recorded-pose-manifest.json", "recorded-poses.jsonl"})
        for name, expected in evidence["files"].items():
            with self.subTest(name=name):
                self.assertEqual(hashlib.sha256((EXAMPLES / name).read_bytes()).hexdigest(), expected)

    def test_manifest_pins_synthetic_coordinate_and_contract_inputs(self):
        manifest = load_manifest()
        validate_manifest(manifest)
        self.assertIs(manifest["synthetic"], True)
        self.assertEqual(manifest["coordinate_space"], "rectified_normalized_coco17")
        self.assertEqual(manifest["schema_sha256"],
                         "b6728e240316e957f5c5addb973f12f9a57fffbcdacc4331f3db5e06895f360b")
        self.assertEqual(manifest["profile_sha256"],
                         "a3533462fdebfd4c7c2f87eaa3bd579d3056170e3dcfc6a6c68ed34474c1d969")

    def test_unverified_or_incompatible_manifest_is_rejected(self):
        replacements = {
            "format": "other-format", "synthetic": "false",
            "profile_id": "other-profile", "schema_sha256": "0" * 64,
            "profile_sha256": "0" * 64, "sender_session_id": "0" * 32,
            "run_id": "not-a-uuid", "clock_id": 0, "calibration_id": 0,
            "image_width": 0, "coordinate_space": "metric_world_3d",
        }
        for field, value in replacements.items():
            with self.subTest(field=field):
                manifest = load_manifest()
                manifest[field] = value
                with self.assertRaises(ValidationError):
                    validate_manifest(manifest)

    def test_required_manifest_provenance_cannot_be_omitted(self):
        for field in ("model_id", "preprocessing_id", "sender_id", "image_height"):
            with self.subTest(field=field):
                manifest = load_manifest()
                del manifest[field]
                with self.assertRaises(ValidationError):
                    validate_manifest(manifest)

    def test_recorded_input_declaration_is_preserved_without_relabeling(self):
        manifest = load_manifest()
        manifest["synthetic"] = False
        adapter = RecordedPoseAdapter(manifest)
        self.assertTrue(adapter.offer(make_frame(), now_us=1_005_000))
        output = adapter.take(now_us=1_005_000)
        self.assertIs(output["provenance"]["synthetic"], False)


class RecordedPoseAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.manifest = load_manifest()
        self.adapter = RecordedPoseAdapter(self.manifest)

    def assert_rejected(self, frame, code=None, now_us=None):
        if now_us is None:
            now_us = int(frame.get("processing_complete_us", "1005000"))
        self.assertFalse(self.adapter.offer(frame, now_us=now_us))
        self.assertIsInstance(self.adapter.last_rejection, dict)
        self.assertTrue(self.adapter.last_rejection["code"])
        if code is not None:
            self.assertEqual(self.adapter.last_rejection["code"], code)

    def test_four_people_share_one_frame_and_keep_all_joint_values(self):
        raw = make_frame()
        self.assertTrue(self.adapter.offer(raw, now_us=1_005_000))
        output = self.adapter.take(now_us=1_006_000)
        self.assertIsNotNone(output)
        self.assertEqual(len(output["observations"]), 4)
        self.assertEqual(output["frame_status"]["person_ids"], [1, 2, 3, 4])
        self.assertEqual(output["frame_status"]["frame_id"], "1")
        for raw_person, observation in zip(raw["people"], output["observations"]):
            self.assertEqual(observation["frame_id"], raw["frame_id"])
            self.assertEqual(observation["person_id"], raw_person["person_id"])
            self.assertEqual(observation["joints"], raw_person["joints"])
            self.assertEqual(observation["capture"], raw["capture"])
            self.assertEqual(observation["processing_complete_us"], raw["processing_complete_us"])
            self.assertEqual(observation["processing_clock_id"], self.manifest["clock_id"])
            self.assertEqual(observation["image_width"], 1920)
            self.assertEqual(observation["image_height"], 1080)
            self.assertEqual(observation["calibration_id"], 1)
            self.assertFalse({"team", "player_slot", "avatar_id", "world_position"} & set(observation))
        self.assertEqual(output["provenance"]["sender_session_id"], raw["sender_session_id"])
        self.assertEqual(output["provenance"]["arrival_us"], raw["arrival_us"])
        self.assertEqual(output["provenance"]["processing_complete_us"], raw["processing_complete_us"])
        self.assertEqual(output["provenance"]["emitted_us"], "1006000")
        self.assertIsNone(self.adapter.take(now_us=1_006_000))

    def test_offline_envelopes_keep_sender_and_run_byte_identity(self):
        self.adapter.offer(make_frame(), now_us=1_005_000)
        output = self.adapter.take(now_us=1_005_000)
        envelopes = output["envelopes"]
        self.assertEqual(len(envelopes), 5)
        self.assertEqual(sum("skeleton_frame" in envelope for envelope in envelopes), 4)
        self.assertEqual(sum("frame_status" in envelope for envelope in envelopes), 1)
        sequences = []
        for envelope in envelopes:
            self.assertEqual((envelope["major"], envelope["minor"]), (0, 3))
            self.assertEqual(envelope["sender_id"], self.manifest["sender_id"])
            self.assertEqual(base64.b64decode(envelope["sender_session_id"]),
                             bytes.fromhex(self.manifest["sender_session_id"]))
            self.assertEqual(base64.b64decode(envelope["run_id"]),
                             bytes.fromhex(self.manifest["run_id"]))
            sequences.append(int(envelope["message_seq"]))
        self.assertEqual(len(set(sequences)), 5)
        self.assertEqual(sequences, sorted(sequences))

    def test_fixture_replay_is_deterministic_with_caller_times(self):
        def replay():
            adapter = RecordedPoseAdapter(load_manifest())
            results = []
            for raw in load_frames():
                now = int(raw["processing_complete_us"])
                self.assertTrue(adapter.offer(raw, now_us=now))
                results.append(adapter.take(now_us=now))
            return results, adapter.stats, adapter.drain_diagnostics()
        self.assertEqual(replay(), replay())

    def test_explicit_unavailable_joint_retains_supplied_coordinates(self):
        raw = load_frames()[1]
        self.assertTrue(self.adapter.offer(raw, now_us=1_015_000))
        observation = self.adapter.take(now_us=1_015_000)["observations"][0]
        self.assertEqual(len(observation["joints"]), 17)
        self.assertEqual(observation["joints"][16], raw["people"][0]["joints"][16])
        self.assertEqual(observation["joints"][16]["state"], "UNAVAILABLE")

    def test_origin_coordinate_is_a_valid_measurement_not_a_missing_joint(self):
        raw = make_frame()
        raw["people"][0]["joints"][0].update(x_normalized=0.0, y_normalized=0.0)
        self.assertTrue(self.adapter.offer(raw, now_us=1_005_000))
        joint = self.adapter.take(now_us=1_005_000)["observations"][0]["joints"][0]
        self.assertEqual(joint["state"], "TRACKED")
        self.assertEqual((joint["x_normalized"], joint["y_normalized"]), (0.0, 0.0))

    def test_empty_frame_emits_status_without_inventing_people(self):
        raw = make_frame()
        raw["people"] = []
        self.assertTrue(self.adapter.offer(raw, now_us=1_005_000))
        output = self.adapter.take(now_us=1_005_000)
        self.assertEqual(output["observations"], [])
        self.assertEqual(output["frame_status"]["person_ids"], [])
        self.assertEqual(len(output["envelopes"]), 1)

    def test_missing_duplicate_and_out_of_range_joint_indices_are_rejected(self):
        for mutation in ("missing", "extra", "duplicate", "outside"):
            with self.subTest(mutation=mutation):
                raw = make_frame()
                joints = raw["people"][0]["joints"]
                if mutation == "missing":
                    joints.pop()
                elif mutation == "extra":
                    joints.append(copy.deepcopy(joints[0]))
                else:
                    joints[-1]["coco_joint_index"] = 0 if mutation == "duplicate" else 17
                self.assert_rejected(raw)

    def test_nonfinite_out_of_range_and_non_numeric_coordinates_are_rejected(self):
        for coordinate in ("x_normalized", "y_normalized"):
            for value in (float("nan"), float("inf"), float("-inf"), -0.01, 1.01, None, True, "0.5", 10 ** 400):
                with self.subTest(coordinate=coordinate, value=value):
                    raw = make_frame()
                    raw["people"][0]["joints"][0][coordinate] = value
                    self.assert_rejected(raw, "invalid_coordinate")

    def test_invalid_confidence_never_becomes_a_usable_joint(self):
        for value in (float("nan"), float("inf"), -0.01, 1.01, None, True, "0.9", 10 ** 400):
            with self.subTest(value=value):
                raw = make_frame()
                raw["people"][0]["joints"][0]["score"] = value
                self.assert_rejected(raw, "invalid_quality")

    def test_unavailable_state_still_requires_explicit_bounded_joint_values(self):
        raw = make_frame()
        joint = raw["people"][0]["joints"][0]
        joint.update(state="UNAVAILABLE", x_normalized=None)
        self.assert_rejected(raw, "invalid_coordinate")

    def test_unknown_tracking_states_are_rejected(self):
        for where in ("person", "joint"):
            with self.subTest(where=where):
                raw = make_frame()
                target = raw["people"][0] if where == "person" else raw["people"][0]["joints"][0]
                target["state"] = "TRACKING_UNSPECIFIED"
                self.assert_rejected(raw)

    def test_duplicate_people_and_extra_people_are_rejected(self):
        raw = make_frame()
        raw["people"][1]["person_id"] = raw["people"][0]["person_id"]
        self.assert_rejected(raw, "duplicate_person")
        raw = make_frame()
        fifth = copy.deepcopy(raw["people"][0])
        fifth["person_id"] = 5
        raw["people"].append(fifth)
        self.assert_rejected(raw)

    def test_person_identity_must_be_positive_and_uint32_bounded(self):
        for value in (0, -1, True, "1", 1 << 32):
            with self.subTest(value=value):
                raw = make_frame()
                raw["people"][0]["person_id"] = value
                self.assert_rejected(raw)

    def test_frame_and_timestamp_counters_obey_pinned_wire_range(self):
        for field in ("frame_id", "arrival_us", "processing_complete_us", "frames_dropped_total"):
            for value in (str(MAX_WIRE_UINT64 + 1), "-1", "01", 1, True):
                with self.subTest(field=field, value=value):
                    raw = make_frame()
                    raw[field] = value
                    self.assert_rejected(raw, now_us=1_005_000)
        raw = make_frame()
        raw["frame_id"] = "0"
        self.assert_rejected(raw)

    def test_recent_arrival_does_not_hide_stale_capture(self):
        raw = make_frame()
        raw["arrival_us"] = "1100000"
        raw["processing_complete_us"] = "1101000"
        self.assert_rejected(raw, "stale_capture", now_us=1_101_000)

    def test_capture_age_and_uncertainty_boundary_is_inclusive(self):
        raw = make_frame()
        self.assertTrue(self.adapter.offer(raw, now_us=1_079_000))
        self.assertIsNotNone(self.adapter.take(now_us=1_079_000))
        later = make_frame(frame_id=2)
        self.assert_rejected(later, "stale_capture", now_us=1_079_001)

    def test_capture_uncertainty_is_bounded_and_not_implicitly_zero(self):
        for value in (8_001, -1, True, None):
            with self.subTest(value=value):
                raw = make_frame()
                raw["capture"]["uncertainty_us"] = value
                self.assert_rejected(raw)
        raw = make_frame()
        raw["capture"]["uncertainty_us"] = 8_000
        self.assertTrue(self.adapter.offer(raw, now_us=1_005_000))

    def test_unknown_timing_and_other_clock_are_not_replaced_by_arrival(self):
        raw = make_frame()
        raw["capture"]["timing_valid"] = False
        self.assert_rejected(raw, "unknown_timing")
        for boundary in ("PRESENTATION", "IRQ_MONOTONIC", "TIME_UNKNOWN"):
            with self.subTest(boundary=boundary):
                raw = make_frame()
                raw["capture"]["kind"] = boundary
                self.assert_rejected(raw, "unknown_timing")
        raw = make_frame()
        raw["capture"]["clock_id"] = 2
        self.assert_rejected(raw, "clock_mismatch")

    def test_capture_arrival_completion_and_now_keep_their_boundary_order(self):
        for mutation in ("capture_after_arrival", "arrival_after_completion", "completion_after_now"):
            with self.subTest(mutation=mutation):
                raw = make_frame()
                if mutation == "capture_after_arrival":
                    raw["capture"]["value_us"] = "1003000"
                elif mutation == "arrival_after_completion":
                    raw["arrival_us"] = "1006000"
                self.assert_rejected(raw, now_us=1_004_999 if mutation == "completion_after_now" else 1_005_000)

    def test_calibration_revision_mismatch_is_explicit(self):
        raw = make_frame()
        raw["calibration_id"] = 2
        self.assert_rejected(raw, "calibration_mismatch")

    def test_invalid_new_frame_cannot_poison_the_latest_valid_slot(self):
        first = make_frame()
        self.assertTrue(self.adapter.offer(first, now_us=1_005_000))
        bad = make_frame(frame_id=2, capture_us=1_010_000)
        bad["people"][0]["joints"][0]["score"] = float("nan")
        self.assert_rejected(bad, "invalid_quality", now_us=1_015_000)
        output = self.adapter.take(now_us=1_015_000)
        self.assertEqual(output["frame_status"]["frame_id"], "1")
        self.assertEqual(self.adapter.stats["replaced"], 0)
        corrected = make_frame(frame_id=2, capture_us=1_010_000)
        self.assertTrue(self.adapter.offer(corrected, now_us=1_015_000))

    def test_one_slot_replaces_whole_frames_and_reports_drops_separately(self):
        for raw in load_frames():
            self.assertTrue(self.adapter.offer(raw, now_us=int(raw["processing_complete_us"])))
        output = self.adapter.take(now_us=1_035_000)
        self.assertEqual(output["frame_status"]["frame_id"], "4")
        self.assertEqual(output["observations"], [])
        self.assertEqual(self.adapter.stats["replaced"], 2)
        self.assertEqual(self.adapter.stats["frame_sequence_gaps"], 1)
        self.assertEqual(self.adapter.stats["source_frames_dropped_total"], 1)
        self.assertEqual(int(output["frame_status"]["frames_dropped_total"]), 3)
        self.assertEqual(self.adapter.stats["accepted"], 3)
        self.assertEqual(self.adapter.stats["emitted"], 1)

    def test_late_take_expires_pending_frame_and_retains_drop_evidence(self):
        self.adapter.offer(make_frame(), now_us=1_005_000)
        self.assertIsNone(self.adapter.take(now_us=1_079_001))
        self.assertEqual(self.adapter.stats["expired"], 1)
        fresh = make_frame(frame_id=2, capture_us=1_090_000)
        self.assertTrue(self.adapter.offer(fresh, now_us=1_095_000))
        output = self.adapter.take(now_us=1_095_000)
        self.assertEqual(int(output["frame_status"]["frames_dropped_total"]), 1)

    def test_repeated_or_older_frame_id_is_rejected_after_consumption(self):
        self.adapter.offer(make_frame(frame_id=7), now_us=1_005_000)
        self.adapter.take(now_us=1_005_000)
        self.assertEqual(self.adapter.stats["frame_sequence_gaps"], 0)
        self.assert_rejected(make_frame(frame_id=7), "frame_order")
        self.assert_rejected(make_frame(frame_id=6), "frame_order")

    def test_regressing_source_loss_counter_is_rejected_without_overwriting_pending(self):
        self.adapter.offer(make_frame(dropped=4), now_us=1_005_000)
        self.assert_rejected(make_frame(frame_id=2, capture_us=1_010_000, dropped=3),
                             "source_counter_regression", now_us=1_015_000)
        output = self.adapter.take(now_us=1_015_000)
        self.assertEqual(output["frame_status"]["frame_id"], "1")
        self.assertEqual(int(output["frame_status"]["frames_dropped_total"]), 4)

    def test_offer_does_not_implicitly_adopt_a_new_tracker_session(self):
        self.adapter.offer(make_frame(), now_us=1_005_000)
        foreign = make_frame(frame_id=2, capture_us=1_010_000)
        foreign["sender_session_id"] = "3" * 32
        self.assert_rejected(foreign, "session_mismatch", now_us=1_015_000)
        self.assertEqual(self.adapter.take(now_us=1_015_000)["frame_status"]["frame_id"], "1")

    def test_explicit_session_restart_flushes_pending_and_scopes_reused_person_ids(self):
        self.adapter.offer(make_frame(frame_id=8, dropped=5), now_us=1_005_000)
        replacement = load_manifest()
        replacement["sender_session_id"] = "3" * 32
        self.adapter.start_session(replacement)
        self.assertEqual(self.adapter.stats["session_flushes"], 1)
        self.assertEqual(self.adapter.stats["session_restarts"], 1)
        self.assertIsNone(self.adapter.take(now_us=1_005_000))
        self.assert_rejected(make_frame(frame_id=9), "session_mismatch")
        reused = make_frame(frame_id=1, capture_us=1_010_000)
        reused["sender_session_id"] = replacement["sender_session_id"]
        self.assertTrue(self.adapter.offer(reused, now_us=1_015_000))
        output = self.adapter.take(now_us=1_015_000)
        self.assertEqual(output["provenance"]["sender_session_id"], replacement["sender_session_id"])
        self.assertEqual(output["frame_status"]["person_ids"], [1, 2, 3, 4])
        self.assertEqual(int(output["frame_status"]["frames_dropped_total"]), 0)
        self.assertTrue(self.adapter.drain_diagnostics())

    def test_invalid_or_same_session_restart_preserves_pending_work(self):
        self.adapter.offer(make_frame(), now_us=1_005_000)
        with self.assertRaises(ValidationError):
            self.adapter.start_session(load_manifest())
        invalid = load_manifest()
        invalid["sender_session_id"] = "3" * 32
        invalid["synthetic"] = "false"
        with self.assertRaises(ValidationError):
            self.adapter.start_session(invalid)
        self.assertEqual(self.adapter.take(now_us=1_005_000)["frame_status"]["frame_id"], "1")

    def test_retired_session_identity_cannot_be_reused_after_another_restart(self):
        second_session = load_manifest()
        second_session["sender_session_id"] = "3" * 32
        self.adapter.start_session(second_session)
        current = make_frame()
        current["sender_session_id"] = second_session["sender_session_id"]
        self.assertTrue(self.adapter.offer(current, now_us=1_005_000))
        with self.assertRaises(ValidationError):
            self.adapter.start_session(load_manifest())
        output = self.adapter.take(now_us=1_005_000)
        self.assertEqual(output["provenance"]["sender_session_id"], second_session["sender_session_id"])

    def test_bounded_session_history_refuses_new_sessions_without_forgetting_old_ids(self):
        for identity in range(1, 64):
            manifest = load_manifest()
            manifest["sender_session_id"] = format(identity, "032x")
            self.adapter.start_session(manifest)
        latest = make_frame()
        latest["sender_session_id"] = manifest["sender_session_id"]
        self.assertTrue(self.adapter.offer(latest, now_us=1_005_000))
        overflow = load_manifest()
        overflow["sender_session_id"] = format(64, "032x")
        with self.assertRaises(ValidationError):
            self.adapter.start_session(overflow)
        self.assertEqual(self.adapter.stats["session_restarts"], 63)
        self.assertEqual(self.adapter.take(now_us=1_005_000)["provenance"]["sender_session_id"],
                         latest["sender_session_id"])

    def test_observation_clock_regression_cannot_emit_backwards_timestamps(self):
        self.adapter.offer(make_frame(), now_us=1_005_000)
        first = self.adapter.take(now_us=1_070_000)
        second = make_frame(frame_id=2, capture_us=1_010_000)
        self.assert_rejected(second, "clock_regression", now_us=1_020_000)
        self.assertTrue(self.adapter.offer(second, now_us=1_071_000))
        output = self.adapter.take(now_us=1_072_000)
        self.assertGreater(int(output["envelopes"][0]["sent_time_us"]),
                           int(first["envelopes"][-1]["sent_time_us"]))

    def test_invalid_take_time_keeps_the_valid_pending_frame(self):
        self.adapter.offer(make_frame(), now_us=1_005_000)
        with self.assertRaises(ValidationError):
            self.adapter.take(now_us=1_004_999)
        self.assertEqual(self.adapter.stats["expired"], 0)
        output = self.adapter.take(now_us=1_006_000)
        self.assertEqual(output["frame_status"]["frame_id"], "1")

    def test_malformed_json_shapes_fail_without_leaking_type_errors(self):
        for malformed in (None, [], "frame", {"frame_id": "1"}):
            with self.subTest(malformed=malformed):
                self.assert_rejected(malformed, now_us=1_005_000)
        for path in ("capture_kind", "person_state", "joint_state"):
            with self.subTest(path=path):
                raw = make_frame()
                if path == "capture_kind":
                    raw["capture"]["kind"] = []
                elif path == "person_state":
                    raw["people"][0]["state"] = {}
                else:
                    raw["people"][0]["joints"][0]["state"] = []
                self.assert_rejected(raw, now_us=1_005_000)

    def test_diagnostics_are_bounded_and_drain_without_resetting_accounting(self):
        for _ in range(100):
            raw = make_frame()
            raw["capture"]["timing_valid"] = False
            self.assertFalse(self.adapter.offer(raw, now_us=1_005_000))
        diagnostics = self.adapter.drain_diagnostics()
        self.assertGreater(len(diagnostics), 0)
        self.assertLessEqual(len(diagnostics), 64)
        self.assertGreater(self.adapter.stats["diagnostics_dropped"], 0)
        self.assertEqual(self.adapter.stats["rejected"], 100)
        self.assertEqual(self.adapter.drain_diagnostics(), [])

    def test_diagnostics_preserve_source_boundaries_and_remain_strict_json(self):
        raw = make_frame()
        self.adapter.offer(raw, now_us=1_005_000)
        self.adapter.take(now_us=1_006_000)
        invalid = make_frame(frame_id=2, capture_us=1_010_000)
        invalid["people"][0]["joints"][0]["score"] = float("nan")
        self.assertFalse(self.adapter.offer(invalid, now_us=1_015_000))
        records = self.adapter.drain_diagnostics()
        json.dumps(records, allow_nan=False)
        emitted = next(record for record in records if record["event"] == "frame_emitted")
        self.assertEqual(emitted["source_session_id"], self.manifest["sender_session_id"])
        self.assertEqual(emitted["clock_id"], str(self.manifest["clock_id"]))
        self.assertEqual(emitted["mono_us"], "1006000")
        self.assertEqual(emitted["details"]["frame_id"], raw["frame_id"])
        self.assertEqual(emitted["details"]["capture"], raw["capture"])
        self.assertEqual(emitted["details"]["arrival_us"], raw["arrival_us"])
        self.assertEqual(emitted["details"]["processing_complete_us"], raw["processing_complete_us"])

    def test_caller_mutation_cannot_change_validated_pending_observations(self):
        raw = make_frame()
        self.assertTrue(self.adapter.offer(raw, now_us=1_005_000))
        raw["people"][0]["joints"][0]["x_normalized"] = float("nan")
        raw["people"].clear()
        self.manifest["image_width"] = 1
        output = self.adapter.take(now_us=1_005_000)
        self.assertEqual(len(output["observations"]), 4)
        self.assertEqual(output["observations"][0]["joints"][0]["x_normalized"], 0.5)
        self.assertEqual(output["observations"][0]["image_width"], 1920)
        stats = self.adapter.stats
        stats["accepted"] = -1
        self.assertEqual(self.adapter.stats["accepted"], 1)


if __name__ == "__main__":
    unittest.main()
