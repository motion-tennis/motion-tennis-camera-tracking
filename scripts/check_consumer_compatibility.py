#!/usr/bin/env python3
"""Exercise actual S1 tracking output through the physics and debug consumers.

Only the fixture controller records, confirmed bindings and Pi map are
synthetic test infrastructure. No sensor, clock fitting or network is involved.
"""

import argparse
import base64
from copy import deepcopy
from datetime import date
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tracking_adapter import RecordedPoseAdapter  # noqa: E402


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "Cannot load " + str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_debug(debug_root):
    scripts = debug_root / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        return load_module("motion_tennis_consumer_auditor", scripts / "check_trace.py")
    finally:
        sys.path.pop(0)


def fixtures():
    manifest = json.loads((ROOT / "examples/recorded-pose-manifest.json").read_text(encoding="utf-8"))
    frames = [json.loads(line) for line in (ROOT / "examples/recorded-poses.jsonl").read_text(encoding="utf-8").splitlines()
              if line.strip()]
    return manifest, frames


def emitted_examples():
    manifest, frames = fixtures()
    adapter = RecordedPoseAdapter(manifest)
    emitted = []
    for frame in frames:
        now = int(frame["processing_complete_us"])
        require(adapter.offer(frame, now_us=now), "Checked-in frame rejected: " + str(adapter.last_rejection))
        result = adapter.take(now_us=now)
        require(result is not None, "Checked-in frame was suppressed")
        emitted.append(result)
    return manifest, frames, adapter, emitted


def audit_bundle(auditor, debug_root, bundle, include_controllers=True):
    """Merge actual tracking records with explicitly declared controller fixtures."""
    header = deepcopy(bundle["header"])
    events = deepcopy(bundle["events"])
    require(header["synthetic"] is True, "This bench merges synthetic fixtures only")
    if include_controllers:
        controller_records = [json.loads(line) for line in (debug_root / "examples/synthetic-trace.jsonl").read_text(encoding="utf-8").splitlines()
                              if line.strip()][1:]
        for record in controller_records:
            record["run_id"] = header["run_id"]
        events.extend(controller_records)
        header["compatibility_fixture"] = "Actual tracking events plus the separately declared synthetic controller fixture"
    return auditor.audit([header] + events)


