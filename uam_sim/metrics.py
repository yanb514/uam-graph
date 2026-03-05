"""
Metrics collection and KPI computation for UAM corridor simulation.

Records time-series data at each simulation step and computes
aggregate statistics at the end of the run.
"""

import math
from uam_sim.models import Mode


class MetricsCollector:
    """Collects and stores all simulation KPIs."""

    def __init__(self, config):
        self.config = config

        # Time-series data (one entry per recorded step)
        self.time = []

        # --- Transportation KPIs ---
        self.num_uams_active = []
        self.num_uams_hwtl = []
        self.min_separation_time = []
        self.mean_separation_time = []
        self.separation_violations = []  # count per step

        # --- Communication KPIs ---
        # Per-step aggregated
        self.mean_rtt = []
        self.max_rtt = []
        self.p95_rtt = []
        self.total_msgs_dropped = []
        self.total_msgs_processed = []

        # Per-BS time series: bs_id -> list of per-step values
        self.bs_load_factor = {}
        self.bs_queue_delay = {}
        self.bs_msgs_dropped = {}
        self.bs_connected_count = {}

        # Per-step handoff counts
        self.handoff_count = []
        self.no_coverage_count = []

        # Mode switch events
        self.mode_switch_events = []  # list of (time, uam_id, from_mode, to_mode)

        # Per-UAM RTT samples (for histograms): collected at record steps
        self.rtt_samples = []
        self.separation_samples = []

        # Spatial snapshots (subsampled for visualization)
        self.spatial_snapshots = []
        self._snapshot_interval = max(1, int(10.0 / config["simulation"]["dt"]))

        # Track previous mode for switch detection
        self._prev_modes = {}

        # Per-BS external load series: bs_id -> list of per-step values (bps)
        self.bs_external_load = {}

        # Initialize per-BS series
        for bs_cfg in config["base_stations"]:
            bs_id = bs_cfg["id"]
            self.bs_load_factor[bs_id] = []
            self.bs_queue_delay[bs_id] = []
            self.bs_msgs_dropped[bs_id] = []
            self.bs_connected_count[bs_id] = []
            self.bs_external_load[bs_id] = []

    def record_step(self, t, uams, base_stations, graph, corridors, thresholds,
                    ext_load_per_bs=None):
        """Record KPIs for one simulation step."""
        self.time.append(t)

        # --- Transportation metrics ---
        active_uams = [u for u in uams.values() if u.active and not u.arrived]
        self.num_uams_active.append(len(active_uams))
        self.num_uams_hwtl.append(
            sum(1 for u in active_uams if u.mode == Mode.HWTL)
        )

        # Separation times
        sep_times = self._compute_separation_times(active_uams, corridors)
        if sep_times:
            self.min_separation_time.append(min(sep_times))
            self.mean_separation_time.append(sum(sep_times) / len(sep_times))
            violations = sum(1 for s in sep_times if s < thresholds["sep_time_min_s"])
            self.separation_violations.append(violations)
            self.separation_samples.extend(sep_times)
        else:
            self.min_separation_time.append(float("inf"))
            self.mean_separation_time.append(float("inf"))
            self.separation_violations.append(0)

        # --- Communication metrics ---
        step_rtts = []
        step_dropped = 0
        step_processed = 0
        handoffs = 0
        no_coverage = 0

        for uam in active_uams:
            if uam.serving_bs_id is None:
                no_coverage += 1
                continue
            edge_key = (uam.id, uam.serving_bs_id)
            edge = graph.edges.get(edge_key, {})
            rtt = edge.get("rtt", 0)
            if rtt > 0:
                step_rtts.append(rtt)
            if uam.in_handoff:
                handoffs += 1

        for bs in base_stations.values():
            step_dropped += bs.msgs_dropped
            step_processed += bs.msgs_processed

        self.total_msgs_dropped.append(step_dropped)
        self.total_msgs_processed.append(step_processed)
        self.handoff_count.append(handoffs)
        self.no_coverage_count.append(no_coverage)

        if step_rtts:
            step_rtts_sorted = sorted(step_rtts)
            self.mean_rtt.append(sum(step_rtts) / len(step_rtts))
            self.max_rtt.append(max(step_rtts))
            idx_95 = min(int(len(step_rtts_sorted) * 0.95), len(step_rtts_sorted) - 1)
            self.p95_rtt.append(step_rtts_sorted[idx_95])
            self.rtt_samples.extend(step_rtts)
        else:
            self.mean_rtt.append(0)
            self.max_rtt.append(0)
            self.p95_rtt.append(0)

        # Per-BS metrics
        if ext_load_per_bs is None:
            ext_load_per_bs = {}
        for bs_id, bs in base_stations.items():
            self.bs_load_factor[bs_id].append(bs.load_factor)
            self.bs_queue_delay[bs_id].append(bs.queue_delay_s)
            self.bs_msgs_dropped[bs_id].append(bs.msgs_dropped)
            self.bs_connected_count[bs_id].append(len(bs.connected_uams))
            self.bs_external_load[bs_id].append(ext_load_per_bs.get(bs_id, 0))

        # Mode switch detection
        for uam in active_uams:
            prev = self._prev_modes.get(uam.id)
            if prev is not None and prev != uam.mode:
                self.mode_switch_events.append(
                    (t, uam.id, prev.value, uam.mode.value)
                )
            self._prev_modes[uam.id] = uam.mode

        # Spatial snapshot (subsampled)
        step_idx = len(self.time) - 1
        if step_idx % self._snapshot_interval == 0:
            snapshot = {
                "t": t,
                "uams": [],
                "bs_loads": {},
            }
            for uam in active_uams:
                snapshot["uams"].append({
                    "id": uam.id,
                    "pos": round(uam.position_m, 1),
                    "vel": round(uam.velocity_mps, 2),
                    "lane": uam.lane,
                    "mode": uam.mode.value,
                    "bs": uam.serving_bs_id,
                    "handoff": uam.in_handoff,
                })
            for bs_id, bs in base_stations.items():
                snapshot["bs_loads"][bs_id] = round(bs.load_factor, 4)
            self.spatial_snapshots.append(snapshot)

    def _compute_separation_times(self, active_uams, corridors):
        """Compute separation times between consecutive UAMs in each lane."""
        lane_groups = {}
        for u in active_uams:
            key = (u.corridor_id, u.lane)
            lane_groups.setdefault(key, []).append(u)

        sep_times = []
        for key, group in lane_groups.items():
            if len(group) < 2:
                continue
            group.sort(key=lambda u: u.position_m)
            for i in range(1, len(group)):
                leader = group[i]
                follower = group[i - 1]
                gap = leader.position_m - follower.position_m
                if follower.velocity_mps > 0:
                    t_sep = gap / follower.velocity_mps
                    sep_times.append(t_sep)

        return sep_times

    def finalize(self, uams, base_stations, thresholds):
        """Compute aggregate summary statistics."""
        self.summary = {}

        # Transportation
        if self.min_separation_time:
            valid_seps = [s for s in self.min_separation_time if s != float("inf")]
            self.summary["min_separation_time_s"] = min(valid_seps) if valid_seps else float("inf")
            self.summary["mean_min_separation_time_s"] = (
                sum(valid_seps) / len(valid_seps) if valid_seps else float("inf")
            )
        self.summary["total_separation_violations"] = sum(self.separation_violations)
        self.summary["total_mode_switches"] = len(self.mode_switch_events)

        # Communication
        if self.mean_rtt:
            valid_rtts = [r for r in self.mean_rtt if r > 0]
            self.summary["avg_rtt_s"] = sum(valid_rtts) / len(valid_rtts) if valid_rtts else 0
            self.summary["max_rtt_s"] = max(self.max_rtt) if self.max_rtt else 0

        total_dropped = sum(self.total_msgs_dropped)
        total_processed = sum(self.total_msgs_processed)
        total_all = total_dropped + total_processed
        self.summary["total_msgs_dropped"] = total_dropped
        self.summary["total_msgs_processed"] = total_processed
        self.summary["drop_rate"] = total_dropped / max(total_all, 1)

        # Per-BS summary
        self.summary["bs"] = {}
        for bs_id in self.bs_load_factor:
            loads = self.bs_load_factor[bs_id]
            drops = self.bs_msgs_dropped[bs_id]
            if loads:
                avg_load = sum(loads) / len(loads)
                max_load = max(loads)
                time_in_red = sum(
                    1 for l in loads if l > thresholds["load_critical"]
                ) / max(len(loads), 1)
            else:
                avg_load = max_load = time_in_red = 0

            self.summary["bs"][bs_id] = {
                "avg_load": round(avg_load, 4),
                "max_load": round(max_load, 4),
                "total_drops": sum(drops),
                "time_in_red_frac": round(time_in_red, 4),
            }

        # Overall classification
        rtt_violated = self.summary.get("max_rtt_s", 0) > thresholds.get(
            "sep_time_min_s", 999
        )
        sep_violated = self.summary.get("min_separation_time_s", 999) < thresholds[
            "sep_time_min_s"
        ]
        high_drop = self.summary["drop_rate"] > 0.05

        if sep_violated or (self.summary.get("max_rtt_s", 0) > thresholds.get("sep_time_min_s", 0.5) * 2):
            self.summary["classification"] = "unsafe"
        elif high_drop or any(
            v["time_in_red_frac"] > 0.1 for v in self.summary["bs"].values()
        ):
            self.summary["classification"] = "degraded"
        else:
            self.summary["classification"] = "normal"

    def to_dict(self):
        """Export all metrics as a plain dict (for JSON serialization or report)."""
        return {
            "time": self.time,
            "num_uams_active": self.num_uams_active,
            "num_uams_hwtl": self.num_uams_hwtl,
            "min_separation_time": self.min_separation_time,
            "mean_separation_time": self.mean_separation_time,
            "separation_violations": self.separation_violations,
            "mean_rtt": self.mean_rtt,
            "max_rtt": self.max_rtt,
            "p95_rtt": self.p95_rtt,
            "total_msgs_dropped": self.total_msgs_dropped,
            "total_msgs_processed": self.total_msgs_processed,
            "handoff_count": self.handoff_count,
            "no_coverage_count": self.no_coverage_count,
            "mode_switch_events": self.mode_switch_events,
            "bs_load_factor": self.bs_load_factor,
            "bs_queue_delay": self.bs_queue_delay,
            "bs_msgs_dropped": self.bs_msgs_dropped,
            "bs_connected_count": self.bs_connected_count,
            "bs_external_load": self.bs_external_load,
            "spatial_snapshots": self.spatial_snapshots,
            "rtt_samples": self.rtt_samples[:10000],  # cap for report size
            "separation_samples": self.separation_samples[:10000],
            "summary": getattr(self, "summary", {}),
        }
