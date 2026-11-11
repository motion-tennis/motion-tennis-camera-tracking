# S1 recorded-pose adapter and handoff

[Repository home](../README.md) · [S1 acceptance](s0-contract-review.md#first-bounded-s1-task) · [Central status](https://github.com/motion-tennis/documentation/blob/main/docs/project-status.md)

The initial adapter and 47-test evidence below are retained as the original slice record. The subsequent [consumer compatibility handoff](s1-consumer-compatibility.md) adds a trace-v1 exporter, physics input bridge and current 64-test/consumer evidence. Its source hashes supersede the initial snapshot for the changed files.

## Task brief

- Task/contributor: implement the first bounded tracking S1 slice; Codex, authorized by the project user on 2026-11-11.
- Branch: `task/s1-recorded-pose-adapter`, based on freshly fetched tracking `a7ae1bd53ad9b3396c997a13c8b84cdbda10309d`; shared documentation/status baseline `e541fd2c6a089a1fea90cc412cc2dae3d90255f5`.
- Stage: S1 isolated component slices, active/incomplete; no later-stage exception or shared acceptance.
- Scope: Python input validation, one-slot handoff, bounded local diagnostics, file replay, synthetic fixtures, tests and source-backed documentation. Work was prepared on dedicated task branches.
- Publication authorization: on 2026-11-11, the project user explicitly authorized committing this slice and pushing both tracking and documentation to remote `main`. The containing commits and remote refs identify delivery; validation alone does not establish publication.
- Contract: accepted `motion.v03` / `0.3-proposed` / `webcam-pi3-doubles-v3`. Schema SHA-256 `b6728e240316e957f5c5addb973f12f9a57fffbcdacc4331f3db5e06895f360b`; profile SHA-256 `a3533462fdebfd4c7c2f87eaa3bd579d3056170e3dcfc6a6c68ed34474c1d969`, over canonical LF bytes.
- Deferred: camera acquisition, inference, temporal person association, Pi clock fitting, live exports/networking, Kinect capture and true-3D protocol changes.

## Run and input format

Python 3.10+ and the standard library are sufficient:

```sh
python -B -m unittest discover -s tests -v
python -B -m tracking_adapter examples/recorded-poses.jsonl --manifest examples/recorded-pose-manifest.json
python -B -m tracking_adapter examples/recorded-poses.jsonl --manifest examples/recorded-pose-manifest.json --consume-every 2
```

The separate JSON manifest pins the format, contract hashes, `synthetic` declaration, sender/run/session, native host clock, calibration, image dimensions, preprocessing and model identity. UUIDs in the input are nonzero 32-character lowercase hexadecimal values. The output envelopes use standard Protobuf-JSON base64 for byte identities; 64-bit fields remain decimal strings. `synthetic: false` preserves a caller's recorded-input declaration; it does not certify sensor provenance.

Each JSONL record is one whole frame: session/frame/calibration IDs; `capture` SourceTime; separate `arrival_us` and `processing_complete_us`; source `frames_dropped_total`; explicit `camera_ready`; and zero through four `people`. Each person supplies a positive session-scoped ID, state and seventeen distinct COCO joints. The examples pin the complete field spelling and fixture hashes in [fixture-hashes.json](../examples/fixture-hashes.json).

Coordinates are already normalized to the original rectified image: top-left origin, +x right, +y down. This adapter performs no undistortion, letterbox inversion, metric-depth conversion or joint estimation. It sorts complete joint indices and person IDs for deterministic output, preserving all supplied values. Missing joints, null/invalid coordinates and invalid confidence are rejected; nothing is clipped or fabricated. `UNAVAILABLE` retains explicit state and supplied finite coordinates, which consumers must not interpret as usable observations. `(0, 0)` remains a valid measured coordinate when its state says so.

The manifest's calibration ID is a fixture identity, not a measured camera calibration. An incompatible per-frame revision is rejected. Actual `K_rect`, source transform and camera calibration need producer/consumer agreement and device evidence before live use.

## Time, sessions and failure accounting

The fixture declares one native host clock for capture, arrival, completion and caller observation time. `capture.clock_id` must match it. Only `SENSOR_CAPTURE` and `DRIVER_FRAME` boundaries are accepted. Presentation/IRQ/unknown timing is rejected; a future camera presentation timestamp needs its own characterized conversion. Arrival never replaces capture time.

`RecordedPoseAdapter.offer(frame, now_us)` enforces ordered capture/arrival/completion/observation boundaries, nondecreasing native observation time, declared capture uncertainty at most 8000 microseconds, and conservative `now - capture + uncertainty <= 80000` microseconds. `take(now_us)` checks age again after waiting. These are accepted reference gates applied to declared fixture data, not measured camera accuracy. No cross-clock subtraction, Pi map or guessed half-RTT conversion occurs.

Frame IDs advance within one session and capture time cannot move backwards. A new session requires explicit `start_session(manifest)`, clears the waiting old frame and resets source ordering/message sequence. Old session packets and reuse of any session seen by this adapter are rejected. Person numbers may repeat under a genuinely new session; that does not preserve an old controller association. The bounded session history retains at most 64 identities and rejects further restarts instead of evicting a fence. Start a new declared run/adapter after that limit, using fresh identities.

Invalid input leaves a valid waiting frame intact. One newer accepted frame replaces the entire waiting frame, never just one person's observation. An expired frame is suppressed with its original identity/times retained in diagnostics. Invalid caller times raise `ValidationError` at `take` without consuming pending data. Counter exhaustion is an explicit suppression requiring a fresh session, distinct from an expired capture.

| Counter | Meaning |
| --- | --- |
| `received`, `accepted`, `rejected` | Input-record accounting; malformed/duplicate records are not silently counted as unique lost camera frames |
| `replaced`, `expired`, `suppressed` | Waiting-frame replacement, age expiry and other output suppression, separately |
| `frame_sequence_gaps` | Missing IDs between accepted source frames, not an inferred UDP-loss measurement |
| `source_frames_dropped_total` | Accumulated declared source loss; never inferred from arrival age |
| `session_flushes`, `session_restarts` | Explicit session transition and invalidated waiting work |
| `diagnostics_dropped` | Records overwritten in the bounded diagnostic ring |

The emitted `frame_status.frames_dropped_total` combines this session's declared source losses with known local replacement/suppression losses. Source sequence gaps and rejected input records remain separate because they may overlap with those populations. Healthy zero-person frames and unavailable-camera status remain distinct. Status lists exactly the people emitted from that frame.

## Resource boundary and output

- One waiting frame, at most four people with seventeen joints each; handoff methods use a lock and copy data so caller mutation cannot alter pending observations.
- At most 64 diagnostic records and 64 seen session identities. Diagnostic overflow counts loss; no exporter or observer callback runs in the handoff.
- Incremental JSONL reading, at most 65536 bytes per offline record/manifest; metadata labels at most 128 UTF-8 bytes and image dimensions at most 16384 per axis. This JSON cap is an offline file limit, not a UDP packet size.
- Shared uint32/uint56 bounds are checked before emission. Near wire-counter exhaustion, output is suppressed explicitly.

An emitted result contains per-person `observations`, a common `frame_status`, their complete v0.3 JSON `envelopes`, raw `provenance` and counters. Local diagnostics retain source session/frame IDs, native clock/times and explicit reasons. The subsequent consumer slice exports these records as trace-v1 and verifies the actual offline debug consumer; its separate handoff retains the remaining live/export and owner-adoption limits.

## Shared codec check

The optional development check consumes the adjacent `documentation` checkout. It checks the accepted schema/profile hashes, generates the Python codec in a temporary workspace directory, validates emitted envelopes with the shared validator, performs canonical encode/decode round trips and compares a known-answer pose body with the shared S0 fixture values.

On Windows, in a separate development environment:

```powershell
python -m venv .venv-codec
.\.venv-codec\Scripts\python.exe -m pip install -r requirements-codec.txt
.\.venv-codec\Scripts\python.exe -B scripts/check_shared_contract.py
```

The replay and ordinary suite need none of these packages. The checker exits 2 and reports `skipped` if pinned development dependencies are missing; that is not a pass. It accepts `--documentation-root PATH` when the shared checkout is elsewhere. Temporary generated files are removed afterward; shared contract sources and the historical S0 report are unchanged.

## Validation and handoff

Host validation on 2026-11-11 used Windows and Python 3.14.3. All 47 API/fixture/CLI tests passed. The generated Python codec check passed six cases and twenty envelopes, including four-person/max-counter cases; the largest observed encoded envelope was 497 bytes, below the 1200-byte cap including its envelope. This establishes the exercised host-codec boundary, not nanopb/C, target-device or live transport interoperability. Saved outputs, code/fixture hashes and environment are in [S1 evidence](../evidence/s1-recorded-pose-results.json).

The three example frames cover four people, an explicitly unavailable joint, then one person, then a healthy zero-person frame with declared source loss. Tests also cover malformed JSON/oversized records, invalid dimensions/identities/quality/joints, stale/unknown/cross-clock timing, late consumption, session reuse, replacement, bounded diagnostics and mutation isolation. Replays are deterministic for the same declared input times.

The project user reports a working Xbox Kinect available for future work. The adjacent unversioned `testenv` describes Kinect v2/Xbox One RGB/depth/IR checks from 2026-10-29; no detected person was observed in those recorded tests. No Kinect access or new device test occurred in this task. A future adapter must identify the actual unit/SDK, characterize capture clocks/calibration and map its joint semantics explicitly. Depth-backed data requires a separately reviewed representation before a true-3D claim.

Next bounded task: Pi and debug owners review these fixture outputs and local diagnostic fields, then exercise the same rejected/stale/restart cases at the consumer boundary. Live camera/Kinect feasibility follows a separately authorized scope and the shared gates. This task contributes local S1 evidence and does not accept S1 or release S2.