def check_debug(debug_root):
    auditor = load_debug(debug_root)
    manifest, frames, adapter, emitted = emitted_examples()
    bundles = adapter.export_trace()
    require(len(bundles) == 1, "One replay run must export one trace bundle")
    bundle = bundles[0]
    events = bundle["events"]
    require(bundle["header"]["tracking_trace"]["complete_source_diagnostics"], "Clean source diagnostics were marked incomplete")
    require(bundle["header"]["run_id"] == manifest["run_id"], "Trace lost its run identity")
    require(all(event["transaction"] is None for event in events), "Tracking fabricated a controller transaction")
    require([int(event["event_seq"]) for event in events] == list(range(len(events))),
            "Clean producer event sequence is not original and contiguous")
    require(all(event["source_id"] == str(manifest["sender_id"])
                and event["source_session_id"] == manifest["sender_session_id"]
                and event["clock_id"] == str(manifest["clock_id"]) for event in events),
            "Trace source identities were not normalized losslessly")
    emitted_events = [event for event in events if event["event"] == "frame_emitted"]
    require(len(emitted_events) == len(emitted), "Missing emitted-frame diagnostics")
    for event, result in zip(emitted_events, emitted):
        details = event["details"]
        require(details["observations"] == result["observations"], "Trace changed pose values or states")
        require(details["frame_status"] == result["frame_status"], "Trace changed frame membership or drops")
        require(event["mono_us"] == result["provenance"]["emitted_us"], "Emission timestamp was relabelled")
        for envelope in result["envelopes"]:
            require(base64.b64decode(envelope["sender_session_id"]).hex() == event["source_session_id"],
                    "Wire and trace source UUIDs differ")
        require(details["observations"] == [] or details["observations"][0]["capture"] == result["provenance"]["capture"],
                "Capture provenance was lost")
    clean = audit_bundle(auditor, debug_root, bundle)
    require(clean["valid_trace"], "Real debug auditor rejected exported records: " + str(clean["errors"]))
    tracking_only = audit_bundle(auditor, debug_root, bundle, include_controllers=False)
    require(tracking_only["errors"] == ["trace contains no started measurement transactions"],
            "Tracking-only trace either fabricated measurements or has structural errors")

    rejecting = RecordedPoseAdapter(manifest)
    bad = deepcopy(frames[0])
    bad["calibration_id"] += 1
    require(not rejecting.offer(bad, now_us=int(bad["processing_complete_us"])), "Calibration rejection disappeared")
    reject_bundle = rejecting.export_trace()[0]
    rejected_report = audit_bundle(auditor, debug_root, reject_bundle)
    require(rejected_report["valid_trace"], "Truthful rejection record is not trace-v1 compatible")
    require(any(event["event"] == "frame_rejected" and event["details"]["code"] == "calibration_mismatch"
                for event in reject_bundle["events"]), "Trace lacks explicit rejection reason")

    lossy = RecordedPoseAdapter(manifest)
    for _ in range(100):
        require(not lossy.offer(bad, now_us=int(bad["processing_complete_us"])), "Invalid fixture was admitted")
    loss_stats = lossy.stats
    loss_bundle = lossy.export_trace()[0]
    require(not loss_bundle["header"]["tracking_trace"]["complete_source_diagnostics"], "Loss was hidden in the source header")
    loss_report = audit_bundle(auditor, debug_root, loss_bundle)
    require(not loss_report["valid_trace"], "Lost records became a passing audit")
    require(loss_report["source_sequence_gaps"] > 0, "Buffer overflow was hidden by renumbering")
    require(loss_report["reported_log_drops"] == loss_stats["diagnostics_dropped"] > 0,
            "Explicit loss deltas differ from actual producer loss")

    restarting = RecordedPoseAdapter(manifest)
    first = frames[0]
    require(restarting.offer(first, now_us=int(first["processing_complete_us"])), "Restart fixture rejected")
    next_manifest = deepcopy(manifest)
    next_manifest["sender_session_id"] = "33" * 16
    next_frame = deepcopy(first)
    next_frame["sender_session_id"] = next_manifest["sender_session_id"]
    restarting.start_session(next_manifest, now_us=1_006_000, previous_session_now_us=1_006_000)
    require(not restarting.offer(first, now_us=1_006_000), "Old tracker session was admitted")
    require(restarting.offer(next_frame, now_us=1_006_000), "New session could not reuse frame/person numbers")
    require(restarting.take(now_us=1_006_000) is not None, "New session output suppressed")
    restart_bundle = restarting.export_trace()[0]
    restart_report = audit_bundle(auditor, debug_root, restart_bundle)
    require(restart_report["valid_trace"], "Session restart trace has identity/time/sequence conflicts")
    for session in (manifest["sender_session_id"], next_manifest["sender_session_id"]):
        sequences = [int(event["event_seq"]) for event in restart_bundle["events"] if event["source_session_id"] == session]
        require(sequences and sequences == list(range(len(sequences))), "Restart renumbered or mixed source sessions")

    mixed = RecordedPoseAdapter(manifest)
    require(mixed.offer(first, now_us=int(first["processing_complete_us"])), "Mixed-run fixture rejected")
    other_manifest = deepcopy(next_manifest)
    other_manifest["run_id"] = "44" * 16
    mixed.start_session(other_manifest)
    other_frame = deepcopy(first)
    other_frame["sender_session_id"] = other_manifest["sender_session_id"]
    require(mixed.offer(other_frame, now_us=int(other_frame["processing_complete_us"])), "Second run fixture rejected")
    mixed.take(now_us=int(other_frame["processing_complete_us"]))
    mixed_bundles = mixed.export_trace()
    require({item["header"]["run_id"] for item in mixed_bundles} == {manifest["run_id"], other_manifest["run_id"]},
            "Session transition overwrote an earlier run identity")
    untimed = []
    for item in mixed_bundles:
        require(all(event["run_id"] == item["header"]["run_id"] for event in item["events"]), "Run records mixed")
        if item["untimed_metadata"]:
            require(not item["header"]["tracking_trace"]["complete_source_diagnostics"], "Unknown lifecycle time became complete evidence")
        untimed.extend(item["untimed_metadata"])
    require(untimed, "Lifecycle without a known clock boundary was silently omitted")
    require(all("mono_us" not in item or item["mono_us"] is None for item in untimed),
            "Unknown lifecycle time was fabricated")
    return {"status": "passed", "consumer": "debug-units/scripts/check_trace.py:audit",
            "cases": ["actual_pose_and_identity_preservation", "clean_trace_with_declared_controller_fixture",
                      "tracking_only_has_no_controller_measurements", "rejection_reason", "overflow_and_loss",
                      "old_session_rejection_and_restart", "mixed_runs_and_untimed_lifecycle"],
            "clean_tracking_records": len(events), "lost_records": loss_stats["diagnostics_dropped"],
            "loss_audit": {"valid_trace": loss_report["valid_trace"],
                           "source_sequence_gaps": loss_report["source_sequence_gaps"],
                           "reported_log_drops": loss_report["reported_log_drops"]},
            "limits": "Debug validates trace integrity; these independent checks validate the exercised pose/identity fields. Controller records are explicitly synthetic."}


