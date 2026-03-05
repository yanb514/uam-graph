"""
Simulation engine for UAM corridor communication-transportation model.

Implements discrete-time simulation with:
  - UAM movement and car-following
  - Coverage computation and handoff
  - Traffic generation and M/M/1 queuing
  - Mode switching (HOTL <-> HWTL)
  - KPI recording
"""

import math
import random
import copy

from uam_sim.models import Corridor, Hub, UAM, BaseStation, CommGraph, Mode
from uam_sim.metrics import MetricsCollector


def run_simulation(config):
    """Run a single simulation scenario.

    Args:
        config: dict following the configuration schema (see config.py)

    Returns:
        dict with keys:
          "config"    - copy of the input config
          "metrics"   - MetricsCollector with all recorded data
          "final_state" - snapshot of final simulation state
    """
    cfg = copy.deepcopy(config)
    rng = random.Random(cfg["simulation"]["random_seed"])

    # --- Build world objects ---
    corridors = {c["id"]: Corridor(c) for c in cfg["corridors"]}
    hubs = [Hub(h) for h in cfg["hubs"]]
    base_stations = {bs_cfg["id"]: BaseStation(bs_cfg) for bs_cfg in cfg["base_stations"]}
    graph = CommGraph()

    # Add GCS node
    graph.add_node("GCS", "ground_control")

    # Add BS nodes
    for bs_id, bs in base_stations.items():
        graph.add_node(bs_id, "base_station",
                       x=bs.position_x, y=bs.position_y,
                       capacity_bps=bs.capacity_bps)
        # BS-GCS links (always up, high capacity)
        graph.add_edge(bs_id, "GCS", quality="good", rtt=0.01)
        graph.add_edge("GCS", bs_id, quality="good", rtt=0.01)

    # --- Spawn UAMs ---
    uam_cfg = cfg["uams"]
    num_uams = uam_cfg["num_uams"]
    speed_range = uam_cfg["speed_mps"]
    corridor_id = cfg["corridors"][0]["id"]
    corridor = corridors[corridor_id]
    num_lanes = corridor.num_lanes

    uams = {}
    if uam_cfg["spawn_pattern"] == "uniform":
        # Spread UAMs uniformly along the corridor
        spacing = corridor.length_m / (num_uams + 1)
        for i in range(num_uams):
            uid = f"UA{i+1:03d}"
            pos = spacing * (i + 1)
            vel = rng.uniform(speed_range[0], speed_range[1])
            lane = i % num_lanes
            uam = UAM(uid, corridor_id, lane, pos, vel)
            uam.spawned_at = cfg["simulation"]["t_start"]
            # Initialize mode switch timer (Poisson inter-arrival)
            ms_cfg = cfg["mode_switch"]
            if ms_cfg["model"] == "poisson" and ms_cfg["lambda_per_hour"] > 0:
                lam = ms_cfg["lambda_per_hour"] / 3600.0  # per second
                uam.mode_switch_timer = rng.expovariate(lam) if lam > 0 else float("inf")
            uams[uid] = uam
    elif uam_cfg["spawn_pattern"] == "batch":
        # All UAMs start near origin hub
        for i in range(num_uams):
            uid = f"UA{i+1:03d}"
            pos = rng.uniform(0, corridor.length_m * 0.1)
            vel = rng.uniform(speed_range[0], speed_range[1])
            lane = i % num_lanes
            uam = UAM(uid, corridor_id, lane, pos, vel)
            uam.spawned_at = cfg["simulation"]["t_start"]
            ms_cfg = cfg["mode_switch"]
            if ms_cfg["model"] == "poisson" and ms_cfg["lambda_per_hour"] > 0:
                lam = ms_cfg["lambda_per_hour"] / 3600.0
                uam.mode_switch_timer = rng.expovariate(lam) if lam > 0 else float("inf")
            uams[uid] = uam
    else:
        # Poisson arrival: spawn over time (simplified: spawn all initially with random positions)
        for i in range(num_uams):
            uid = f"UA{i+1:03d}"
            pos = rng.uniform(0, corridor.length_m)
            vel = rng.uniform(speed_range[0], speed_range[1])
            lane = i % num_lanes
            uam = UAM(uid, corridor_id, lane, pos, vel)
            uam.spawned_at = cfg["simulation"]["t_start"]
            ms_cfg = cfg["mode_switch"]
            if ms_cfg["model"] == "poisson" and ms_cfg["lambda_per_hour"] > 0:
                lam = ms_cfg["lambda_per_hour"] / 3600.0
                uam.mode_switch_timer = rng.expovariate(lam) if lam > 0 else float("inf")
            uams[uid] = uam

    # --- Initial state validation and speed assignment ---
    T_sep_min = uam_cfg["T_sep_min_s"]
    if uam_cfg["spawn_pattern"] == "uniform":
        _validate_uniform_density(num_uams, num_lanes, corridor, speed_range, T_sep_min)
    _apply_cf_initial_speeds(uams, T_sep_min)

    # --- Metrics collector ---
    metrics = MetricsCollector(cfg)

    # --- Simulation parameters ---
    t_start = cfg["simulation"]["t_start"]
    t_end = cfg["simulation"]["t_end"]
    dt = cfg["simulation"]["dt"]
    record_interval = cfg["simulation"].get("record_interval", 1)

    traffic_cfg = cfg["traffic"]
    bsm_rate_bps = traffic_cfg["bsm_size_bytes"] * 8 * traffic_cfg["bsm_rate_hz"]
    hotl_rate_bps = traffic_cfg["hotl_rate_bps"]
    hwtl_rate_bps = traffic_cfg["hwtl_rate_bps"]
    rtt_max = traffic_cfg["RTT_max_s"]

    handoff_cfg = cfg["handoff"]
    handoff_delay = handoff_cfg["delay_s"]
    handoff_p_drop = handoff_cfg["p_drop"]

    ms_cfg = cfg["mode_switch"]
    thresholds = cfg["thresholds"]
    ext_load_cfg = cfg.get("external_load", {"enabled": False, "events": []})

    # Propagation delay approximation: speed of light, ~3.3 us/km
    SPEED_OF_LIGHT = 3e8

    step = 0
    t = t_start

    while t <= t_end:
        # ========================================
        # 1. Update UAM positions (car-following)
        # ========================================
        _update_uam_positions(uams, corridors, dt, uam_cfg["T_sep_min_s"])

        # ========================================
        # 2. Mode switching
        # ========================================
        _update_mode_switches(uams, ms_cfg, corridors, dt, t, rng)

        # ========================================
        # 3. Coverage, serving BS assignment, handoff
        # ========================================
        _update_coverage_and_handoff(
            uams, base_stations, corridors, graph,
            handoff_delay, handoff_p_drop, dt, rng
        )

        # ========================================
        # 4. Traffic generation and queuing
        # ========================================
        # Compute external (terrestrial) load active at this time step
        ext_load_per_bs = _compute_external_load(t, ext_load_cfg, base_stations)

        _update_traffic_and_queuing(
            uams, base_stations, graph,
            bsm_rate_bps, hotl_rate_bps, hwtl_rate_bps,
            rtt_max, dt, rng, handoff_p_drop, SPEED_OF_LIGHT,
            ext_load_per_bs
        )

        # ========================================
        # 5. Record KPIs
        # ========================================
        if step % record_interval == 0:
            metrics.record_step(
                t, uams, base_stations, graph, corridors, thresholds,
                ext_load_per_bs=ext_load_per_bs
            )

        t += dt
        step += 1

    # --- Finalize ---
    metrics.finalize(uams, base_stations, thresholds)

    return {
        "config": cfg,
        "metrics": metrics,
        "final_state": {
            "uams": {uid: _uam_snapshot(u) for uid, u in uams.items()},
            "base_stations": {bsid: _bs_snapshot(bs) for bsid, bs in base_stations.items()},
        },
    }


