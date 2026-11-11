"""Replay bounded normalized JSONL records, with explicit synthetic provenance."""

import argparse
import json
from pathlib import Path
import sys

from .adapter import MAX_RECORD_BYTES, RecordedPoseAdapter, ValidationError, _counter


def _object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValidationError("invalid_json", "Duplicate JSON object key")
        result[name] = value
    return result


def _constant(value):
    raise ValidationError("invalid_json", "Non-finite JSON number")


def read_json(raw):
    if len(raw) > MAX_RECORD_BYTES:
        raise ValidationError("record_too_large", "Offline record exceeds 65536 bytes")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_object, parse_constant=_constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        if isinstance(error, ValidationError):
            raise
        raise ValidationError("invalid_json", "Record must be bounded UTF-8 JSON") from error


def read_manifest(path):
    with Path(path).open("rb") as stream:
        return read_json(stream.read(MAX_RECORD_BYTES + 1))


def read_frames(path):
    """Read at most one capped line, never the complete replay, into memory."""
    with Path(path).open("rb") as stream:
        line_number = 0
        while True:
            raw = stream.readline(MAX_RECORD_BYTES + 1)
            if not raw:
                break
            line_number += 1
            if not raw.strip():
                if len(raw) > MAX_RECORD_BYTES:
                    raise ValidationError("record_too_large", "Offline record exceeds 65536 bytes")
                continue
            try:
                yield read_json(raw)
            except ValidationError as error:
                raise ValidationError(error.code, "Line " + str(line_number) + ": " + str(error)) from error


def _emit(value):
    print(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False))


def main(argv=None):
    parser = argparse.ArgumentParser(description="S1 recorded-pose replay; no camera, inference or network access.")
    parser.add_argument("fixture", help="Normalized frame JSONL input")
    parser.add_argument("--manifest", required=True, help="Pinned offline session manifest")
    parser.add_argument("--consume-every", type=int, default=1,
                        help="Consume after this many input records (1..1024); larger values exercise replacement")
    args = parser.parse_args(argv)
    if not 1 <= args.consume_every <= 1024:
        parser.error("--consume-every must be between 1 and 1024")
    try:
        adapter = RecordedPoseAdapter(read_manifest(args.manifest))
        now_us, received = 0, 0
        for frame in read_frames(args.fixture):
            received += 1
            try:
                observed = _counter(frame.get("processing_complete_us"), "processing_complete_us") if type(frame) is dict else now_us
            except ValidationError:
                observed = now_us
            now_us = max(now_us, observed)
            adapter.offer(frame, now_us=now_us)
            if received % args.consume_every == 0:
                result = adapter.take(now_us=now_us)
                if result is not None:
                    _emit({"type": "frame", "result": result})
        result = adapter.take(now_us=now_us)
        if result is not None:
            _emit({"type": "frame", "result": result})
        stats = adapter.stats
        valid = bool(received) and not (stats["rejected"] or stats["expired"] or stats["suppressed"])
        _emit({"type": "summary", "valid": valid, "stats": stats, "diagnostics": adapter.drain_diagnostics(),
               "limits": "Offline declared input only; no sensor, inference, Pi mapping, transport or hardware validation."})
        return 0 if valid else 1
    except (ValidationError, OSError) as error:
        print(json.dumps({"error": getattr(error, "code", "input_error"), "message": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