def run_checked(args, cwd):
    result = subprocess.run(args, cwd=cwd, text=True, encoding="utf-8", capture_output=True)
    if result.returncode:
        raise ValueError("Command failed: " + " ".join(map(str, args)) + "\n" + result.stdout[-8000:] + result.stderr[-8000:])
    return result


def _uuid_literal(value):
    raw = base64.b64decode(value, validate=True)
    require(len(raw) == 16, "Expected an exact wire UUID")
    return "Uuid{" + ",".join(str(item) for item in raw) + "}"


def _float_literal(value):
    import struct
    rounded = struct.unpack("<f", struct.pack("<f", value))[0]
    text = repr(rounded)
    if "." not in text and "e" not in text.lower():
        text += ".0"
    return text + "f"


def write_cpp_fixtures(destination, results):
    """Project actual generated-codec JSON fields into the real typed C++ API.

    The caller's wire check runs first. No values are inferred from player order
    and no camera coordinate is converted to a physical or metric position.
    """
    state_names = {"TRACKED": "Tracked", "INFERRED": "Inferred", "UNAVAILABLE": "Unavailable"}
    time_names = {"DRIVER_FRAME": "DriverFrame", "SENSOR_CAPTURE": "SensorCapture"}
    lines = ["#pragma once", '#include "motion_tennis/physics/tracking_pose_bridge.hpp"',
             "namespace actual_tracking_fixture {", "using namespace motion_tennis::physics;"]
    for index, result in enumerate(results):
        lines.extend(["inline TrackingFrameBatch frame_" + str(index) + "() {", "  TrackingFrameBatch batch;"])
        for envelope in result["envelopes"]:
            status = "frame_status" in envelope
            name = "batch.status_envelope" if status else "packet.envelope"
            if not status:
                lines.extend(["  {", "  TrackingPersonPacket packet;"])
            for field in ("major", "minor", "sender_id", "message_seq", "sent_time_us", "clock_id"):
                lines.append("  " + name + "." + field + " = " + str(int(envelope[field])) + "ULL;")
            for field in ("sender_session_id", "run_id"):
                lines.append("  " + name + "." + field + " = " + _uuid_literal(envelope[field]) + ";")
            if status:
                body = envelope["frame_status"]
                for field in ("frame_id", "frames_dropped_total"):
                    lines.append("  batch.status." + field + " = " + str(int(body[field])) + "ULL;")
                lines.append("  batch.status.camera_ready = " + str(body["camera_ready"]).lower() + ";")
                for person in body["person_ids"]:
                    lines.append("  batch.status.person_ids.push_back(" + str(person) + "U);")
            else:
                body = envelope["skeleton_frame"]
                for field in ("frame_id", "person_id", "processing_complete_us", "processing_clock_id",
                              "image_width", "image_height", "calibration_id"):
                    lines.append("  packet.frame." + field + " = " + str(int(body[field])) + "ULL;")
                capture = body["capture"]
                lines.append("  packet.frame.capture = SourceTime{" + str(int(capture["value_us"])) + "ULL," +
                             str(capture["clock_id"]) + "U,TimeKind::" + time_names[capture["kind"]] + "," +
                             str(capture["uncertainty_us"]) + "U," + str(capture["timing_valid"]).lower() + "};")
                lines.append("  packet.frame.state = TrackingState::" + state_names[body["state"]] + ";")
                for joint in body["joints"]:
                    lines.append("  packet.frame.joints.push_back(Joint2D{" + str(joint["coco_joint_index"]) + "U," +
                                 ",".join(_float_literal(joint[field]) for field in ("x_normalized", "y_normalized", "score")) +
                                 ",TrackingState::" + state_names[joint["state"]] + "});")
                lines.extend(["  batch.people.push_back(packet);", "  }"])
        lines.extend(["  return batch;", "}"])
    lines.append("}  // namespace actual_tracking_fixture")
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def validate_cpp_inputs(results, documentation):
    """Decode real serialized v0.3 messages before projecting the typed C++ API."""
    from google.protobuf import json_format
    schema = documentation / "spec/motion.proto"
    profile = json.loads((documentation / "spec/reference-profile.json").read_text(encoding="utf-8"))
    shared = load_module("motion_tennis_consumer_wire_bounds", documentation / "scripts/contract/wire_bounds.py")
    validated, identities = [], []
    with tempfile.TemporaryDirectory(prefix=".consumer-codec-", dir=ROOT) as temporary:
        run_checked([sys.executable, "-B", "-m", "grpc_tools.protoc", "-I" + str(schema.parent),
                     "--python_out=" + temporary, str(schema)], ROOT)
        module = load_module("motion_tennis_consumer_generated", Path(temporary) / "motion_pb2.py")
        for result in results:
            converted = deepcopy(result)
            converted["envelopes"] = []
            for payload in result["envelopes"]:
                envelope = json_format.ParseDict(payload, module.Envelope(), ignore_unknown_fields=False)
                shared.validate_envelope(envelope, profile, "udp")
                encoded = envelope.SerializeToString(deterministic=True)
                decoded = module.Envelope.FromString(encoded)
                shared.validate_envelope(decoded, profile, "udp")
                converted["envelopes"].append(json_format.MessageToDict(decoded, preserving_proto_field_name=True,
                                                                       always_print_fields_with_no_presence=True))
                identities.append(hashlib.sha256(encoded).hexdigest())
            validated.append(converted)
    return validated, identities


