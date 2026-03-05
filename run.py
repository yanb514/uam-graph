#!/usr/bin/env python3
"""
UAM Corridor Simulation - Entry Point

Runs four example scenarios:
  1. Baseline: Single-corridor SF-SJ with moderate traffic
  2. High-density: More UAMs stressing BS capacity
  3. Frequent mode switches: High HOTL->HWTL switch rate
  4. Cascade failure: Infrastructure overload via concurrent HWTL + terrestrial surge

Generates individual HTML reports per scenario and one combined comparison report.

Usage:
    python run.py                        # all scenarios
    python run.py --cascade-only         # only the cascade failure scenario
"""

import copy
import os
import sys
import time

from uam_sim.config import default_config, validate_config
from uam_sim.engine import run_simulation
from uam_sim.report import generate_html_report


def make_scenario_baseline():
    """Scenario 1: Baseline moderate traffic."""
    cfg = default_config()
    cfg["scenario_name"] = "Baseline (50 UAMs)"
    cfg["simulation"]["t_end"] = 600.0   # 10 minutes
    cfg["simulation"]["dt"] = 1.0
    cfg["scenario_narrative"] = (
        "Think of this as a normal business day on a future air corridor connecting "
        "San Francisco and San Jose. Air taxis are spaced out evenly, flying at a "
        "comfortable pace. The cell towers along the route handle the trickle of "
        "telemetry traffic the way a mobile network handles a quiet Tuesday morning "
        "— plenty of bandwidth to spare, no queues building up. Aircraft maintain "
        "safe following distances the way cars do on an open highway at low density. "
        "Every safety check passes with comfortable margin. This is what the system "
        "is designed to look like under normal operating conditions."
    )
    return cfg


def make_scenario_high_density():
    """Scenario 2: High-density corridor stressing BS capacity."""
    cfg = default_config()
    cfg["scenario_name"] = "High Density (150 UAMs)"
    cfg["scenario_narrative"] = (
        "Imagine rush hour on the freeway, but in the sky. With three times the "
        "usual number of air taxis sharing the same route, two compounding problems "
        "emerge. First, all aircraft are heading toward the same destination hub near "
        "San Jose — so they naturally bunch up near the end of the corridor, like "
        "passengers crowding an airplane aisle before landing. The single cell tower "
        "serving that area gets flooded with far more status messages than it can "
        "handle; its queue fills up and safety-critical updates start getting "
        "discarded. Second, as aircraft bunch together, the gap ahead of each one "
        "shrinks below the safe braking margin. Either problem alone might be "
        "tolerable; together, they push the corridor into genuinely unsafe territory "
        "— not because the technology broke down, but because more aircraft were "
        "packed into a space designed for fewer."
    )
    cfg["simulation"]["t_end"] = 600.0
    cfg["simulation"]["dt"] = 1.0
    cfg["simulation"]["random_seed"] = 123

    cfg["uams"]["num_uams"] = 150
    cfg["uams"]["speed_mps"] = [35, 55]
    cfg["uams"]["T_sep_min_s"] = 3.0

    # Reduce BS capacity to create congestion
    for bs in cfg["base_stations"]:
        bs["capacity_bps"] = 50_000_000  # 50 Mbps (down from 100)
        bs["buffer_capacity_msgs"] = 300

    cfg["corridors"][0]["num_lanes"] = 2
    return cfg


def make_scenario_frequent_switches():
    """Scenario 3: Frequent HOTL->HWTL switches."""
    cfg = default_config()
    cfg["scenario_name"] = "Frequent Switches (λ=5/hr)"
    cfg["scenario_narrative"] = (
        "In this scenario, pilots take manual control of their aircraft far more "
        "often than usual — roughly once every twelve minutes each, compared to "
        "once every two hours in normal operations. Every time a pilot takes over, "
        "the aircraft switches from a low-bandwidth status ping to a full live video "
        "stream so the pilot can see what the aircraft is seeing. This is like "
        "suddenly switching from sending text messages to video-calling — the data "
        "demand jumps dramatically. Despite this, the corridor handles it fine: the "
        "number of aircraft is modest, and the cell towers were sized with headroom "
        "precisely for these kinds of temporary video bursts. The extra load is "
        "real and visible in the charts, but it stays well within the towers' "
        "capacity. The system demonstrates that occasional human intervention is "
        "not inherently a problem — it just needs infrastructure sized to absorb it."
    )
    cfg["simulation"]["t_end"] = 600.0
    cfg["simulation"]["dt"] = 1.0
    cfg["simulation"]["random_seed"] = 777

    cfg["uams"]["num_uams"] = 80

    # High switch rate
    cfg["mode_switch"]["lambda_per_hour"] = 5.0
    cfg["mode_switch"]["mean_hwtl_duration_s"] = 45

    # Also try zone-based for comparison within the same run:
    # (keeping Poisson model but with high rate)
    return cfg