# ============================================================
# Initialization helpers
# ============================================================

def _validate_uniform_density(num_uams, num_lanes, corridor, speed_range, T_sep_min):
    """Raise ValueError if uniform-spaced UAMs exceed the maximum safe corridor density.

    For uniform spawn, UAMs interleave across lanes, so the intra-lane gap is:
        intra_lane_spacing = num_lanes × (L / (N + 1))

    The minimum safe spacing at the slowest design speed is v_min × τ_min.
    If the initial spacing is smaller than this, a follower's initial speed would
    have to be negative to maintain safety — an infeasible initial condition.
    """
    spacing_all = corridor.length_m / (num_uams + 1)
    intra_lane_spacing = num_lanes * spacing_all
    v_min = speed_range[0]
    min_required = v_min * T_sep_min
    if intra_lane_spacing < min_required:
        N_max = max(0, int(num_lanes * corridor.length_m / min_required) - 1)
        raise ValueError(
            f"Too many UAMs for corridor '{corridor.id}': "
            f"intra-lane spacing {intra_lane_spacing:.0f} m < "
            f"v_min × τ_min = {v_min:.0f} × {T_sep_min:.1f} = {min_required:.0f} m. "
            f"Reduce num_uams to ≤ {N_max}."
        )


def _apply_cf_initial_speeds(uams, T_sep_min):
    """Adjust initial UAM speeds to satisfy car-following constraints.

    For each lane, processes UAMs from leader (highest position) to last
    follower and caps each follower's speed at gap / τ_min so that the
    initial state satisfies the car-following law: v_i ≤ Δx_i / τ_min.
    The leader retains its randomly drawn free-flow speed.
    """
    lane_groups = {}
    for u in uams.values():
        lane_groups.setdefault((u.corridor_id, u.lane), []).append(u)
    for group in lane_groups.values():
        group.sort(key=lambda u: u.position_m, reverse=True)  # leader first
        for i in range(1, len(group)):
            gap = group[i - 1].position_m - group[i].position_m
            safe_speed = gap / max(T_sep_min, 1e-6)
            if group[i].velocity_mps > safe_speed:
                group[i].velocity_mps = safe_speed


