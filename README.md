# Motion Tennis Camera Tracking

The camera and pose-estimation component of **Motion Tennis**, a multiplayer tennis demonstrator for up to four players. The first implementation targets a webcam on the available **Windows laptop with an RTX 5080**. Its observations actively contribute to player/racket movement and physics decisions on the **Raspberry Pi 3 Model B**.

## Status and reference profile

| Status | Meaning |
| --- | --- |
| **Implemented** | Documentation and an MIT license only; no capture adapter, model integration, runtime configuration, executable or test suite exists |
| **Agreed direction** | Webcam-first gameplay with four battery-powered wireless controllers; calibrated 2.5D first, a separately verified true-3D phase later |
| **Proposed reference** | Native Windows Media Foundation capture, Python RTMO-m 640 × 640 via rtmlib/ONNX Runtime GPU, continuous temporal person tracking and compact pose publication |
| **Open** | Exact webcam generation, verified GPU/runtime versions, model checksum/notices, calibrated confidence thresholds and actual four-person accuracy/latency |

See the [master plan](https://github.com/motion-tennis/documentation/blob/main/docs/master-plan.md) and [tracking-stack specification](https://github.com/motion-tennis/documentation/blob/main/docs/tracking-stack.md). The webcam-first profile replaces the earlier Kinect-first prerequisite. Kinect v2 is an optional later depth adapter requiring its own verified skeleton backend.

## Hardware and prerequisites

The user is considering an Elgato Facecam or an alternative; the generation is not confirmed. Desired capture is 1920 × 1080 at 60 frames/s. Facecam/MK.2 desk-focus limits must be checked against four-player room distances. Facecam 4K in its 1080p mode is a candidate with a broader published focus range, but no camera is approved by measurement yet. The [hardware guide](https://github.com/motion-tennis/documentation/blob/main/docs/hardware.md) and [camera selection evidence](https://github.com/motion-tennis/documentation/blob/main/docs/tracking-stack.md#camera-selection-and-commissioning) define the gate.

Capture and inference stay on the laptop. The Pi receives observations, not raw video. Verify the actual Windows build, GPU/driver, USB topology, runtime execution provider and model compatibility; an RTX 5080 label does not establish latency or prevent CPU fallback. Git and a Markdown viewer are sufficient for current documentation work. Python/ONNX/CUDA dependencies are planned, with no tested installation command yet.

## Responsibilities and boundaries

- Acquire frames continuously with preserved source timestamp semantics and a fresh tracking session after restart.
- Undistort once in the capture adapter using versioned calibration and `K_rect`; run full-frame pose estimation on a letterboxed rectified image, undo letterboxing, and publish 17 COCO joints normalized to the rectified image's original dimensions. Physics uses `K_rect` without undistorting again.
- Maintain session-scoped temporal person IDs and explicitly report uncertain identity, occlusion, unavailable joints and stream failure.
- Keep one waiting image; replace old waiting images and count skips instead of building capture backlog.
- Expose timestamps, model/profile identity and loss counters to the shared debug environment.

Physics owns controller/person association, calibrated plane mapping, historical IMU alignment, sensor fusion and hit calculation. A single RGB image is not measured metric wrist depth; do not label image-space joints as world-space metres. The tracker does not own ball state, decide hits or turn missing poses into ordinary misses. Controller transactions do not trigger new exposures.

## Inputs, outputs, and connections

Interfaces below are **proposed**, following the central [`0.2-proposed` protocol](https://github.com/motion-tennis/documentation/blob/main/docs/protocol.md).

| Direction | Interface | Component |
| --- | --- | --- |
| Input | Webcam images and raw driver/capture metadata | Native Windows capture adapter |
| Configuration | Camera/inference profile and calibration identity | Operator setup and shared run manifest |
| Output | One `skeleton_frame` UDP/Protobuf datagram per person, at most 1,200 bytes; common source frame ID | Physics on Pi; optional game display subscription |
| Output | `frame_status` with observed IDs and stream/loss information | Physics and display diagnostics |
| Output | Buffered correlated trace records; optional independently buffered diagnostic video | `debug-units` |

Source timestamps, host arrival, processing completion and Pi arrival are distinct. UDP loss is not an explicit body-loss message; missing packets and skipped camera frames must be counted separately. Exact schema, endpoint and lifecycle rules are central, not duplicated here.

## Runtime and timing contract

The candidate profile targets at least 30 pose updates/s for four people, preferably 60, from desired 1080p60 capture and 640 × 640 RTMO-m inference. These are acceptance targets, not current capabilities. Physics retains eight pose frames/person and 256 IMU samples/controller. It aligns delayed pose capture with historical IMU samples, then propagates orientation to the current decision.

Candidate limits are pose age 80 ms, current IMU age 30 ms, historical pose/IMU alignment 25 ms, plane-position prediction 50 ms, per-network-clock uncertainty 2 ms and measured camera timestamp uncertainty 8 ms. Apply uncertainty conservatively; prediction does not change capture time. See [tracking and fusion inputs](https://github.com/motion-tennis/documentation/blob/main/docs/tracking.md) for exact meanings and [timing](https://github.com/motion-tennis/documentation/blob/main/docs/timing.md) for controller response/actuation targets. Continuous camera work is not wholly inside each application round trip.

## Setup and planned entry points

The verified Git remote can be cloned with:

```sh
git clone git@github.com:motion-tennis/motion-tennis-camera-tracking.git
cd motion-tennis-camera-tracking
```

This requires configured GitHub access. There is no service to build, configure or launch yet. Planned modules are the timestamp-preserving capture adapter, latest-frame shared buffer, RTMO inference worker, temporal identity tracker, packet publisher and trace adapter. Add real dependency locks, model checksums, source paths and launch commands with implementation. Do not download arbitrary GPU wheels or claim a version combination was tested from the existence of this README.

Follow the [integrated startup plan](https://github.com/motion-tennis/documentation/blob/main/docs/development.md). Pair one controller/person at a time in marked lanes and require explicit confirmation. Revalidate identity after loss; do not bind controllers according to detection order or proximity alone.

## Smoke test and validation

**Planned smoke test:** capture one person's timestamped frames; confirm GPU inference and mapped image coordinates; publish the per-person packet plus frame status; pair a controller; verify Pi selection and historical IMU alignment. Repeat for four people, crossing/occlusion, distractors, stale frames and tracker restart. Failure must disable hit eligibility and produce an explicit diagnostic outcome.

No hardware, inference or networking smoke test is implemented or executed. Current local documentation check:

```sh
git diff --check
```

Run the shared documentation checker from the central repository as described in [development](https://github.com/motion-tennis/documentation/blob/main/docs/development.md). Future acceptance must report frame delivery/inference/age distributions, useful-pose rate, uncertain identities, packet gaps and skipped frames under render load. See [testing](https://github.com/motion-tennis/documentation/blob/main/docs/testing.md) and [debugging](https://github.com/motion-tennis/documentation/blob/main/docs/debugging.md).

## Repository layout and limitations

```text
README.md  Component reference profile and implementation status
LICENSE    Existing MIT license
```

There is no model artifact or runnable code. Room-scale camera focus, four-person identity stability, GPU compatibility, exposure timestamp uncertainty and calibrated plane accuracy must pass their gates before gameplay claims. Full 3D requires an independently verified depth/multi-view profile.

## Related repositories, contribution, and license

- [Documentation hub](https://github.com/motion-tennis/documentation), [controller](https://github.com/motion-tennis/motion-tennis-controller), [physics](https://github.com/motion-tennis/motion-tennis-physics-engine), [game engine](https://github.com/motion-tennis/motion-tennis-game-engine), and [debug-units](https://github.com/motion-tennis/debug-units).
- All project edits must be in English, including code, identifiers, comments, docstrings, examples and diagrams. New C/C++ comments use `//`.
- Keep shared interface changes synchronized with the central protocol and affected repositories. Preserve the distinction between proposed behavior and tested implementation.

Licensed under the [MIT License](LICENSE), copyright 2026 Viktor Hofer. Preserve this attribution and separately review dependency/model notices.
