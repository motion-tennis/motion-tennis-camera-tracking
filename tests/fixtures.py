"""Stable synthetic inputs; these are not camera or hardware observations."""

import copy
import json
from pathlib import Path


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
MAX_WIRE_UINT64 = (1 << 56) - 1


def load_manifest():
    return json.loads((EXAMPLES / "recorded-pose-manifest.json").read_text(encoding="utf-8"))


def load_frames():
    return [json.loads(line) for line in
            (EXAMPLES / "recorded-poses.jsonl").read_text(encoding="utf-8").splitlines()]


def make_frame(frame_id=1, capture_us=1_000_000, dropped=0):
    result = copy.deepcopy(load_frames()[0])
    result["frame_id"] = str(frame_id)
    result["capture"]["value_us"] = str(capture_us)
    result["arrival_us"] = str(capture_us + 2_000)
    result["processing_complete_us"] = str(capture_us + 5_000)
    result["frames_dropped_total"] = str(dropped)
    return result
