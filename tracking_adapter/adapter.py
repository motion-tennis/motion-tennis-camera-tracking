"""Validate isolated observations against the accepted v0.3 tracking boundary.

All freshness comparisons use the fixture's one declared native host clock.
This module neither estimates Pi maps nor assigns controllers to people.
"""

import base64
from collections import deque
from copy import deepcopy
import math
import re
from threading import Lock


PROFILE_ID = "webcam-pi3-doubles-v3"
SCHEMA_SHA256 = "b6728e240316e957f5c5addb973f12f9a57fffbcdacc4331f3db5e06895f360b"
PROFILE_SHA256 = "a3533462fdebfd4c7c2f87eaa3bd579d3056170e3dcfc6a6c68ed34474c1d969"
MAX_WIRE_UINT64 = (1 << 56) - 1
MAX_POSE_AGE_US = 80_000
MAX_CAPTURE_UNCERTAINTY_US = 8_000
MAX_RECORD_BYTES = 65_536
DIAGNOSTIC_CAPACITY = 64
SESSION_HISTORY_CAPACITY = 64
STATES = {"TRACKED", "INFERRED", "UNAVAILABLE"}
CAPTURE_KINDS = {"SENSOR_CAPTURE", "DRIVER_FRAME"}


class ValidationError(ValueError):
    """A bounded validation failure with a stable machine-readable category."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _require(condition, code, message):
    if not condition:
        raise ValidationError(code, message)


def _fields(value, required, label):
    _require(type(value) is dict, "invalid_structure", label + " must be an object")
    _require(len(value) == len(required) and set(value) == set(required),
             "invalid_structure", label + " fields differ from the offline format")


def _integer(value, name, maximum=(1 << 32) - 1, minimum=0):
    _require(type(value) is int and minimum <= value <= maximum,
             "invalid_identity", name + " is outside its integer range")
    return value


def _counter(value, name, minimum=0):
    _require(type(value) is str and re.fullmatch(r"0|[1-9][0-9]{0,16}", value) is not None,
             "invalid_counter", name + " must be a canonical decimal string")
    number = int(value)
    _require(minimum <= number <= MAX_WIRE_UINT64, "invalid_counter", name + " exceeds the wire range")
    return number


def _uuid(value, name):
    _require(type(value) is str and re.fullmatch(r"[0-9a-f]{32}", value) is not None
             and value != "0" * 32, "invalid_identity", name + " must be a nonzero 16-byte lowercase hex identity")
    return value


def _label(value, name):
    _require(type(value) is str and 0 < len(value) <= 128,
             "invalid_identity", name + " must contain 1 through 128 characters")
    try:
        length = len(value.encode("utf-8"))
    except UnicodeError as error:
        raise ValidationError("invalid_identity", name + " must be valid UTF-8") from error
    _require(0 < length <= 128, "invalid_identity", name + " must contain 1 through 128 UTF-8 bytes")


def validate_manifest(manifest):
    """Return an isolated, validated copy of the offline session declaration."""
    _fields(manifest, ("format", "synthetic", "profile_id", "schema_sha256", "profile_sha256",
                       "sender_id", "sender_session_id", "run_id", "clock_id", "calibration_id",
                       "image_width", "image_height", "coordinate_space", "preprocessing_id", "model_id"),
            "manifest")
    _require(manifest["format"] == "motion-tennis-tracking-fixture-v1", "unsupported_format", "Unsupported fixture format")
    _require(type(manifest["synthetic"]) is bool, "invalid_structure", "synthetic must be an explicit Boolean")
    _require((manifest["profile_id"], manifest["schema_sha256"], manifest["profile_sha256"])
             == (PROFILE_ID, SCHEMA_SHA256, PROFILE_SHA256), "contract_mismatch", "Fixture does not pin the accepted contract")
    _uuid(manifest["sender_session_id"], "sender_session_id")
    _uuid(manifest["run_id"], "run_id")
    for name in ("sender_id", "clock_id", "calibration_id"):
        _integer(manifest[name], name, minimum=1)
    for name in ("image_width", "image_height"):
        _integer(manifest[name], name, maximum=16_384, minimum=1)
    _require(manifest["coordinate_space"] == "rectified_normalized_coco17", "invalid_coordinates",
             "Coordinates must already refer to the original rectified image")
    for name in ("preprocessing_id", "model_id"):
        _label(manifest[name], name)
    return deepcopy(manifest)


def _now(value):
    return _integer(value, "now_us", maximum=MAX_WIRE_UINT64)


def _capture(value, manifest):
    _fields(value, ("value_us", "clock_id", "kind", "uncertainty_us", "timing_valid"), "capture")
    _counter(value["value_us"], "capture.value_us")
    _require(value["timing_valid"] is True and type(value["kind"]) is str
             and len(value["kind"]) <= 14 and value["kind"] in CAPTURE_KINDS,
             "unknown_timing", "Capture timing needs an explicit supported boundary")
    _integer(value["clock_id"], "capture.clock_id", minimum=1)
    _require(value["clock_id"] == manifest["clock_id"], "clock_mismatch",
             "Cross-clock age cannot be established by this isolated adapter")
    _integer(value["uncertainty_us"], "capture.uncertainty_us")
    _require(value["uncertainty_us"] <= MAX_CAPTURE_UNCERTAINTY_US, "uncertain_capture",
             "Capture uncertainty exceeds the reference gate")
    return deepcopy(value)


def _joint(value):
    _fields(value, ("coco_joint_index", "x_normalized", "y_normalized", "score", "state"), "joint")
    _integer(value["coco_joint_index"], "coco_joint_index", maximum=16)
    _require(type(value["state"]) is str and len(value["state"]) <= 11 and value["state"] in STATES,
             "invalid_quality", "Joint tracking state is not explicit")
    for name in ("x_normalized", "y_normalized", "score"):
        number = value[name]
        code = "invalid_quality" if name == "score" else "invalid_coordinate"
        _require(type(number) in (int, float) and 0 <= number <= 1 and math.isfinite(number),
                 code, name + " must be finite and normalized")
    return deepcopy(value)


def _frame(value, manifest, now_us):
    _fields(value, ("sender_session_id", "frame_id", "calibration_id", "capture", "arrival_us",
                    "processing_complete_us", "frames_dropped_total", "camera_ready", "people"), "frame")
    _require(value["sender_session_id"] == manifest["sender_session_id"], "session_mismatch", "Frame belongs to another tracking session")
    _counter(value["frame_id"], "frame_id", minimum=1)
    _integer(value["calibration_id"], "calibration_id", minimum=1)
    _require(value["calibration_id"] == manifest["calibration_id"], "calibration_mismatch", "Frame calibration differs from its session")
    capture = _capture(value["capture"], manifest)
    arrival = _counter(value["arrival_us"], "arrival_us")
    complete = _counter(value["processing_complete_us"], "processing_complete_us")
    _counter(value["frames_dropped_total"], "frames_dropped_total")
    _require(int(capture["value_us"]) <= arrival <= complete <= now_us,
             "invalid_time_order", "Capture, arrival, completion and observation time must be ordered in one clock")
    _fresh(capture, now_us)
    _require(type(value["camera_ready"]) is bool, "invalid_structure", "camera_ready must be Boolean")
    _require(type(value["people"]) is list and len(value["people"]) <= 4,
             "invalid_people", "An offline frame contains at most four people")
    _require(value["camera_ready"] or not value["people"], "invalid_people", "An unavailable camera cannot claim current people")
    people, identities = [], set()
    for person in value["people"]:
        _fields(person, ("person_id", "state", "joints"), "person")
        person_id = _integer(person["person_id"], "person_id", minimum=1)
        _require(person_id not in identities, "duplicate_person", "Person identity occurs twice in one frame")
        identities.add(person_id)
        _require(type(person["state"]) is str and len(person["state"]) <= 11 and person["state"] in STATES,
                 "invalid_quality", "Person tracking state is not explicit")
        _require(type(person["joints"]) is list and len(person["joints"]) == 17,
                 "invalid_joints", "Every pose must declare all seventeen joints, including unavailable joints")
        joints = [_joint(item) for item in person["joints"]]
        _require(sorted(item["coco_joint_index"] for item in joints) == list(range(17)),
                 "invalid_joints", "COCO joint identities must be distinct and complete")
        joints.sort(key=lambda item: item["coco_joint_index"])
        people.append({"person_id": person_id, "state": person["state"], "joints": joints})
    people.sort(key=lambda item: item["person_id"])
    result = deepcopy(value)
    result.update(capture=capture, people=people)
    return result


def _fresh(capture, now_us):
    age_upper = now_us - int(capture["value_us"]) + capture["uncertainty_us"]
    _require(0 <= now_us - int(capture["value_us"]) and age_upper <= MAX_POSE_AGE_US,
             "stale_capture", "Capture age including uncertainty exceeds the reference gate")


class RecordedPoseAdapter:
    """One waiting whole frame and a bounded, independent diagnostic ring.

    The caller supplies times in the manifest's native clock. Returned data and
    accepted input are copied so caller mutation cannot alter pending evidence.
    """

    def __init__(self, manifest):
        self._manifest = validate_manifest(manifest)
        self._lock = Lock()
        self._pending = None
        self._last_frame_id = 0
        self._last_capture_us = None
        self._last_source_drop = 0
        self._sequence = 0
        self._session_drops = 0
        self._last_now_us = None
        self._seen_sessions = {self._manifest["sender_session_id"]}
        self._last_rejection = None
        self._diagnostics = deque()
        self._stats = dict.fromkeys(("received", "accepted", "rejected", "replaced", "emitted", "expired", "suppressed",
                                    "session_flushes", "session_restarts", "frame_sequence_gaps",
                                    "source_frames_dropped_total", "diagnostics_dropped"), 0)

    @property
    def stats(self):
        with self._lock:
            return dict(self._stats)

    @property
    def last_rejection(self):
        with self._lock:
            return deepcopy(self._last_rejection)

    def _diagnostic(self, event, now_us=None, frame=None, code=None):
        if len(self._diagnostics) == DIAGNOSTIC_CAPACITY:
            self._diagnostics.popleft()
            self._stats["diagnostics_dropped"] += 1
        record = {"event": event, "sender_id": self._manifest["sender_id"],
                  "sender_session_id": self._manifest["sender_session_id"],
                  "clock_id": self._manifest["clock_id"], "time_us": None if now_us is None else str(now_us)}
        if frame is not None:
            record.update(frame_id=frame["frame_id"], capture=deepcopy(frame["capture"]),
                          arrival_us=frame["arrival_us"], processing_complete_us=frame["processing_complete_us"])
        if code:
            record["code"] = code
        self._diagnostics.append(record)

    def _reject(self, error, now_us=None, raw_frame=None):
        self._stats["rejected"] += 1
        self._last_rejection = {"code": error.code, "message": str(error)}
        self._diagnostic("frame_rejected", now_us, code=error.code)
        record = self._diagnostics[-1]
        if type(raw_frame) is dict:
            for name in ("frame_id", "arrival_us", "processing_complete_us"):
                try:
                    _counter(raw_frame.get(name), name)
                except ValidationError:
                    continue
                record[name] = raw_frame[name]
            session = raw_frame.get("sender_session_id")
            if type(session) is str and re.fullmatch(r"[0-9a-f]{32}", session):
                record["input_sender_session_id"] = session

    def _observe_now(self, now_us):
        now_us = _now(now_us)
        _require(self._last_now_us is None or now_us >= self._last_now_us,
                 "clock_regression", "Observation time moved backwards within the native clock session")
        self._last_now_us = now_us
        return now_us

    def offer(self, raw_frame, now_us):
        """Validate a frame; invalid input never displaces a valid waiting frame."""
        with self._lock:
            self._stats["received"] += 1
            observed = None
            try:
                now_us = self._observe_now(now_us)
                observed = now_us
                frame = _frame(raw_frame, self._manifest, now_us)
                frame_id, captured = int(frame["frame_id"]), int(frame["capture"]["value_us"])
                source_drop = int(frame["frames_dropped_total"])
                _require(frame_id > self._last_frame_id, "frame_order", "Frame identity must advance within a session")
                _require(self._last_capture_us is None or captured >= self._last_capture_us,
                         "capture_order", "Capture time moved backwards within a session")
                _require(source_drop >= self._last_source_drop, "source_counter_regression", "Source loss counter moved backwards")
            except ValidationError as error:
                self._reject(error, observed, raw_frame)
                return False
            if self._last_frame_id:
                self._stats["frame_sequence_gaps"] += frame_id - self._last_frame_id - 1
            self._stats["source_frames_dropped_total"] += source_drop - self._last_source_drop
            self._last_frame_id, self._last_capture_us, self._last_source_drop = frame_id, captured, source_drop
            if self._pending is not None:
                self._stats["replaced"] += 1
                self._session_drops += 1
                self._diagnostic("frame_replaced", now_us, self._pending)
            self._pending = frame
            self._stats["accepted"] += 1
            self._last_rejection = None
            self._diagnostic("frame_accepted", now_us, frame)
            return True

    def take(self, now_us):
        """Recheck freshness after waiting and emit typed v0.3 JSON observations."""
        with self._lock:
            now_us = self._observe_now(now_us)
            if self._pending is None:
                return None
            frame = self._pending
            _require(now_us >= int(frame["processing_complete_us"]), "invalid_time_order", "Output time precedes completion")
            try:
                _fresh(frame["capture"], now_us)
                _require(self._sequence + len(frame["people"]) + 1 <= MAX_WIRE_UINT64,
                         "counter_exhausted", "Start a new tracking session before message sequence exhaustion")
                drops = int(frame["frames_dropped_total"]) + self._session_drops
                _require(drops <= MAX_WIRE_UINT64, "counter_exhausted", "Start a new tracking session before loss counter exhaustion")
            except ValidationError as error:
                self._pending = None
                self._stats["expired" if error.code == "stale_capture" else "suppressed"] += 1
                self._session_drops += 1
                self._last_rejection = {"code": error.code, "message": str(error)}
                self._diagnostic("frame_suppressed", now_us, frame, error.code)
                return None
            self._pending = None
            observations = []
            for person in frame["people"]:
                observations.append({"frame_id": frame["frame_id"], "person_id": person["person_id"],
                                     "capture": deepcopy(frame["capture"]),
                                     "processing_complete_us": frame["processing_complete_us"],
                                     "processing_clock_id": self._manifest["clock_id"],
                                     "image_width": self._manifest["image_width"], "image_height": self._manifest["image_height"],
                                     "calibration_id": frame["calibration_id"], "state": person["state"],
                                     "joints": deepcopy(person["joints"])})
            status = {"frame_id": frame["frame_id"], "person_ids": [item["person_id"] for item in observations],
                      "frames_dropped_total": str(drops), "camera_ready": frame["camera_ready"]}
            envelopes = [self._envelope("skeleton_frame", body, now_us) for body in observations]
            envelopes.append(self._envelope("frame_status", status, now_us))
            self._stats["emitted"] += 1
            self._diagnostic("frame_emitted", now_us, frame)
            provenance = {name: self._manifest[name] for name in ("synthetic", "profile_id", "schema_sha256", "profile_sha256",
                          "sender_id", "sender_session_id", "run_id", "clock_id", "coordinate_space", "preprocessing_id", "model_id")}
            provenance.update(frame_id=frame["frame_id"], capture=deepcopy(frame["capture"]),
                              arrival_us=frame["arrival_us"], processing_complete_us=frame["processing_complete_us"],
                              emitted_us=str(now_us), source_frames_dropped_total=frame["frames_dropped_total"])
            return {"observations": observations, "frame_status": status, "envelopes": envelopes,
                    "provenance": provenance, "stats": dict(self._stats)}

    def _envelope(self, body, payload, now_us):
        self._sequence += 1
        return {"major": 0, "minor": 3, "sender_id": self._manifest["sender_id"],
                "sender_session_id": base64.b64encode(bytes.fromhex(self._manifest["sender_session_id"])).decode("ascii"),
                "run_id": base64.b64encode(bytes.fromhex(self._manifest["run_id"])).decode("ascii"),
                "message_seq": str(self._sequence), "sent_time_us": str(now_us),
                "clock_id": self._manifest["clock_id"], body: deepcopy(payload)}

    def drain_diagnostics(self):
        with self._lock:
            records = list(self._diagnostics)
            self._diagnostics.clear()
            return records

    def start_session(self, manifest):
        """Explicitly invalidate waiting observations before accepting new identities."""
        manifest = validate_manifest(manifest)
        with self._lock:
            _require(manifest["sender_session_id"] not in self._seen_sessions,
                     "session_reuse", "A restart must not reuse any session already seen by this adapter")
            _require(len(self._seen_sessions) < SESSION_HISTORY_CAPACITY, "session_limit",
                     "Create a new adapter/run after the bounded session history is full")
            if self._pending is not None:
                self._stats["session_flushes"] += 1
                self._diagnostic("session_frame_flushed", frame=self._pending)
            self._manifest = manifest
            self._seen_sessions.add(manifest["sender_session_id"])
            self._pending = None
            self._last_frame_id = 0
            self._last_capture_us = None
            self._last_source_drop = 0
            self._sequence = 0
            self._session_drops = 0
            self._last_now_us = None
            self._last_rejection = None
            self._stats["session_restarts"] += 1
            self._diagnostic("session_started")