def check_physics(physics_root, documentation):
    manifest, frames, _, emitted = emitted_examples()
    restarted_manifest = deepcopy(manifest)
    restarted_manifest["sender_session_id"] = "33" * 16
    restarted_frame = deepcopy(frames[0])
    restarted_frame["sender_session_id"] = restarted_manifest["sender_session_id"]
    restarted = RecordedPoseAdapter(restarted_manifest)
    require(restarted.offer(restarted_frame, now_us=int(restarted_frame["processing_complete_us"])),
            "New-session source fixture rejected")
    emitted.append(restarted.take(now_us=int(restarted_frame["processing_complete_us"])))
    next_frame = deepcopy(frames[1])
    next_frame["sender_session_id"] = restarted_manifest["sender_session_id"]
    require(restarted.offer(next_frame, now_us=int(next_frame["processing_complete_us"])), "Restart follow-up rejected")
    emitted.append(restarted.take(now_us=int(next_frame["processing_complete_us"])))
    emitted, wire_hashes = validate_cpp_inputs(emitted, documentation)
    with tempfile.TemporaryDirectory(prefix=".consumer-check-", dir=ROOT) as temporary:
        directory = Path(temporary)
        write_cpp_fixtures(directory / "tracking_fixture.hpp", emitted)
        build = directory / "build"
        run_checked(["cmake", "-S", str(ROOT / "tests/compatibility"), "-B", str(build),
                     "-DPHYSICS_ROOT=" + str(physics_root), "-DFIXTURE_DIR=" + str(directory)], ROOT)
        run_checked(["cmake", "--build", str(build), "--config", "Release", "--target", "tracking_consumer_probe"], ROOT)
        choices = [build / "Release/tracking_consumer_probe.exe", build / "tracking_consumer_probe.exe",
                   build / "tracking_consumer_probe"]
        executable = next((path for path in choices if path.is_file()), None)
        require(executable is not None, "C++ compatibility executable missing")
        result = run_checked([str(executable)], ROOT)
        cases = [line[5:] for line in result.stdout.splitlines() if line.startswith("PASS ")]
        require(cases and not any(line.startswith("FAIL ") for line in result.stdout.splitlines()), "C++ consumer cases failed")
        sizes = {line.split()[1]: int(line.split()[2]) for line in result.stdout.splitlines() if line.startswith("RESOURCE ")}
    return {"status": "passed", "consumer": "Actual C++ TrackingPoseBridge and BatchCore",
            "cases": cases, "case_count": len(cases), "actual_source_frames": len(emitted),
            "canonical_wire_sha256": wire_hashes,
            "host_sizeof_bytes": sizes,
            "fixture_map": {"source_anchor_us": 1000000, "pi_anchor_us": 500000,
                            "rate_numerator": 1, "rate_denominator": 1, "uncertainty_us": 500,
                            "measured": False},
            "limits": "Generated fixture preserves decoded source values. Explicit synthetic bindings/map and scripted contact evaluator; no metric geometry, Pi fitting or C wire decoding."}


