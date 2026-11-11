"""Bounded producer-side trace-v1 records; no I/O, clock fitting or callbacks."""

from collections import deque
from copy import deepcopy


MAX_TRACE_SEQUENCE = (1 << 64) - 1
DEFAULT_TRACE_LIMITS = {
    "response_deadline_us": "30000",
    "electrical_deadline_us": "40000",
    "transaction_timeout_us": "50000",
}


def run_header(manifest):
    """Describe the declared run; the pinned profile supplies legacy defaults."""
    limits = manifest.get("trace_limits", DEFAULT_TRACE_LIMITS)
    return {
        "record_type": "run", "trace_version": "1", "run_id": manifest["run_id"],
        "synthetic": manifest["synthetic"], **deepcopy(limits),
        "profile_id": manifest["profile_id"], "schema_sha256": manifest["schema_sha256"],
        "profile_sha256": manifest["profile_sha256"],
        "trace_limits_source": "manifest" if "trace_limits" in manifest else "accepted_profile",
        "description": "Offline declared tracking observations; no hardware or Pi-clock validation.",
    }


class TraceBuffer:
    """Keep original sequences, explicit loss and separately untimed metadata.

    The adapter serializes calls under its existing lock. Session registration
    is bounded by the adapter's never-reused 64-session registry. A loss notice
    is produced at the caller's observed boundary, never at a guessed drain
    time. Replacing an undelivered loss notice counts that notice as lost and
    carries its still-unreported delta into its replacement.
    """

    def __init__(self, manifest, stats, capacity=64):
        self.capacity = capacity
        self.events = deque()
        self.untimed = deque()
        self.sessions = {}
        self.headers = {}
        self.stats = stats
        self.register(manifest)

    @staticmethod
    def key(manifest):
        return manifest["run_id"], str(manifest["sender_id"]), manifest["sender_session_id"]

    def check_registration(self, manifest):
        header = run_header(manifest)
        existing = self.headers.get(manifest["run_id"])
        if existing is not None:
            compared = ("synthetic", "profile_id", "schema_sha256", "profile_sha256", *DEFAULT_TRACE_LIMITS)
            if any(header[name] != existing[name] for name in compared):
                raise ValueError("A retained run cannot change its declared profile, synthetic flag or timing limits")

    def register(self, manifest):
        self.check_registration(manifest)
        self.headers.setdefault(manifest["run_id"], run_header(manifest))
        self.sessions[self.key(manifest)] = {
            "manifest": deepcopy(manifest), "next_seq": 0, "next_metadata_seq": 0,
            "pending_loss": 0, "dropped_total": 0, "metadata_total": 0,
            "metadata_dropped": 0, "notice": None, "sequence_exhausted": False,
        }

    @staticmethod
    def identity(manifest):
        return {"run_id": manifest["run_id"], "source_id": str(manifest["sender_id"]),
                "source_session_id": manifest["sender_session_id"], "clock_id": str(manifest["clock_id"])}

    def _untimed(self, manifest, event, details):
        state = self.sessions[self.key(manifest)]
        state["metadata_total"] += 1
        metadata_seq = state["next_metadata_seq"]
        state["next_metadata_seq"] += 1
        if len(self.untimed) == self.capacity:
            old = self.untimed.popleft()
            old_key = old["run_id"], old["source_id"], old["source_session_id"]
            self.sessions[old_key]["metadata_dropped"] += 1
            self.stats["untimed_metadata_dropped"] += 1
        record = {"record_type": "tracking_untimed_metadata", **self.identity(manifest),
                  "metadata_seq": str(metadata_seq), "event": event, "mono_us": None,
                  "reason": "No valid native observation timestamp was supplied for this boundary.",
                  "details": deepcopy(details)}
        self.untimed.append(record)
        return record

    def _allocate(self, manifest, event, now_us, details):
        state = self.sessions[self.key(manifest)]
        if state["next_seq"] > MAX_TRACE_SEQUENCE:
            state["sequence_exhausted"] = True
            state["dropped_total"] += 1
            state["pending_loss"] += 1
            self.stats["diagnostics_dropped"] += 1
            return None
        record = {"record_type": "event", **self.identity(manifest),
                  "event_seq": str(state["next_seq"]), "mono_us": str(now_us),
                  "event": event, "transaction": None, "details": deepcopy(details)}
        state["next_seq"] += 1
        return record

    def _lost(self, record):
        key = record["run_id"], record["source_id"], record["source_session_id"]
        state = self.sessions[key]
        state["dropped_total"] += 1
        state["pending_loss"] += 1
        self.stats["diagnostics_dropped"] += 1
        if record["event"] == "log_drop":
            state["pending_loss"] += int(record["details"]["count"])
            if state["notice"] is record:
                state["notice"] = None

    def _append(self, record):
        if len(self.events) == self.capacity:
            self._lost(self.events.popleft())
        self.events.append(record)

    def _loss_notice(self, manifest, now_us):
        state = self.sessions[self.key(manifest)]
        if not state["pending_loss"]:
            return
        previous = state["notice"]
        if previous is not None:
            for index, record in enumerate(self.events):
                if record is previous:
                    del self.events[index]
                    self._lost(previous)
                    break
        if len(self.events) == self.capacity:
            self._lost(self.events.popleft())
        count = state["pending_loss"]
        notice = self._allocate(manifest, "log_drop", now_us, {
            "count": str(count), "event_boundary": "diagnostic_ring_overflow_observed",
            "capture_uncertainty_us": None,
            "capture_uncertainty_reason": "The caller observation timestamp has no characterized error bound.",
        })
        if notice is not None:
            state["pending_loss"] = 0
            state["notice"] = notice
            self.events.append(notice)

    def record(self, manifest, event, now_us, details):
        if now_us is None:
            return self._untimed(manifest, event, details)
        record = self._allocate(manifest, event, now_us, details)
        if record is None:
            self._untimed(manifest, "trace_sequence_exhausted", {
                "omitted_event": event, "requires_new_source_session": True,
                "observed_us": str(now_us),
            })
            return None
        self._append(record)
        self._loss_notice(manifest, now_us)
        return record

    def drain_events(self):
        records = list(self.events)
        self.events.clear()
        for state in self.sessions.values():
            state["notice"] = None
        return deepcopy(records)

    def export(self):
        events = self.drain_events()
        metadata = list(self.untimed)
        self.untimed.clear()
        bundles = []
        for run_id, header in self.headers.items():
            run_events = [record for record in events if record["run_id"] == run_id]
            run_metadata = [deepcopy(record) for record in metadata if record["run_id"] == run_id]
            states = []
            for key, state in self.sessions.items():
                if key[0] != run_id:
                    continue
                identity = self.identity(state["manifest"])
                states.append({**identity, "diagnostics_dropped_total": str(state["dropped_total"]),
                               "unreported_loss_delta": str(state["pending_loss"]),
                               "untimed_records_total": str(state["metadata_total"]),
                               "untimed_metadata_dropped_total": str(state["metadata_dropped"]),
                               "sequence_exhausted": state["sequence_exhausted"]})
                if state["pending_loss"]:
                    run_metadata.append({"record_type": "tracking_untimed_metadata", **identity,
                                         "event": "unreported_log_loss", "mono_us": None,
                                         "reason": "No further native timestamp for this source was observed.",
                                         "details": {"count": str(state["pending_loss"])}})
                    state["pending_loss"] = 0
            complete = not any(int(state["diagnostics_dropped_total"]) or int(state["untimed_records_total"])
                               or int(state["untimed_metadata_dropped_total"]) or state["sequence_exhausted"]
                               for state in states)
            run_header_value = deepcopy(header)
            run_header_value["tracking_trace"] = {"complete_source_diagnostics": complete, "sources": states}
            bundles.append({"header": run_header_value, "events": run_events, "untimed_metadata": run_metadata})
        return bundles
