# Camera-tracking contributor instructions

These instructions apply to this repository and to both human and AI contributors. Future architecture documents describe a destination, not authorization to build every stage at once.

## Establish the task boundary

1. Read [orientation](docs/orientation.md), [local workflow](docs/workflow.md), the canonical [project status](https://github.com/motion-tennis/documentation/blob/main/docs/project-status.md), and the shared [contribution workflow/task template](https://github.com/motion-tennis/documentation/blob/main/docs/contribution-workflow.md).
2. Inspect Git status and current files; preserve others' work. Record the task's stage ID, bounded deliverable, allowed paths, acceptance evidence and deferred scope. The [shared stage gates](https://github.com/motion-tennis/documentation/blob/main/docs/project-stages.md) control progression; do not maintain a competing local active-stage flag.
3. Implement only the authorized slice. Do not turn a file/synthetic adapter into a live GPU pipeline or a complete playable game, add future scaffolding because it appears in the roadmap, or advance a stage automatically after a local success.
4. An explicit human request for a named later-stage slice is a bounded exception. Record it and its missing prerequisite evidence in the handoff; it does not advance the global stage or authorize adjacent features. Routine fixes within the authorized scope need no repeated approval.
5. If canonical status cannot be read, use the task's pinned verified status/revision. Do not infer runtime authorization from an old README or stage table; record the missing baseline and any explicit human exception instead of inventing progress.

S0 can include explicitly tasked small contract-validation tools and generated-codec fixtures for pose/identity/timestamp compatibility, encoded size and resource bounds. These are validation artifacts, not authorization for a capture adapter, inference runtime, publisher or runtime codec integration.

## Preserve tracking ownership and evidence

- All repository edits, identifiers, comments and examples must be English; use `//` for new C/C++ comments and preserve existing attribution/licenses.
- Capture and inference belong on the Windows laptop. RTMO-m/rtmlib/ONNX Runtime GPU remain a proposed stack until verified; no executable, model, provider performance or pinned version is implied by documentation.
- Capture continuously and preserve source/arrival/completion times, frame/session/person IDs, uncertainty and loss counters. Controller input or an IMU marker must not trigger an exposure or change the 200 Hz controller stream.
- Keep image-space pose semantics, one rectification step, 17-joint identity/quality and explicit missing data consistent with the shared contract. Do not invent metric wrist depth or treat host arrival as camera exposure.
- Pi physics owns confirmed controller/person associations, body-local gesture fusion, avatar movement, hits, serving and scoring. Tracking supplies observations; discovery order/proximity cannot assign teams, tracking loss is not a miss, and the renderer cannot repair invalid collision evidence.
- Preserve native clocks and the Pi-owned mapping/reference epochs. A common verified host-clock fit does not permit reuse of another producer's session-bound map ID. Unknown timing fails applicable freshness gates honestly.
- Coordinate shared schema/profile changes; do not silently alter rates, coordinates, quality semantics or payload limits. The proposed v0.3 full-match schema keeps tracking observations separate from match ownership; use its pinned profile and fixtures without claiming runtime interoperability.

## Validate and hand off

Use implemented/agreed/proposed/open status labels supported by actual evidence. For documentation, run `git diff --check`, inspect untracked Markdown whitespace/final newlines, and run the existing central checker when its checkout is available as described in [orientation](docs/orientation.md#available-checks). Add real build/run/test commands only alongside their authorized implementation; do not report synthetic data as camera/GPU evidence.

End with the stage/slice, paths changed, checks/evidence, unresolved dependencies and limits, any later-stage exception, and the next bounded task using the shared handoff template. Do not automatically begin the next task. Do not commit, push or publish without authorization.