def source_evidence(physics_root, debug_root, documentation):
    """Pin the tested working files independently from unpublished base commits."""
    roots = {ROOT.name: ROOT, physics_root.name: physics_root, debug_root.name: debug_root, documentation.name: documentation}
    revisions = {}
    for name, path in roots.items():
        revision = run_checked(["git", "rev-parse", "HEAD"], path).stdout.strip()
        dirty = bool(run_checked(["git", "status", "--porcelain=v1"], path).stdout.strip())
        revisions[name] = {"base_revision": revision, "working_tree_changes": dirty}
    paths = []
    for area in ("tracking_adapter", "scripts", "tests"):
        paths.extend(path for path in (ROOT / area).rglob("*") if path.is_file()
                     and "__pycache__" not in path.parts and path.suffix in (".py", ".cpp", ".hpp", ".txt"))
    paths.extend([ROOT / "requirements-codec.txt", ROOT / "examples/recorded-pose-manifest.json",
                  ROOT / "examples/recorded-poses.jsonl", ROOT / "examples/fixture-hashes.json"])
    for area in ("include", "src", "tests"):
        paths.extend(path for path in (physics_root / area).rglob("*") if path.is_file() and path.suffix in (".cpp", ".hpp"))
    paths.extend([physics_root / "CMakeLists.txt", debug_root / "scripts/check_trace.py",
                  debug_root / "scripts/audit_extensions.py", debug_root / "examples/synthetic-trace.jsonl",
                  documentation / "spec/motion.proto", documentation / "spec/reference-profile.json",
                  documentation / "scripts/contract/wire_bounds.py"])
    hashes = {}
    for path in sorted(set(paths)):
        owner = next(root for root in roots.values() if path.is_relative_to(root))
        key = owner.name + "/" + path.relative_to(owner).as_posix()
        hashes[key] = hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    return revisions, hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--physics-root", type=Path, default=ROOT.parent / "motion-tennis-physics-engine")
    parser.add_argument("--debug-root", type=Path, default=ROOT.parent / "debug-units")
    parser.add_argument("--documentation-root", type=Path, default=ROOT.parent / "documentation")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--evidence-date", help="Caller-supplied review date in YYYY-MM-DD form")
    args = parser.parse_args()
    try:
        if args.evidence_date:
            date.fromisoformat(args.evidence_date)
        wire_result = run_checked([sys.executable, "-B", str(ROOT / "scripts/check_shared_contract.py"),
                                   "--documentation-root", str(args.documentation_root)], ROOT)
        wire = json.loads(wire_result.stdout)
        require(wire["status"] == "passed", "Shared wire check is not passing")
        unit_result = run_checked([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests"], ROOT)
        unit_count = re.search(r"Ran (\d+) tests", unit_result.stderr)
        require(unit_count is not None, "Unit-test result has no test count")
        debug = check_debug(args.debug_root.resolve())
        physics = check_physics(args.physics_root.resolve(), args.documentation_root.resolve())
        revisions, hashes = source_evidence(args.physics_root.resolve(), args.debug_root.resolve(), args.documentation_root.resolve())
        report = {"status": "passed_offline_consumer_compatibility", "stage": "S1", "date": args.evidence_date, "wire": wire,
                  "debug": debug, "physics": physics,
                  "python_tests": {"status": "passed", "tests": int(unit_count.group(1)), "exit_code": 0},
                  "environment": {"python": platform.python_version(), "platform": platform.platform(),
                                  "cmake": run_checked(["cmake", "--version"], ROOT).stdout.splitlines()[0]},
                  "source_revisions": revisions, "source_sha256_lf": hashes,
                  "limitations": "Synthetic controller/setup/map fixtures; no live capture, transport, clock fitting, target-device, geometric fusion or stage acceptance."}
        output = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(output, encoding="utf-8", newline="\n")
        print(output, end="")
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        failure = {"status": "failed", "stage": "S1", "date": args.evidence_date, "error": str(error)}
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(failure, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        print(json.dumps(failure))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
