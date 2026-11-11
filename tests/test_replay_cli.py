"""Exercise actual file parsing, bounded records and replay exit statuses."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from fixtures import EXAMPLES, make_frame


REPOSITORY = Path(__file__).resolve().parents[1]


class ReplayCliTests(unittest.TestCase):
    def run_cli(self, fixture, *extra):
        return subprocess.run(
            [sys.executable, "-m", "tracking_adapter", str(fixture),
             "--manifest", str(EXAMPLES / "recorded-pose-manifest.json"), *extra],
            cwd=REPOSITORY, capture_output=True, text=True, encoding="utf-8",
            check=False, timeout=10,
        )

    def run_input(self, contents):
        with tempfile.TemporaryDirectory(prefix=".s1-cli-", dir=REPOSITORY) as directory:
            workspace = Path(directory).resolve()
            self.assertTrue(workspace.is_relative_to(REPOSITORY))
            path = workspace / "input.jsonl"
            path.write_bytes(contents)
            return self.run_cli(path)

    def test_replay_reads_all_records_and_emits_a_valid_summary(self):
        result = self.run_cli(EXAMPLES / "recorded-poses.jsonl")
        self.assertEqual(result.returncode, 0, result.stderr)
        records = [json.loads(line) for line in result.stdout.splitlines()]
        frames = [record["result"] for record in records if record["type"] == "frame"]
        self.assertEqual([frame["frame_status"]["frame_id"] for frame in frames], ["1", "2", "4"])
        self.assertEqual([len(frame["observations"]) for frame in frames], [4, 1, 0])
        summary = records[-1]
        self.assertEqual(summary["type"], "summary")
        self.assertIs(summary["valid"], True)
        self.assertEqual(summary["stats"]["accepted"], 3)
        self.assertEqual(summary["stats"]["emitted"], 3)
        self.assertEqual(summary["stats"]["replaced"], 0)

    def test_buffered_replay_reports_whole_frame_replacements(self):
        result = self.run_cli(EXAMPLES / "recorded-poses.jsonl", "--consume-every", "3")
        self.assertEqual(result.returncode, 0, result.stderr)
        records = [json.loads(line) for line in result.stdout.splitlines()]
        frames = [record["result"] for record in records if record["type"] == "frame"]
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0]["frame_status"]["frame_id"], "4")
        self.assertEqual(int(frames[0]["frame_status"]["frames_dropped_total"]), 3)
        self.assertEqual(records[-1]["stats"]["replaced"], 2)
        self.assertIs(records[-1]["valid"], True)

    def test_duplicate_json_keys_and_nonfinite_numbers_are_input_errors(self):
        for raw in (b'{"frame_id":"1","frame_id":"2"}\n', b'{"coordinate":NaN}\n',
                    b'{"coordinate":Infinity}\n'):
            with self.subTest(raw=raw):
                result = self.run_input(raw)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(json.loads(result.stderr)["error"], "invalid_json")
                self.assertFalse(result.stdout)

    def test_oversized_record_is_rejected_before_semantic_processing(self):
        for raw in (b'{"padding":"' + b"x" * 65_536 + b'"}\n', b" " * 65_537 + b"\n"):
            with self.subTest(record_prefix=raw[:20]):
                result = self.run_input(raw)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(json.loads(result.stderr)["error"], "record_too_large")
                self.assertFalse(result.stdout)

    def test_semantic_failure_is_accounted_in_summary_and_returns_one(self):
        invalid = make_frame()
        invalid["people"][1]["person_id"] = invalid["people"][0]["person_id"]
        result = self.run_input((json.dumps(invalid) + "\n").encode("utf-8"))
        self.assertEqual(result.returncode, 1, result.stderr)
        records = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(records), 1)
        summary = records[0]
        self.assertEqual(summary["type"], "summary")
        self.assertIs(summary["valid"], False)
        self.assertEqual(summary["stats"]["received"], 1)
        self.assertEqual(summary["stats"]["rejected"], 1)
        self.assertEqual(summary["stats"]["emitted"], 0)
        self.assertTrue(any(record["details"].get("code") == "duplicate_person" for record in summary["diagnostics"]))

    def test_empty_or_blank_only_run_is_not_successful_evidence(self):
        for raw in (b"", b"\n  \n\t\n"):
            with self.subTest(raw=raw):
                result = self.run_input(raw)
                self.assertEqual(result.returncode, 1, result.stderr)
                summary = json.loads(result.stdout)
                self.assertIs(summary["valid"], False)
                self.assertEqual(summary["stats"]["received"], 0)
                self.assertEqual(summary["stats"]["emitted"], 0)


if __name__ == "__main__":
    unittest.main()
