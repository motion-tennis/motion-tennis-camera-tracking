#include <cstdint>
#include <iostream>
#include <string_view>

#include "fixtures.hpp"
#include "motion_tennis/physics/batch_core.hpp"
#include "motion_tennis/physics/fakes.hpp"
#include "tracking_fixture.hpp"

using namespace motion_tennis::physics;
using namespace motion_tennis::physics::fixtures;
using namespace motion_tennis::physics::fakes;

namespace {
std::uint32_t failed = 0;

void check(std::string_view name, bool condition) {
    std::cout << (condition ? "PASS " : "FAIL ") << name << '\n';
    if (!condition) ++failed;
}

TrackingSourceSession source_of(const TrackingFrameBatch& frame) {
    const auto& envelope = frame.status_envelope;
    return {envelope.sender_id, envelope.sender_session_id, envelope.run_id, envelope.clock_id};
}

PiClockReference reference() { return {filled_uuid('P'), 1}; }

MatchSetup setup_for(const TrackingFrameBatch& frame) {
    auto setup = build_setup();
    for (std::size_t index = 0; index < setup.configuration.players.size(); ++index) {
        auto& player = setup.configuration.players[index];
        player.person_id = frame.status.person_ids[index];
        player.tracking_session_id = frame.status_envelope.sender_session_id;
    }
    return setup;
}

TrackingClockMap mapping_for(const TrackingFrameBatch& frame) {
    TrackingClockMap map;
    map.mapping_id = 1;
    map.version = 1;
    map.source = source_of(frame);
    map.reference = reference();
    map.source_anchor_us = 1000000;
    map.pi_anchor_us = 500000;
    map.rate_numerator = 1;
    map.rate_denominator = 1;
    map.valid_from_source_us = 900000;
    map.valid_until_source_us = 2100000;
    map.issued_pi_us = 400000;
    map.last_good_pi_us = 400000;
    map.valid_from_pi_us = 400000;
    map.valid_until_pi_us = 1600000;
    map.uncertainty_us = 500;
    map.valid = true;
    return map;
}

bool configure(TrackingPoseBridge& bridge, const TrackingFrameBatch& frame, bool with_map = true) {
    if (bridge.start_session(source_of(frame), reference(), {0.5f}) != BridgeCode::Accepted) return false;
    BoundedVector<PlayerBinding, kPlayers> bindings;
    for (const auto& player : setup_for(frame).configuration.players) bindings.push_back(player);
    if (bridge.install_confirmed_bindings(bindings) != BridgeCode::Accepted) return false;
    return !with_map || bridge.install_clock_map(mapping_for(frame)) == BridgeCode::Accepted;
}

bool no_usable_pose(const TrackingPoseBridge& bridge, std::uint32_t person) {
    const auto pose = bridge.latest_for(person);
    return !pose || !pose->tracked;
}
}  // namespace