def make_scenario_cascade_failure():
    """Scenario 4: Cascading BS overload from concurrent HWTL + terrestrial surge.

    Design parameters (from CascadeFailureScenario.docx):
      - 6 base stations at 20 Mbps each (matching reference scenario)
      - 60 UAMs => ~10 UAMs per BS on average
      - High HWTL switch rate (λ=8/hr) + 90 s episode duration
        => expected ~2 concurrent HWTL per BS in steady state
      - External load event at t=120–360 s: +8 Mbps terrestrial surge per BS
        (stadium event model from CascadeFailureScenario.docx §3.5)

    Cascade progression:
      Phase 1  t=0–120s    Pure HOTL: ρ ≈ 3%   (green)
      Phase 2  t=60–120s   HWTL events accumulate: ρ → 63%  (yellow)
      Phase 3  t=120–360s  Terrestrial surge: ρ > 100% on loaded BS  (red/critical)
      Phase 4  t=360–480s  Surge ends; ρ recovers but HWTL still active
      Phase 5  t=480–600s  HWTL episodes expire; full recovery
    """
    corridor_length = 80_000

    # 6 BS spaced ~11.4 km apart, 20 Mbps each (reference scenario capacity)
    num_bs = 6
    bs_spacing = corridor_length / (num_bs + 1)
    base_stations = []
    for i in range(num_bs):
        x = bs_spacing * (i + 1)
        base_stations.append({
            "id": f"BS{i+1:02d}",
            "position": [x, 500.0],
            "coverage_good_radius_m": 5000,    # wider coverage to ensure connectivity
            "coverage_degraded_radius_m": 9000,
            "capacity_bps": 20_000_000,        # 20 Mbps — matches CascadeFailureScenario.docx
            "buffer_capacity_msgs": 500,
        })

    cfg = {
        "scenario_name": "Cascade Failure (BS Overload)",
        "simulation": {
            "t_start": 0.0,
            "t_end": 600.0,
            "dt": 1.0,
            "random_seed": 42,
            "record_interval": 1,
        },
        "corridors": [{
            "id": "SF-SJ",
            "length_m": corridor_length,
            "altitude_m": 300,
            "height_m": 33,
            "num_lanes": 1,
        }],
        "hubs": [
            {"id": "SF", "corridor_id": "SF-SJ", "position_m": 0.0},
            {"id": "SJ", "corridor_id": "SF-SJ", "position_m": float(corridor_length)},
        ],
        "uams": {
            "num_uams": 60,
            "spawn_pattern": "uniform",
            "speed_mps": [40, 55],
            "T_sep_min_s": 5.0,
        },
        "base_stations": base_stations,
        "traffic": {
            "bsm_size_bytes": 300,
            "bsm_rate_hz": 10,
            "hotl_rate_bps": 35_000,
            "hwtl_rate_bps": 6_000_000,
            "RTT_max_s": 0.5,
        },
        # High switch rate + long episodes => concurrent HWTL events build up.
        # At λ=8/hr per UAM with 10 UAMs/BS and 90 s duration:
        #   E[concurrent HWTL/BS] = (8/3600) × 90 × 10 ≈ 2.0
        #   Load from 2 HWTL on a 20 Mbps BS: ~63% (yellow)
        #   With terrestrial surge (+8 Mbps): ~103% (critical/saturated)
        "mode_switch": {
            "model": "poisson",
            "lambda_per_hour": 8.0,
            "mean_hwtl_duration_s": 90,
            "max_concurrent_hwtl": None,
        },
        "handoff": {
            "delay_s": 0.2,
            "p_drop": 0.1,
        },
        "thresholds": {
            "load_warning": 0.6,
            "load_critical": 0.85,
            "sep_time_min_s": 2.0,
            "ttc_min_s": 5.0,
        },
        # Terrestrial surge: stadium event ends at t=120 s, adding 8 Mbps per BS.
        # Matches CascadeFailureScenario.docx §3.5 "Additional Load from Non-UAM Users".
        "external_load": {
            "enabled": True,
            "events": [
                {
                    "t_start": 120.0,
                    "t_end": 360.0,
                    "bs_ids": "all",
                    "load_bps": 8_000_000,
                    "label": "Terrestrial surge (stadium event, +8 Mbps/BS)",
                },
            ],
        },
        "scenario_narrative": (
            "This scenario illustrates how shared infrastructure can collapse in "
            "unexpected ways — not from a single dramatic failure, but from two "
            "ordinary events happening at the wrong time. The air corridor is "
            "humming along with a moderate number of aircraft. Pilots occasionally "
            "take manual control, which briefly turns each aircraft's data link from "
            "a trickle into a full video stream. The cell towers are stressed by "
            "this but holding on — like a coffee shop Wi-Fi that's busy but "
            "functional. Then a nearby stadium lets out. Tens of thousands of "
            "people simultaneously pull out their phones and start sharing videos "
            "and photos. These ground users share the exact same cell towers as "
            "the aircraft overhead. The sudden surge of ground traffic — the digital "
            "equivalent of everyone flushing the toilet at halftime — tips the "
            "already-stressed towers past their breaking point. Queues pile up, "
            "delays balloon from milliseconds to seconds, and pilot commands stop "
            "arriving in time to be acted on. The towers didn't fail because of the "
            "aircraft, and they didn't fail because of the sports fans — they failed "
            "because both groups needed the same resource at the same moment, and "
            "nobody had planned for that collision."
        ),
    }
    return cfg