# ============================================================
# Internal step functions
# ============================================================

def _update_uam_positions(uams, corridors, dt, T_sep_min):
    """Move UAMs forward with simple car-following."""
    # Group by corridor and lane, sorted by position
    lane_groups = {}
    for u in uams.values():
        if not u.active or u.arrived:
            continue
        key = (u.corridor_id, u.lane)
        lane_groups.setdefault(key, []).append(u)

    for key, group in lane_groups.items():
        corridor = corridors[key[0]]
        # Sort by position descending (leader first)
        group.sort(key=lambda u: u.position_m, reverse=True)

        for i, uam in enumerate(group):
            if i == 0:
                # Leader: no car ahead, free flow
                uam.position_m += uam.velocity_mps * dt
            else:
                leader = group[i - 1]
                gap = leader.position_m - uam.position_m
                safe_gap = uam.velocity_mps * T_sep_min

                if gap < safe_gap:
                    # Slow down to maintain safe separation
                    desired_v = max(gap / max(T_sep_min, 0.01), 0.0)
                    uam.velocity_mps = max(desired_v, 0.0)

                # Hard collision guard: follower cannot reach or pass the leader's
                # already-updated position (leader was processed earlier in this loop)
                max_v_nocollision = max(0.0, (leader.position_m - uam.position_m) / dt)
                uam.velocity_mps = min(uam.velocity_mps, max_v_nocollision)

                uam.position_m += uam.velocity_mps * dt

            # One-way travel: mark as arrived at destination hub (SJ)
            if uam.position_m >= corridor.length_m:
                uam.position_m = corridor.length_m
                uam.arrived = True


def _update_mode_switches(uams, ms_cfg, corridors, dt, t, rng):
    """Handle HOTL <-> HWTL mode transitions."""
    model = ms_cfg["model"]
    max_concurrent = ms_cfg.get("max_concurrent_hwtl")

    # Count current HWTL
    current_hwtl = sum(1 for u in uams.values() if u.active and u.mode == Mode.HWTL)

    for uam in uams.values():
        if not uam.active or uam.arrived:
            continue

        if uam.mode == Mode.HWTL:
            # Check if HWTL episode ends
            uam.hwtl_remaining_s -= dt
            if uam.hwtl_remaining_s <= 0:
                uam.mode = Mode.HOTL
                uam.hwtl_remaining_s = 0.0
                current_hwtl -= 1
                # Reset switch timer
                if model == "poisson" and ms_cfg["lambda_per_hour"] > 0:
                    lam = ms_cfg["lambda_per_hour"] / 3600.0
                    uam.mode_switch_timer = rng.expovariate(lam)
            continue

        # HOTL mode: check for switch triggers
        if model == "poisson":
            uam.mode_switch_timer -= dt
            if uam.mode_switch_timer <= 0:
                # Check concurrent limit
                if max_concurrent is not None and current_hwtl >= max_concurrent:
                    # Defer: try again next step
                    uam.mode_switch_timer = dt
                    continue
                uam.mode = Mode.HWTL
                uam.hwtl_remaining_s = rng.expovariate(1.0 / ms_cfg["mean_hwtl_duration_s"])
                current_hwtl += 1
                # Timer will be reset when switching back to HOTL

        elif model == "zone":
            corridor = corridors.get(uam.corridor_id)
            if corridor is None:
                continue
            for zone in ms_cfg.get("hot_zones", []):
                if zone["corridor_id"] != uam.corridor_id:
                    continue
                if zone["start_m"] <= uam.position_m <= zone["end_m"]:
                    if rng.random() < zone["switch_prob"] * dt:
                        if max_concurrent is not None and current_hwtl >= max_concurrent:
                            continue
                        uam.mode = Mode.HWTL
                        uam.hwtl_remaining_s = rng.expovariate(
                            1.0 / ms_cfg["mean_hwtl_duration_s"]
                        )
                        current_hwtl += 1
                        break


