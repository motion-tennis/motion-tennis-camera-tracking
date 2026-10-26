# S0 tracking contract review and S1 handoff

[Repository home](../README.md) · [Local workflow](workflow.md) · [Central status](https://github.com/motion-tennis/documentation/blob/main/docs/project-status.md) · [Shared contract](https://github.com/motion-tennis/documentation/blob/main/docs/protocol.md)

## Review scope and evidence

Task: S0 component-side contract review and bounded S1 handoff, 2026-10-26. The starting shared revision is `documentation@95c2592`; this review accompanies the S0 schema/profile revision identified by the exact hashes in the shared evidence. The [S0 baseline](https://github.com/motion-tennis/documentation/blob/main/docs/s0-baseline.md) pins the final contract hashes and codec/size results. The candidate is `motion.v03`, protocol `0.3-proposed`, profile `webcam-pi3-doubles-v3`; [ADR 0011](https://github.com/motion-tennis/documentation/blob/main/docs/adr/0011-full-match-contract-and-state-stream.md) records the full-match state channel. This document records an AI technical review, not a human stage decision or an implemented component. The central ledger alone releases S1.

Allowed work here is documentation only. Shared schema, codec fixtures and resource checks belong in `documentation`; runtime integration and hardware measurements retain their later stage gates. Proposed numerical targets remain unmeasured. No later-stage exception is claimed.

## Producer and consumer expectations

- Publish continuous per-person observations and common frame status, independent of controller inputs and diagnostic markers. Keep the original capture, arrival and processing-completion boundaries separate.
- Preserve tracking-session/person/frame IDs, calibration revision, normalized image-space joint coordinates, quality and explicit missing data. A reused person number after tracker restart is a different identity.
- The Pi owns confirmed controller/person/avatar bindings, body-local 2.5D fusion, automatic movement, serving and scoring. Detection order, image side and physical-station movement never assign teams or virtual avatar roots.
- Reference source-session-bound Pi clock maps and uncertainty. A shared Windows host clock does not authorize reuse of the game service's producer session or map identity. Unknown exposure timing is not relabeled as host arrival.
- A suspended, occluded or ambiguous person remains explicitly unavailable; the tracker cannot fabricate a valid pose, a normal sample `MISS` or a replacement player to keep four slots ready.

## Required contract cases

| Case | Expected result and handoff evidence |
| --- | --- |
| Four people in one frame | One frame identity with distinct session-scoped persons and bounded per-person messages; no discovery-order team assignment |
| Missing/duplicate/out-of-range joint | Explicit missing status or validation rejection; no zero-coordinate fabrication or invalid finite/range values |
| Delayed capture with recent arrival | Capture age remains old; the Pi applies age/alignment gates using the declared clock map |
| Tracker restart and repeated person number | Old binding is suspended; explicit reconfirmation and installation/resume are needed |
| Occlusion or ambiguous re-identification | Preserve the established reservation and explicit failure; never silently transfer a controller/team |
| Maximum person/joint message | Generated codec and size fixture within the selected bound, retaining all required joints and identities |

Codec and synthetic fixture results do not establish camera exposure accuracy, GPU compatibility, four-person quality, metric wrist depth or timing.

## First bounded S1 task

**Outcome:** a deterministic file/synthetic pose adapter that emits the shared observation contract with source provenance and bounded buffers. Allow fixture input, adapter validation, focused tests and actual local commands. Defer camera capture, model downloads, GPU inference, live publishing and gameplay.

**Dependencies:** accepted schema/profile and pinned sample fixtures; explicit input coordinate/capture-time/calibration conventions. No GPU or webcam is needed for this isolated slice.

**Acceptance:** deterministic valid output; missing-joint, invalid coordinate/quality, duplicate identity, stale capture, unknown timing and session-restart rejection cases; preserved frame/person/session IDs and loss counters; one-slot latest-frame capacity with explicit replacement accounting. Save fixture hashes and actual test output. Handoff to Pi pose-history and debug provenance checks.

## Review disposition

The tracking boundary is compatible with the full-match extension because observations keep their own identities and match membership remains versioned setup state. Shared codec/size evidence and unresolved contract findings are recorded centrally. This repository still has no capture/inference runtime or hardware test result.