def _run_one(name, cfg, output_dir, results_list):
    """Run a single scenario, print summary, write report, append to results_list."""
    validate_config(cfg)
    print(f"\n{'='*60}")
    print(f"Running scenario: {cfg['scenario_name']}")
    print(f"  UAMs: {cfg['uams']['num_uams']}")
    print(f"  Duration: {cfg['simulation']['t_end']}s, dt={cfg['simulation']['dt']}s")
    print(f"  Base stations: {len(cfg['base_stations'])}")
    ext = cfg.get("external_load", {})
    if ext.get("enabled"):
        for ev in ext.get("events", []):
            print(f"  External load: {ev['label']} "
                  f"[t={ev['t_start']:.0f}–{ev['t_end']:.0f}s, "
                  f"+{ev['load_bps']/1e6:.0f} Mbps/BS]")
    print(f"{'='*60}")

    t0 = time.time()
    result = run_simulation(cfg)
    elapsed = time.time() - t0

    summary = result["metrics"].summary
    print(f"\n  Completed in {elapsed:.1f}s")
    print(f"  Classification: {summary['classification'].upper()}")
    print(f"  Avg RTT:        {summary['avg_rtt_s']*1000:.1f} ms")
    print(f"  Max RTT:        {summary['max_rtt_s']*1000:.1f} ms")
    print(f"  Drop rate:      {summary['drop_rate']*100:.2f}%")
    print(f"  Mode switches:  {summary['total_mode_switches']}")
    print(f"  Min separation: {summary.get('min_separation_time_s', 'N/A')}")

    # Highlight any BS that reached critical
    for bs_id, info in summary["bs"].items():
        if info["max_load"] > 0.85:
            print(f"  *** {bs_id} reached CRITICAL load: "
                  f"max={info['max_load']*100:.1f}%, "
                  f"time_in_red={info['time_in_red_frac']*100:.1f}%")

    report_path = os.path.join(output_dir, f"report_{name}.html")
    generate_html_report(result, report_path,
                         scenario_name=f"UAM Simulation: {cfg['scenario_name']}")
    print(f"  Report: {report_path}")
    results_list.append(result)


def main():
    cascade_only = "--cascade-only" in sys.argv
    output_dir = os.path.join(os.path.dirname(__file__), "reports")
    os.makedirs(output_dir, exist_ok=True)

    results = []

    if cascade_only:
        _run_one("cascade_failure", make_scenario_cascade_failure(), output_dir, results)
    else:
        all_scenarios = [
            ("baseline",          make_scenario_baseline()),
            ("high_density",      make_scenario_high_density()),
            ("frequent_switches", make_scenario_frequent_switches()),
            ("cascade_failure",   make_scenario_cascade_failure()),
        ]
        for name, cfg in all_scenarios:
            _run_one(name, cfg, output_dir, results)

        comparison_path = os.path.join(output_dir, "report_comparison.html")
        generate_html_report(
            results, comparison_path,
            scenario_name="UAM Corridor Simulation — Scenario Comparison",
        )
        print(f"\nComparison report: {comparison_path}")

    print("\nDone!")


if __name__ == "__main__":
    main()