int main() {
    const auto actual = actual_tracking_fixture::frame_0();
    const std::uint32_t person = actual.people[0].frame.person_id;
    {
        TrackingPoseBridge bridge;
        check("actual_four_person_frame_admitted", configure(bridge, actual) &&
              bridge.ingest_frame(actual, 505000) == BridgeCode::Accepted);
        const auto pose = bridge.latest_for(person);
        bool every_source_preserved = true;
        for (const auto& packet : actual.people) {
            const auto retained = bridge.latest_for(packet.frame.person_id);
            every_source_preserved = every_source_preserved && retained &&
                retained->source_frame == packet.frame && retained->envelope == packet.envelope;
        }
        check("actual_joint_state_raw_time_and_uuid_preserved", pose &&
              every_source_preserved &&
              pose->source_frame == actual.people[0].frame && pose->envelope == actual.people[0].envelope &&
              pose->mapping == mapping_for(actual) && pose->capture_pi_us == 500000 &&
              pose->total_uncertainty_us >= 1500 && pose->calibration_id == 1);
        auto setup = setup_for(actual);
        FakeStateService service(setup, build_snapshot(setup));
        ScriptedContactEvaluator evaluator;
        BatchCore core(setup, kInitialTick, bridge, evaluator);
        core.admit(input_for(1, 1, 505000), 505000);
        const auto run = run_batch(core, service, 101, 505000);
        const auto feedback = core.take_feedback();
        bool committed = false;
        for (const auto& item : feedback) committed = committed || item.committed;
        check("actual_bridge_drives_real_core_with_declared_fakes", run.result && committed);
    }
    {
        TrackingPoseBridge bridge;
        const bool configured = configure(bridge, actual, false);
        check("missing_pi_map_rejected", configured && bridge.ingest_frame(actual, 505000) != BridgeCode::Accepted &&
              no_usable_pose(bridge, person));
    }
    {
        TrackingPoseBridge bridge;
        auto bad = actual;
        bad.people[0].frame.calibration_id = 999;
        check("calibration_mismatch_rejected", configure(bridge, actual) &&
              bridge.ingest_frame(bad, 505000) != BridgeCode::Accepted && no_usable_pose(bridge, person));
    }
    {
        TrackingPoseBridge bridge;
        check("uncertainty_inclusive_stale_pose_rejected", configure(bridge, actual) &&
              bridge.ingest_frame(actual, 579500) != BridgeCode::Accepted && no_usable_pose(bridge, person));
    }
    {
        TrackingPoseBridge bridge;
        auto future = actual;
        future.status_envelope.sent_time_us = 2000000;
        for (auto& packet : future.people) {
            packet.frame.processing_complete_us = 2000000;
            packet.envelope.sent_time_us = 2000000;
        }
        check("future_processing_and_send_boundaries_rejected", configure(bridge, actual) &&
              bridge.ingest_frame(future, 505000) != BridgeCode::Accepted && no_usable_pose(bridge, person));
    }
    {
        TrackingPoseBridge bridge;
        auto unavailable = actual;
        unavailable.people[0].frame.joints[10].state = TrackingState::Unavailable;
        check("unavailable_required_wrist_stays_ineligible", configure(bridge, actual) &&
              bridge.ingest_frame(unavailable, 505000) == BridgeCode::Accepted && no_usable_pose(bridge, person));
    }
    {
        TrackingPoseBridge bridge;
        const bool admitted = configure(bridge, actual) && bridge.ingest_frame(actual, 505000) == BridgeCode::Accepted;
        check("duplicate_frame_rejected", admitted && bridge.ingest_frame(actual, 505000) != BridgeCode::Accepted);
    }
    {
        TrackingPoseBridge bridge;
        const bool admitted = configure(bridge, actual) && bridge.ingest_frame(actual, 505000) == BridgeCode::Accepted;
        const auto empty = actual_tracking_fixture::frame_2();
        check("actual_empty_frame_invalidates_cached_people", admitted &&
              bridge.ingest_frame(empty, 565000) == BridgeCode::Accepted && no_usable_pose(bridge, person));
        check("source_loss_and_frame_gap_remain_separate", bridge.counters().source_frames_dropped_total == 1 &&
              bridge.counters().frame_sequence_gaps == 2);
    }
    {
        TrackingPoseBridge bridge;
        auto incomplete = actual;
        incomplete.people.clear();
        check("status_membership_requires_complete_person_set", configure(bridge, actual) &&
              bridge.ingest_frame(incomplete, 505000) != BridgeCode::Accepted && no_usable_pose(bridge, person));
    }
    {
        TrackingPoseBridge bridge;
        const bool admitted = configure(bridge, actual) && bridge.ingest_frame(actual, 505000) == BridgeCode::Accepted;
        auto reversed = actual_tracking_fixture::frame_1();
        reversed.status.frames_dropped_total = 1;
        const bool next = bridge.ingest_frame(reversed, 525000) == BridgeCode::Accepted;
        auto empty = actual_tracking_fixture::frame_2();
        empty.status.frames_dropped_total = 0;
        check("regressing_source_loss_rejected", admitted && next && bridge.ingest_frame(empty, 565000) != BridgeCode::Accepted);
    }
    {
        TrackingPoseBridge bridge;
        const bool admitted = configure(bridge, actual) && bridge.ingest_frame(actual, 505000) == BridgeCode::Accepted;
        const auto restarted = actual_tracking_fixture::frame_3();
        const bool reset = bridge.start_session(source_of(restarted), reference(), {0.5f}) == BridgeCode::Accepted;
        check("restart_clears_old_pose_and_requires_new_binding", admitted && reset && no_usable_pose(bridge, person) &&
              bridge.ingest_frame(restarted, 505000) != BridgeCode::Accepted);
        BoundedVector<PlayerBinding, kPlayers> bindings;
        for (const auto& player : setup_for(restarted).configuration.players) bindings.push_back(player);
        const bool rebound = bridge.install_confirmed_bindings(bindings) == BridgeCode::Accepted &&
                             bridge.install_clock_map(mapping_for(restarted)) == BridgeCode::Accepted;
        const auto next = actual_tracking_fixture::frame_4();
        check("new_session_person_numbers_reusable_after_explicit_setup", rebound &&
              bridge.ingest_frame(next, 515000) == BridgeCode::Accepted && !no_usable_pose(bridge, person));
        check("retired_tracker_session_rejected", bridge.start_session(source_of(actual), reference(), {0.5f}) != BridgeCode::Accepted);
    }
    {
        TrackingPoseBridge bridge;
        const bool admitted = configure(bridge, actual) && bridge.ingest_frame(actual, 505000) == BridgeCode::Accepted;
        auto pi = reference();
        pi.session_id = filled_uuid('Q');
        check("pi_epoch_change_fences_cached_pose_and_maps", admitted &&
              bridge.start_session(source_of(actual), pi, {0.5f}) == BridgeCode::Accepted &&
              no_usable_pose(bridge, person) && bridge.install_clock_map(mapping_for(actual)) != BridgeCode::Accepted);
    }
    std::cout << "RESOURCE tracking_pose_bridge " << sizeof(TrackingPoseBridge) << '\n';
    std::cout << "RESOURCE pose_observation " << sizeof(PoseObservation) << '\n';
    std::cout << "RESOURCE batch_core " << sizeof(BatchCore) << '\n';
    return failed == 0 ? 0 : 1;
}
