# Motion Tennis Camera Tracking

The camera and pose-estimation component of **Motion Tennis**, a doubles tennis demonstrator for four people in two fixed teams. The first implementation targets a webcam on the available **Windows laptop with an RTX 5080**. Its observations provide body-relative arm/racket gestures and player-identity evidence to the **Raspberry Pi 3 Model B**, which moves avatar roots automatically.

**Start contributing:** read [repository orientation](docs/orientation.md), [staged workflow](docs/workflow.md) and [AGENTS.md](AGENTS.md), then check the canonical [project status](https://github.com/motion-tennis/documentation/blob/main/docs/project-status.md). Use the [shared task/handoff workflow](https://github.com/motion-tennis/documentation/blob/main/docs/contribution-workflow.md) to bound each human or AI contribution; future architecture sections do not authorize implementing the whole pipeline at once.

The [S0 contract review and first S1 handoff](docs/s0-contract-review.md) record this component's producer/consumer expectations, required fixtures and remaining evidence.

## Status and reference profile

| Status | Meaning |
| --- | --- |
| **Implemented** | Documentation and an MIT license only; no capture adapter, model integration, runtime configuration, executable or test suite exists |
| **Agreed direction** | Webcam-first doubles with one controller/person/avatar per slot; stationary human gestures and automatic avatar locomotion; calibrated 2.5D first, a separately verified true-3D phase later |
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

Physics owns controller/person association, calibrated body-relative gesture mapping, historical IMU alignment, sensor fusion, automatic avatar movement and match calculations. Publish wrist/arm and shoulder/torso reference observations so it can combine local racket motion with the virtual avatar root/heading. A physical wrist position is not the avatar's court position, and a single RGB image does not measure metric wrist depth. Keep published joints in the existing image-space representation. The tracker does not own match state, decide hits or turn missing poses into ordinary misses. Controller transactions do not trigger new exposures.

The [agreed gameplay](https://github.com/motion-tennis/documentation/blob/main/docs/gameplay.md) keeps people in calibrated physical stations; these support visibility/separation and are not virtual lanes or team sides. Observe the assigned server's body-relative lift and subsequent overhead swing while physics owns toss/contact recognition. Both camera acquisition and every controller's 200 Hz stream remain continuous; the diagnostic marker cannot trigger an exposure or authorize a serve. The proposed v0.3 match-state extension retains these observation semantics and continuous streams; the [S0 baseline](https://github.com/motion-tennis/documentation/blob/main/docs/s0-baseline.md) records its fixtures and implementation gates.

The [independent IMU threshold-marker overlay](https://github.com/motion-tennis/documentation/blob/main/docs/imu-trigger-markers.md) joins selected pose/frame identities to the existing controller transaction path. Preserve original capture timestamps and person/session IDs; continuous camera acquisition does not wait for a marker or take an extra triggered frame. A selected pose may predate the marker and remains input provenance, not marker-triggered work.

## Inputs, outputs, and connections

Interfaces below are **proposed**, following the central [`0.3-proposed` protocol](https://github.com/motion-tennis/documentation/blob/main/docs/protocol.md).

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

## Pi reference clock mapping

The [agreed clock design](https://github.com/motion-tennis/documentation/blob/main/docs/coordinates-and-time.md#pi-reference-clock-mapping) maps native host time to Pi time with offset and drift correction, `T_pi = a * t_source + b`. Keep raw timestamps and clock/session identities; never step the host clock. Respond to Pi-coordinated `ClockExchange` over existing TCP control at complete-frame receipt and the declared response-send boundary. A verified common laptop domain and units may share a clock fit, but tracking, game and renderer each retain separate producer-session-bound mapping records/IDs. Distinct domains require separate fits.

A camera/driver clock needs its own characterized conversion and exposure-boundary uncertainty: host arrival is not exposure time. Runtime pose selection and debug traces use the same Pi-owned mapping version, validity, uncertainty and source/reference epochs. Source restart invalidates its mapping; a Pi reference restart invalidates all live mappings. Unknown, expired or insufficiently accurate timing fails pose freshness/alignment gates without stopping continuous capture or controller sample/failure accounting; local RTT remains valid independently. This integration is not implemented and changes no gameplay payload or 200 Hz controller behavior.

## Setup and planned entry points

The verified Git remote can be cloned with:

```sh
git clone git@github.com:motion-tennis/motion-tennis-camera-tracking.git
cd motion-tennis-camera-tracking
```

This requires configured GitHub access. There is no service to build, configure or launch yet. Planned modules are the timestamp-preserving capture adapter, latest-frame shared buffer, RTMO inference worker, temporal identity tracker, packet publisher and trace adapter. Add real dependency locks, model checksums, source paths and launch commands with implementation. Do not download arbitrary GPU wheels or claim a version combination was tested from the existence of this README.

Follow the [integrated startup plan](https://github.com/motion-tennis/documentation/blob/main/docs/development.md) and [assignment contract](https://github.com/motion-tennis/documentation/blob/main/docs/player-assignment.md). The proposed slots are `1=A1`, `2=A2`, `3=B1`, `4=B2`. Identify one controller/person at a time through guided motion at a physical station, require explicit operator confirmation, and complete the versioned Association acknowledgement/resume barrier. Revalidate identity after loss or restart; detection order, proximity and camera side never assign a team. Normal doubles requires all four slots ready; one-to-three-player runs are integration tests without implicit AI fill. End changes and front/back roles preserve each player/controller/avatar/team identity.

## Smoke test and validation

The following acceptance coverage belongs to the named [workflow stages](docs/workflow.md), not to one task that builds the entire pipeline:

- **S1, isolated slice:** use labeled file/synthetic fixtures to validate image-space joints, person/session identity, timestamp/quality semantics and bounded adapter output. A fixture pass is not camera or GPU evidence.
- **S2, feasibility:** capture actual Windows webcam frames, verify the selected GPU provider/model and mapped coordinates, then exercise per-person publication plus frame status against explicit receivers/stubs. Measure four-person focus/FOV, identity, calibration and exposure timing, including crossing/occlusion, distractors, skipped/stale frames and restart cases.
- **S3, real diagnostic path:** pair one real controller, verify Pi pose selection and historical IMU alignment with the accepted time maps/uncertainty, and follow the required ball-query/commit/feedback chain and explicit marker links. Invalid input must suppress hit eligibility and produce an explicit diagnostic outcome.
- **S4, doubles:** verify four stable team/slot/person/controller bindings and body-relative racket/overhead-serve observations while Pi handles virtual locomotion. Camera capture remains continuous through gestures and markers. S5 owns the full matched load/fault/topology measurement campaign.

No hardware, inference or networking smoke test is implemented or executed. Current local documentation check:

```sh
git diff --check
```

Run the shared documentation checker from the central repository as described in [development](https://github.com/motion-tennis/documentation/blob/main/docs/development.md). Future acceptance must report frame delivery/inference/age distributions, useful-pose rate, uncertain identities, packet gaps and skipped frames under render load. See [testing](https://github.com/motion-tennis/documentation/blob/main/docs/testing.md) and [debugging](https://github.com/motion-tennis/documentation/blob/main/docs/debugging.md).

## Repository layout and limitations

```text
README.md            Component reference profile and implementation status
AGENTS.md            Contributor instructions and scope boundaries
docs/orientation.md  Role, reading order, actual evidence and checks
docs/workflow.md     Local deliverables mapped to shared stage gates
LICENSE              Existing MIT license
```

There is no model artifact or runnable code. Room-scale camera focus, four-person identity stability, GPU compatibility, exposure timestamp uncertainty and calibrated plane accuracy must pass their gates before gameplay claims. Full 3D requires an independently verified depth/multi-view profile.

## Related repositories, contribution, and license

- [Documentation hub](https://github.com/motion-tennis/documentation), [controller](https://github.com/motion-tennis/motion-tennis-controller), [physics](https://github.com/motion-tennis/motion-tennis-physics-engine), [game engine](https://github.com/motion-tennis/motion-tennis-game-engine), and [debug-units](https://github.com/motion-tennis/debug-units).
- All project edits must be in English, including code, identifiers, comments, docstrings, examples and diagrams. New C/C++ comments use `//`.
- Keep shared interface changes synchronized with the central protocol and affected repositories. Preserve the distinction between proposed behavior and tested implementation.

Licensed under the [MIT License](LICENSE), copyright 2026 Viktor Hofer. Preserve this attribution and separately review dependency/model notices.
