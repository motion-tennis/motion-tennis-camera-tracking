# Camera-tracking repository orientation

[Repository home](../README.md) · [Local workflow](workflow.md) · [Contributor instructions](../AGENTS.md) · [Canonical project status](https://github.com/motion-tennis/documentation/blob/main/docs/project-status.md)

## Purpose and present evidence

This repository supplies continuous camera observations and temporal person identity for Motion Tennis. Webcam capture/inference runs on the Windows laptop; the Pi receives compact pose observations for body-local arm/racket gestures. Human participants remain at calibrated physical stations while Pi physics moves the virtual avatars.

**Implemented here:** README, contributor/orientation/workflow documents and MIT license. No capture adapter, model artifact, inference worker, publisher, executable, dependency lock or local test suite exists. Native Media Foundation capture with Python RTMO-m/rtmlib/ONNX Runtime GPU is a **proposed** implementation. Camera generation, actual GPU provider compatibility, four-person quality and latency still require evidence. The adjacent offline debug checker is not proof of a tracking runtime.

Read the central [project status](https://github.com/motion-tennis/documentation/blob/main/docs/project-status.md) for the current global stage. The [shared gates](https://github.com/motion-tennis/documentation/blob/main/docs/project-stages.md) and [local workflow](workflow.md) describe staged work; they do not authorize every future feature. Keep the active-stage decision in the canonical record rather than duplicating it here.

## Place in the system

| Boundary | This repository owns | Other owner / shared contract |
| --- | --- | --- |
| Capture input | Camera or explicitly synthetic/file input, source timestamp semantics, host arrival, frame IDs and counted skips | Actual Windows/camera behavior must be characterized; [tracking stack](https://github.com/motion-tennis/documentation/blob/main/docs/tracking-stack.md) |
| Pose/identity output | Rectified-image normalized joints, session-scoped person IDs, confidence/missing-data status and inference provenance | Pi performs body-local calibrated fusion and gameplay decisions; [tracking](https://github.com/motion-tennis/documentation/blob/main/docs/tracking.md) |
| Transport output | Bounded per-person `skeleton_frame` plus common frame identity and `frame_status`; optional display observations | Central [protocol](https://github.com/motion-tennis/documentation/blob/main/docs/protocol.md) governs schemas/ports; neither raw video nor inference runs on the Pi |
| Control/association | Configuration/readiness evidence, guided-person observation and raw clock-exchange responses | Operator confirms and Pi installs controller/person/avatar associations; [player assignment](https://github.com/motion-tennis/documentation/blob/main/docs/player-assignment.md) |
| Time and diagnostics | Original capture/arrival/completion records, uncertainty, source session and losses | Pi owns host-clock mappings; camera exposure conversion remains separately characterized; [clock contract](https://github.com/motion-tennis/documentation/blob/main/docs/coordinates-and-time.md#pi-reference-clock-mapping) |

The tracker does not decide hits, move avatars, award points or infer teams from left/right image order. A physical wrist location is not a virtual court root position, and a monocular pose is not measured metric 3D. Missing or ambiguous observations remain explicit failures for physics to handle. The camera runs continuously, independent of controller transactions and additional IMU trace markers.

Windows game storage owns the committed match snapshot after Pi calculation and renders two views. A selected pose is linked to the full controller/query/commit path by source IDs; it need not have been captured after a diagnostic marker. Respect existing timestamp meaning and uncertainty instead of moving timestamps to make the trace look synchronized.

## Reading order for a new task

1. Read [project status](https://github.com/motion-tennis/documentation/blob/main/docs/project-status.md), [shared stages](https://github.com/motion-tennis/documentation/blob/main/docs/project-stages.md), and the [contribution workflow/task template](https://github.com/motion-tennis/documentation/blob/main/docs/contribution-workflow.md); name the stage, slice and acceptance evidence.
2. Read [local workflow](workflow.md) and the [component README](../README.md). Use the implementation status to separate current files from future modules.
3. Read the relevant [tracking](https://github.com/motion-tennis/documentation/blob/main/docs/tracking.md), [tracking-stack](https://github.com/motion-tennis/documentation/blob/main/docs/tracking-stack.md), [protocol](https://github.com/motion-tennis/documentation/blob/main/docs/protocol.md), [calibration/clock](https://github.com/motion-tennis/documentation/blob/main/docs/coordinates-and-time.md) and [reference profile](https://github.com/motion-tennis/documentation/blob/main/spec/reference-profile.json) sections affected by the slice.
4. Inspect files/Git status and record cross-repository dependencies before editing. Use the shared handoff format so another contributor can reproduce what was checked and identify the next bounded task.

## Available checks

The existing repository-local check for tracked changes is:

```sh
git diff --check
```

Inspect new untracked Markdown separately for trailing whitespace and final newlines. If the central documentation checkout is available, run its existing checker **from that checkout**:

```sh
python3 scripts/check_docs.py
```

It checks available sibling documentation; it does not test webcam capture, model licenses/artifacts, GPU execution, tracking accuracy or timing. Missing sibling checkouts are not verified remote content. No model installation, runtime launch or tracking-test command exists here yet; add such commands only with the corresponding authorized implementation.

## Small S0 tasks to propose

Choose one documented slice using the shared task template, for example:

- Review joint/frame/person/quality and timestamp fields against the future versioned match/roster integration, retaining image-space pose ownership.
- When explicitly tasked, add small contract-validation tools or generated-codec fixtures for compatibility, maximum encoded size and resource bounds; keep them separate from capture/inference/publisher runtime integration.
- Specify synthetic known-answer cases for missing joints, session restart, ambiguous identity, stale capture and body-local 2.5D calibration without implementing the live pipeline.
- Record the camera/model/provider and exposure-timing evidence needed by the later Windows feasibility stage, including exact provenance and validation criteria.

These are S0 contract/planning suggestions; a small validation tool needs its own explicit task scope. They do not authorize installing a GPU stack, acquiring a live camera stream, implementing a tracker or integrating the whole game. Future runtime slices follow named stage gates and explicit task authorization.