def _update_coverage_and_handoff(uams, base_stations, corridors, graph,
                                  handoff_delay, handoff_p_drop, dt, rng):
    """Determine coverage, assign serving BS, handle handoffs."""
    for uam in uams.values():
        if not uam.active:
            continue
        if uam.arrived:
            # Remove stale graph edges for UAMs that reached the destination
            if uam.serving_bs_id:
                graph.remove_edge(uam.id, uam.serving_bs_id)
                graph.remove_edge(uam.serving_bs_id, uam.id)
                uam.serving_bs_id = None
            continue

        corridor = corridors[uam.corridor_id]

        # Find all BS within coverage
        candidates = []
        for bs_id, bs in base_stations.items():
            dist = bs.distance_to(uam.position_m, corridor.altitude_m)
            quality = bs.coverage_quality(dist)
            if quality != "none":
                candidates.append((bs_id, dist, quality))

        if not candidates:
            # No coverage: disconnect
            if uam.serving_bs_id:
                graph.remove_edge(uam.id, uam.serving_bs_id)
                graph.remove_edge(uam.serving_bs_id, uam.id)
            uam.serving_bs_id = None
            uam.in_handoff = False
            continue

        # Sort by distance (nearest = strongest signal proxy)
        candidates.sort(key=lambda c: c[1])
        best_bs_id = candidates[0][0]
        best_quality = candidates[0][2]

        # Handle handoff timer
        if uam.in_handoff:
            uam.handoff_timer -= dt
            if uam.handoff_timer <= 0:
                uam.in_handoff = False
                uam.handoff_timer = 0.0
            continue

        prev_bs = uam.serving_bs_id

        # Hysteresis: only handoff if new BS is significantly closer
        if prev_bs and prev_bs != best_bs_id:
            prev_dist = base_stations[prev_bs].distance_to(
                uam.position_m, corridor.altitude_m
            )
            prev_quality = base_stations[prev_bs].coverage_quality(prev_dist)
            # Handoff if current BS lost coverage or new BS is 20% closer
            if prev_quality != "none" and candidates[0][1] > prev_dist * 0.8:
                best_bs_id = prev_bs
                best_quality = prev_quality

        if prev_bs != best_bs_id:
            # Trigger handoff
            uam.in_handoff = True
            uam.handoff_timer = handoff_delay
            # Remove old link
            if prev_bs:
                graph.remove_edge(uam.id, prev_bs)
                graph.remove_edge(prev_bs, uam.id)

        uam.serving_bs_id = best_bs_id

        # Update graph edges
        graph.add_node(uam.id, "uam", mode=uam.mode.value,
                       position=uam.position_m, lane=uam.lane)
        graph.add_edge(uam.id, best_bs_id, quality=best_quality)
        graph.add_edge(best_bs_id, uam.id, quality=best_quality)


def _compute_external_load(t, ext_load_cfg, base_stations):
    """Return dict {bs_id: extra_bps} for active external load events at time t."""
    result = {bs_id: 0.0 for bs_id in base_stations}
    if not ext_load_cfg.get("enabled", False):
        return result
    for event in ext_load_cfg.get("events", []):
        if event["t_start"] <= t <= event["t_end"]:
            target = event.get("bs_ids", "all")
            load = event.get("load_bps", 0)
            for bs_id in base_stations:
                if target == "all" or bs_id in target:
                    result[bs_id] = result.get(bs_id, 0) + load
    return result


