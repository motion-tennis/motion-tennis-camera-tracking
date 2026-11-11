#!/usr/bin/env python3
"""Optionally check S1 adapter output with the shared generated Python codec.

This development check installs nothing and uses no network or device. Exit 2
means the pinned development dependencies are unavailable, never a passed check.
"""

import argparse
from copy import deepcopy
import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tracking_adapter.adapter import (  # noqa: E402
    MAX_WIRE_UINT64,
    PROFILE_SHA256,
    SCHEMA_SHA256,
    RecordedPoseAdapter,
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical_hash(path):
    """Use the accepted LF identity even for a Windows CRLF text checkout."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def dependencies():
    versions, unavailable = {}, []
    for line in (ROOT / "requirements-codec.txt").read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        name, expected = line.split("==")
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            unavailable.append(name + "==" + expected + " is missing")
            continue
        versions[name] = actual
        if actual != expected:
            unavailable.append(name + ": expected " + expected + ", found " + actual)
    return versions, unavailable


def import_path(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "Cannot import " + str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def collect_examples():
    manifest = json.loads((ROOT / "examples/recorded-pose-manifest.json").read_text(encoding="utf-8"))
    adapter = RecordedPoseAdapter(manifest)
    cases = []
    with (ROOT / "examples/recorded-poses.jsonl").open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            frame = json.loads(line)
            now = int(frame["processing_complete_us"])
            require(adapter.offer(frame, now), "Example rejected: " + str(adapter.last_rejection))
            result = adapter.take(now)
            require(result is not None, "Example unexpectedly suppressed")
            cases.append(("example_line_" + str(number), result["envelopes"]))
    require(bool(cases), "No example frames were checked")
    return manifest, cases


def maximum_case(manifest):
    """Exercise accepted adapter maxima and the maximum envelope varint width."""
    manifest = deepcopy(manifest)
    manifest.update(sender_id=(1 << 32) - 1, clock_id=(1 << 32) - 1,
                    calibration_id=(1 << 32) - 1, image_width=16_384, image_height=16_384,
                    sender_session_id="ff" * 16, run_id="fe" * 16)
    capture = MAX_WIRE_UINT64 - 10_000
    frame = {
        "sender_session_id": manifest["sender_session_id"],
        "frame_id": str(MAX_WIRE_UINT64), "calibration_id": manifest["calibration_id"],
        "capture": {"value_us": str(capture), "clock_id": manifest["clock_id"],
                    "kind": "DRIVER_FRAME", "uncertainty_us": 8_000, "timing_valid": True},
        "arrival_us": str(capture + 1_000), "processing_complete_us": str(capture + 2_000),
        "frames_dropped_total": str(MAX_WIRE_UINT64), "camera_ready": True,
        "people": [{"person_id": (1 << 32) - 1 - index, "state": "UNAVAILABLE",
                    "joints": [{"coco_joint_index": joint, "x_normalized": 1.0,
                                "y_normalized": 1.0, "score": 1.0, "state": "UNAVAILABLE"}
                               for joint in range(17)]} for index in range(4)],
    }
    adapter = RecordedPoseAdapter(manifest)
    now = capture + 3_000
    require(adapter.offer(frame, now), "Maximum adapter case rejected: " + str(adapter.last_rejection))
    result = adapter.take(now)
    require(result is not None, "Maximum adapter case was suppressed")
    emitted = result["envelopes"]
    # Reaching the final legal sequence in normal operation is impractical.
    # A separate field-width witness retains distinct increasing identities.
    widths = deepcopy(emitted)
    for index, envelope in enumerate(widths, MAX_WIRE_UINT64 - len(widths) + 1):
        envelope["message_seq"] = str(index)
    return [("maximum_adapter_values", emitted), ("maximum_message_sequence_width", widths)]


def shared_pose_case(module, manifest, parse_dict):
    """Compare with an independent typed reproduction of the shared pose fixture.

    The known-answer body reproduces seventeen_joint_pose in documentation's
    tests/contract/test_generated.py. Envelope send time differs because the
    adapter honestly sends only after processing completion.
    """
    manifest = deepcopy(manifest)
    manifest.update(sender_id=1, sender_session_id=(b"s" * 16).hex(), run_id=(b"r" * 16).hex(),
                    clock_id=1, calibration_id=1, image_width=1920, image_height=1080)
    frame = {
        "sender_session_id": manifest["sender_session_id"], "frame_id": "1", "calibration_id": 1,
        "capture": {"value_us": "1000000", "clock_id": 1, "kind": "DRIVER_FRAME",
                    "uncertainty_us": 0, "timing_valid": True},
        "arrival_us": "1000000", "processing_complete_us": "1001000",
        "frames_dropped_total": "0", "camera_ready": True,
        "people": [{"person_id": 1, "state": "TRACKED",
                    "joints": [{"coco_joint_index": index, "x_normalized": 0.5,
                                "y_normalized": 0.5, "score": 0.9, "state": "TRACKED"}
                               for index in range(17)]}],
    }
    adapter = RecordedPoseAdapter(manifest)
    require(adapter.offer(frame, 1_001_000), "Shared pose input rejected")
    result = adapter.take(1_001_000)
    require(result is not None, "Shared pose output was suppressed")
    actual = parse_dict(result["envelopes"][0], module.Envelope()).skeleton_frame
    expected = module.SkeletonFrame(frame_id=1, person_id=1, processing_complete_us=1_001_000,
                                    processing_clock_id=1, image_width=1920, image_height=1080,
                                    calibration_id=1, state=module.TRACKED)
    expected.capture.CopyFrom(module.SourceTime(value_us=1_000_000, clock_id=1,
                                              kind=module.DRIVER_FRAME, timing_valid=True))
    for index in range(17):
        expected.joints.add(coco_joint_index=index, x_normalized=0.5, y_normalized=0.5,
                            score=0.9, state=module.TRACKED)
    expected_bytes = expected.SerializeToString(deterministic=True)
    require(actual.SerializeToString(deterministic=True) == expected_bytes,
            "Adapter pose differs from the shared seventeen-joint known answer")
    return ("shared_seventeen_joint_pose", result["envelopes"]), hashlib.sha256(expected_bytes).hexdigest()


def check(documentation, versions):
    schema, profile_path = documentation / "spec/motion.proto", documentation / "spec/reference-profile.json"
    require(canonical_hash(schema) == SCHEMA_SHA256, "Shared schema hash differs from the accepted adapter baseline")
    require(canonical_hash(profile_path) == PROFILE_SHA256, "Shared profile hash differs from the accepted adapter baseline")
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    from google.protobuf import json_format

    shared = import_path("motion_tennis_shared_wire_bounds", documentation / "scripts/contract/wire_bounds.py")
    with tempfile.TemporaryDirectory(prefix=".codec-check-", dir=ROOT) as temporary:
        subprocess.run([sys.executable, "-B", "-m", "grpc_tools.protoc", "-I" + str(schema.parent),
                        "--python_out=" + temporary, str(schema)], check=True, capture_output=True, text=True)
        module = import_path("motion_tennis_shared_generated", Path(temporary) / "motion_pb2.py")
        manifest, cases = collect_examples()
        example_frames = len(cases)
        cases.extend(maximum_case(manifest))
        pose_case, known_answer_hash = shared_pose_case(module, manifest, json_format.ParseDict)
        cases.append(pose_case)
        results = []
        cap = profile["limits"]["udp_payload_bytes"]
        for name, envelopes in cases:
            sizes = []
            for payload in envelopes:
                envelope = json_format.ParseDict(payload, module.Envelope(), ignore_unknown_fields=False)
                shared.validate_envelope(envelope, profile, "udp")
                encoded = envelope.SerializeToString(deterministic=True)
                require(envelope.ByteSize() == len(encoded) <= cap, "Encoded envelope exceeds the UDP cap")
                decoded = module.Envelope.FromString(encoded)
                shared.validate_envelope(decoded, profile, "udp")
                require(decoded.SerializeToString(deterministic=True) == encoded,
                        "Generated Python canonical round trip changed the envelope")
                sizes.append({"body": envelope.WhichOneof("body"), "encoded_bytes": len(encoded)})
            results.append({"case": name, "envelopes": sizes})
    return {"status": "passed", "scope": "S1 offline generated Python codec compatibility",
            "schema_sha256": SCHEMA_SHA256, "profile_sha256": PROFILE_SHA256,
            "development_dependencies": versions, "example_frames": example_frames,
            "checked_envelopes": sum(len(case["envelopes"]) for case in results),
            "udp_cap_bytes_including_envelope": cap,
            "largest_encoded_envelope_bytes": max(item["encoded_bytes"] for case in results for item in case["envelopes"]),
            "shared_pose_body_sha256": known_answer_hash, "cases": results,
            "limitations": "Python host codec only; no nanopb C/device interoperability, network, capture or hardware validation."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documentation-root", type=Path, default=ROOT.parent / "documentation")
    arguments = parser.parse_args()
    try:
        versions, unavailable = dependencies()
        if unavailable:
            print(json.dumps({"status": "skipped", "reason": "Pinned development dependencies unavailable",
                              "details": unavailable,
                              "install": "python -m pip install -r requirements-codec.txt"}, indent=2))
            return 2
        result = check(arguments.documentation_root.resolve(), versions)
    except (ValueError, OSError, ImportError, subprocess.CalledProcessError) as error:
        detail = error.stderr if isinstance(error, subprocess.CalledProcessError) else str(error)
        print(json.dumps({"status": "failed", "reason": detail}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
