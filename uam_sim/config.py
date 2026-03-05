"""
Configuration schema and defaults for UAM corridor simulation.

Provides default_config() for a single SF-SJ corridor scenario
and validate_config() for basic sanity checks.
"""

import copy
import math


def default_config():
    """Return a default configuration dict for the SF-SJ corridor."""

    # SF-SJ corridor: ~80 km
    corridor_length = 80_000  # meters

    # Place base stations every ~5 km along the corridor
    num_bs = 16
    bs_spacing = corridor_length / (num_bs + 1)
    base_stations = []
    for i in range(num_bs):
        x = bs_spacing * (i + 1)
        base_stations.append({
            "id": f"BS{i+1:02d}",
            "position": [x, 500.0],  # 500m lateral offset from corridor
            "coverage_good_radius_m": 3000,
            "coverage_degraded_radius_m": 6000,
            "capacity_bps": 100_000_000,  # 100 Mbps per BS
            "buffer_capacity_msgs": 500,
        })

    return {
        "simulation": {
            "t_start": 0.0,
            "t_end": 600.0,        # 10 minutes for quick prototype runs
            "dt": 1.0,             # 1-second time step
            "random_seed": 42,
            "record_interval": 1,  # record metrics every N steps
        },
        "corridors": [
            {
                "id": "SF-SJ",
                "length_m": corridor_length,
                "altitude_m": 300,
                "height_m": 33,
                "num_lanes": 1,
            }
        ],
        "hubs": [
            {"id": "SF", "corridor_id": "SF-SJ", "position_m": 0.0},
            {"id": "SJ", "corridor_id": "SF-SJ", "position_m": float(corridor_length)},
        ],
        "uams": {
            "num_uams": 50,
            "spawn_pattern": "uniform",  # "uniform", "batch", "poisson"
            "speed_mps": [40, 60],       # [min, max] m/s (~90-135 mph)
            "T_sep_min_s": 5.0,          # minimum safe separation time
        },
        "base_stations": base_stations,
        "traffic": {
            "bsm_size_bytes": 300,
            "bsm_rate_hz": 10,
            "hotl_rate_bps": 35_000,      # 35 kbps HOTL telemetry
            "hwtl_rate_bps": 6_000_000,   # 6 Mbps HWTL video
            "RTT_max_s": 0.5,             # 500 ms max RTT
        },
        "mode_switch": {
            "model": "poisson",           # "poisson" or "zone"
            "lambda_per_hour": 0.5,       # avg switches per UAM per hour
            "mean_hwtl_duration_s": 60,   # avg HWTL episode length
            "max_concurrent_hwtl": None,  # None = no limit
            # Zone-based trigger config (used when model="zone")
            "hot_zones": [
                {"corridor_id": "SF-SJ", "start_m": 0, "end_m": 5000, "switch_prob": 0.3},
                {"corridor_id": "SF-SJ", "start_m": 75000, "end_m": 80000, "switch_prob": 0.3},
            ],
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
        # External (non-UAM terrestrial) load injected onto BS at specific times.
        # Simulates traffic surges from ground users sharing the same 5G infrastructure.
        # See: CascadeFailureScenario.docx §3.5 "Additional Load from Non-UAM Users"
        "external_load": {
            "enabled": False,
            "events": [
                # Example: stadium event surge at t=120-300s
                # {
                #   "t_start": 120.0,
                #   "t_end": 300.0,
                #   "bs_ids": "all",        # "all" or list of BS ID strings
                #   "load_bps": 8_000_000,  # 8 Mbps per BS
                #   "label": "Terrestrial surge (stadium event)",
                # }
            ],
        },
    }


def validate_config(config):
    """Validate configuration dict. Raises ValueError on problems."""
    errors = []

    sim = config.get("simulation", {})
    if sim.get("dt", 0) <= 0:
        errors.append("simulation.dt must be positive")
    if sim.get("t_end", 0) <= sim.get("t_start", 0):
        errors.append("simulation.t_end must be > t_start")

    corridors = config.get("corridors", [])
    if not corridors:
        errors.append("At least one corridor required")
    for c in corridors:
        if c.get("length_m", 0) <= 0:
            errors.append(f"Corridor {c.get('id')}: length_m must be positive")
        if c.get("num_lanes", 0) < 1:
            errors.append(f"Corridor {c.get('id')}: num_lanes must be >= 1")

    uams = config.get("uams", {})
    if uams.get("num_uams", 0) < 1:
        errors.append("uams.num_uams must be >= 1")
    speed = uams.get("speed_mps", [0, 0])
    if isinstance(speed, list) and len(speed) == 2:
        if speed[0] <= 0 or speed[1] < speed[0]:
            errors.append("uams.speed_mps must be [v_min, v_max] with 0 < v_min <= v_max")

    bs_list = config.get("base_stations", [])
    if not bs_list:
        errors.append("At least one base station required")
    for bs in bs_list:
        if bs.get("capacity_bps", 0) <= 0:
            errors.append(f"BS {bs.get('id')}: capacity_bps must be positive")

    traffic = config.get("traffic", {})
    if traffic.get("hwtl_rate_bps", 0) <= traffic.get("hotl_rate_bps", 0):
        errors.append("traffic.hwtl_rate_bps should be > hotl_rate_bps")

    if errors:
        raise ValueError("Configuration errors:\n" + "\n".join(f"  - {e}" for e in errors))

    return True
