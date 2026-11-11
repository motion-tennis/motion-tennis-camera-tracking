# S1 physics and debug consumer handoff

[Repository home](../README.md) · [Initial adapter](s1-recorded-pose-adapter.md) · [Shared handoff](https://github.com/motion-tennis/documentation/blob/main/docs/s1-tracking-consumer-compatibility.md)

## Task and source boundary

On 2026-11-11, the project user requested the physics input bridge, tracking trace-v1 exporter, validation-gap fixes and compatibility tests for rejection, restarts and lost records. This is a bounded S1 interface task, with no later-stage exception, prepared on `task/s1-tracking-consumer-compatibility` in tracking, physics and documentation. Bases are tracking `0509fbd8cc15dd7b5a1a640814b66e890aef1ca3`, physics `51f153593d83bf4872302f7ab286ce458389cd5f`, debug `84c3c2a0289011764980de44575bdb14c7d83376` and documentation `683cd45352e38ac66738fdee3bd5dba1614a9ab0`. The user subsequently authorized committing, merging and pushing all three changed repositories to remote `main`; containing commits and remote refs establish publication separately from the dated validation snapshot.

The accepted v0.3 schema/profile bytes are unchanged. Existing generated-codec pins still apply. The latest [consumer evidence](../evidence/s1-consumer-compatibility-results.json) records baseline revisions, exact tested working-source hashes, environment, canonical wire hashes and actual results. The earlier [47-test report](../evidence/s1-recorded-pose-results.json) remains a historical snapshot of the initial adapter; changed source files have their current hashes in the new report.

The compatible physics implementation is commit `d6d71436f30a1effd1572b85daaf560ebaf40ba1`; its [pinned handoff](https://github.com/motion-tennis/motion-tennis-physics-engine/blob/d6d71436f30a1effd1572b85daaf560ebaf40ba1/docs/s1-tracking-consumer.md) records the consumer API and validation limits. Base revisions and dirty-tree flags in the saved report describe the source state at validation time; they are not current publication-status assertions.

## Trace-v1 producer

`RecordedPoseAdapter` creates trace-v1 records at the supplied native observation boundary, before buffering them. `drain_diagnostics()` returns timed trace events. `export_trace()` drains run-grouped bundles containing `header`, `events` and separately `untimed_metadata`. Each event has its own run/source/session/clock identity, original `event_seq`, decimal `mono_us`, `transaction: null` and `details`.

Numeric IDs normalize to decimal strings; UUIDs normalize losslessly to lowercase hexadecimal strings. Capture, arrival, completion and emission times remain separate. Emitted-frame details contain the exact observations, common frame status and envelope message sequences. The capture uncertainty remains attached to capture. Unknown event-boundary uncertainty is explicit rather than borrowing the camera's uncertainty.

Timed records and untimed metadata each have capacity 64, with at most 64 producer sessions. Sequence allocation precedes ring insertion. Overflow emits truthful `log_drop` deltas at an observed native boundary and preserves original sequence gaps. Loss of an older undelivered loss notice carries its unreported count forward. If an old source has no further clock boundary, unresolved loss remains untimed metadata and in the header. `header.tracking_trace.complete_source_diagnostics` is false for loss, untimed records or sequence exhaustion. A reader must retain this flag even when a generic auditor accepts the remaining event shapes.

`start_session(manifest, now_us=None, previous_session_now_us=None)` takes separate optional new- and old-session boundaries. Equal numeric clock IDs do not imply continuity. An omitted boundary remains untimed metadata; no zero/last-known timestamp is invented. Retired sessions cannot be reused, pending old frames are flushed explicitly and each record retains its original run identity. Repeated exports are chunks: retain one run header and original sequences when joining same-run chunks, rather than concatenating headers as events.

```sh
python -B -m tracking_adapter examples/recorded-poses.jsonl --manifest examples/recorded-pose-manifest.json --format trace-v1
```

This emits a header and timed records on stdout; summary/status goes to stderr. Untimed metadata is retained in the header. The default `observations` format remains available. Observation processing continues independently of diagnostic overflow, which remains an explicit observation-evidence failure. No observer callback, socket or file writer runs inside the adapter lock.

A tracking-only trace has no controller transactions. The existing measurement auditor correctly rejects it as insufficient measurement evidence. Consumer-positive fixtures add the existing **explicitly synthetic** debug controller records; those records are never generated or claimed by the tracker. The debug auditor checks trace integrity; the compatibility harness separately compares observation values, IDs, boundaries and loss counts.

## Typed physics bridge

The physics repository implements `TrackingPoseBridge : PoseSource` in `include/motion_tennis/physics/tracking_pose_bridge.hpp`. It accepts one atomic `TrackingFrameBatch`: decoded v0.3 envelope metadata, all declared per-person skeleton packets and their common frame status. This is a bounded typed handoff after decoding; UDP assembly and a C wire decoder remain separate work.

The caller supplies explicit confirmed player/person/session/calibration bindings, an explicit quality policy and immutable Pi-owned clock evidence. The bridge retains all seventeen image-space joints, raw source time, source/run/session/clock identity, reference epoch, map identity/version and conservative mapped uncertainty. Anchored integer/rational conversion avoids precision loss near the uint56 limit. The synthetic check policy uses a 0.5 joint-score threshold; it is not a measured model threshold.

The bridge and batch core reject missing/expired/uncertain maps, incompatible source/reference sessions and calibrations, unavailable required joints, stale poses, future completion/send boundaries, duplicate/reordered frames, contradictory or incomplete membership and loss-counter regression. Conservative age includes capture/map bounds; map use follows acceptance and its full validity interval. A healthy zero-person frame, unavailable camera or restart invalidates unsupported cached poses. New sessions require explicit reinstallation of bindings/maps. The core rechecks current eligibility and its retained immutable observation after state waiting and before commit.

No normalized joint becomes metric 3D and no real pose/contact/fusion model is added. Existing scripted contact/state doubles remain explicitly synthetic. Physical camera/Kinect capture, Pi clock fitting, model-confidence calibration, real networking and target-device measurements remain future tasks.

## Reproduce compatibility checks

The ordinary suite needs Python 3.10+ and the standard library:

```sh
python -B -m unittest discover -s tests -v
```

For generated-codec and compiled consumer checks, use the pinned optional development environment from the initial handoff and an installed CMake/C++20 toolchain. Adjacent physics, debug and documentation checkouts are required:

```powershell
.\.venv-codec\Scripts\python.exe -B scripts/check_consumer_compatibility.py --evidence-date 2026-11-11 --report evidence/s1-consumer-compatibility-results.json
```

The checker also accepts `--physics-root`, `--debug-root` and `--documentation-root`. It checks shared codec compatibility, serializes and decodes actual adapter messages, projects those decoded values into the real typed C++ API and compiles a focused driver against the actual physics core. Temporary generated/build files remain under the checkout and are removed afterward. A failed run overwrites the requested report with failure rather than retaining stale passing evidence.

Host validation on Windows/Python 3.14.3 passed 64 Python tests, 20 shared-codec envelopes, 17 actual C++ consumer scenarios and seven debug handoff scenarios. Five source frames supplied fifteen canonical wire envelopes, including a new tracker session. The loss fixture's 100 rejected offers produced 72 lost records including overwritten loss notices; source gaps and explicit loss counts both remained 72, and the auditor correctly marked the damaged run invalid.

The compiled fixture uses explicit person/session bindings and a **synthetic**, unmeasured map: source anchor 1000000 microseconds to Pi anchor 500000, rational rate 1/1, map bound 500 microseconds. Host `sizeof` values were 18144 bytes for the bridge, 704 for one retained pose and 68968 for the batch core; fixed-capacity state does not establish target ABI, device memory headroom or execution time. Physics-focused unit/CTest results are recorded in the physics handoff.

The shared S1 gate stays active/incomplete. These results establish the exercised offline producer/consumer boundary and rejection behavior; they do not establish live transport, measured camera/clock accuracy, complete geometry/rules, owner adoption or stage acceptance.