def _update_traffic_and_queuing(uams, base_stations, graph,
                                 bsm_rate_bps, hotl_rate_bps, hwtl_rate_bps,
                                 rtt_max, dt, rng, handoff_p_drop,
                                 speed_of_light, ext_load_per_bs=None):
    """Compute traffic load, queuing delays, message drops.

    ext_load_per_bs: dict {bs_id: additional_bps} representing non-UAM
    terrestrial users sharing the same 5G infrastructure.
    """
    if ext_load_per_bs is None:
        ext_load_per_bs = {}

    for bs in base_stations.values():
        bs.reset_step()

    for uam in uams.values():
        if not uam.active or uam.arrived or not uam.serving_bs_id:
            continue
        bs = base_stations.get(uam.serving_bs_id)
        if bs is None:
            continue

        bs.connected_uams.append(uam.id)

        if uam.mode == Mode.HWTL:
            uam_traffic = bsm_rate_bps + hwtl_rate_bps
        else:
            uam_traffic = bsm_rate_bps + hotl_rate_bps

        bs.arrival_rate_bps += uam_traffic

        bsm_msgs = max(1, int(10 * dt))
        control_msgs = max(1, int(dt * 10))
        total_msgs = bsm_msgs + control_msgs
        bs.total_msgs_arrived += total_msgs

        if uam.in_handoff:
            dropped = sum(1 for _ in range(total_msgs) if rng.random() < handoff_p_drop)
            bs.msgs_dropped += dropped
            bs.msgs_processed += total_msgs - dropped
        else:
            bs.msgs_processed += total_msgs

    # Apply external (non-UAM) load — adds to bandwidth utilisation but
    # not to the UAM message queue (terrestrial users have separate queues
    # in practice; here we model the bandwidth competition effect).
    for bs_id, bs in base_stations.items():
        ext = ext_load_per_bs.get(bs_id, 0)
        bs.arrival_rate_bps += ext

    for bs_id, bs in base_stations.items():
        bs.compute_queue_delay()
        if bs.total_msgs_arrived > bs.buffer_capacity_msgs:
            overflow = bs.total_msgs_arrived - bs.buffer_capacity_msgs
            bs.msgs_dropped += overflow
            bs.msgs_processed = max(0, bs.msgs_processed - overflow)
            bs.buffer_occupancy = bs.buffer_capacity_msgs
        else:
            bs.buffer_occupancy = bs.total_msgs_arrived

    for uam in uams.values():
        if not uam.active or uam.arrived or not uam.serving_bs_id:
            continue
        bs = base_stations.get(uam.serving_bs_id)
        if bs is None:
            continue

        dx = bs.position_x - uam.position_m
        dy = bs.position_y
        dz = 300  # corridor altitude
        dist = math.sqrt(dx * dx + dy * dy + dz * dz)

        prop_delay = dist / speed_of_light
        backhaul_delay = 0.01
        rtt = 2 * (prop_delay + bs.queue_delay_s + backhaul_delay)

        if uam.in_handoff:
            rtt += 0.1

        edge_key = (uam.id, uam.serving_bs_id)
        if edge_key in graph.edges:
            graph.edges[edge_key]["rtt"] = rtt
            graph.edges[edge_key]["rtt_ok"] = rtt <= rtt_max
        edge_key_rev = (uam.serving_bs_id, uam.id)
        if edge_key_rev in graph.edges:
            graph.edges[edge_key_rev]["rtt"] = rtt
            graph.edges[edge_key_rev]["rtt_ok"] = rtt <= rtt_max


def _uam_snapshot(uam):
    return {
        "id": uam.id,
        "position_m": uam.position_m,
        "velocity_mps": uam.velocity_mps,
        "mode": uam.mode.value,
        "serving_bs": uam.serving_bs_id,
        "lane": uam.lane,
        "active": uam.active,
    }


def _bs_snapshot(bs):
    return {
        "id": bs.id,
        "load_factor": bs.load_factor,
        "queue_delay_s": bs.queue_delay_s,
        "connected_uams": list(bs.connected_uams),
        "msgs_dropped": bs.msgs_dropped,
    }
