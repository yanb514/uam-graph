"""
Core data models for UAM corridor simulation.

Classes:
  Corridor  - 1D flight corridor with lane structure
  Hub       - Origin/destination vertiport
  UAM       - Individual air vehicle with position, velocity, mode state
  BaseStation - Cellular base station with coverage and queuing
  CommGraph - Dynamic communication graph (adjacency-based)
"""

import math
import random
from enum import Enum


class Mode(Enum):
    HOTL = "HOTL"   # Human-over-the-loop (supervisory, low bandwidth)
    HWTL = "HWTL"   # Human-within-the-loop (remote piloting, high bandwidth)


class Corridor:
    __slots__ = ("id", "length_m", "altitude_m", "height_m", "num_lanes")

    def __init__(self, cfg):
        self.id = cfg["id"]
        self.length_m = cfg["length_m"]
        self.altitude_m = cfg["altitude_m"]
        self.height_m = cfg.get("height_m", 33)
        self.num_lanes = cfg.get("num_lanes", 1)


class Hub:
    __slots__ = ("id", "corridor_id", "position_m")

    def __init__(self, cfg):
        self.id = cfg["id"]
        self.corridor_id = cfg["corridor_id"]
        self.position_m = cfg["position_m"]


class UAM:
    """Individual UAM vehicle state."""

    __slots__ = (
        "id", "corridor_id", "lane", "position_m", "velocity_mps",
        "mode", "serving_bs_id", "in_handoff", "handoff_timer",
        "active", "mode_switch_timer", "hwtl_remaining_s",
        "spawned_at", "arrived",
    )

    def __init__(self, uam_id, corridor_id, lane, position_m, velocity_mps):
        self.id = uam_id
        self.corridor_id = corridor_id
        self.lane = lane
        self.position_m = position_m
        self.velocity_mps = velocity_mps
        self.mode = Mode.HOTL
        self.serving_bs_id = None
        self.in_handoff = False
        self.handoff_timer = 0.0
        self.active = True
        self.mode_switch_timer = 0.0  # time until next potential switch
        self.hwtl_remaining_s = 0.0   # remaining HWTL duration
        self.spawned_at = 0.0
        self.arrived = False

    @property
    def traffic_rate_bps(self):
        """Current total traffic rate in bits/sec (set externally via engine)."""
        # This is a placeholder; the engine computes actual rate
        return 0


class BaseStation:
    """Cellular base station with M/M/1 queuing model."""

    __slots__ = (
        "id", "position_x", "position_y",
        "coverage_good_radius_m", "coverage_degraded_radius_m",
        "capacity_bps", "buffer_capacity_msgs",
        # Runtime state
        "connected_uams", "arrival_rate_bps", "load_factor",
        "queue_delay_s", "buffer_occupancy", "msgs_dropped",
        "msgs_processed", "total_msgs_arrived",
    )

    def __init__(self, cfg):
        self.id = cfg["id"]
        pos = cfg["position"]
        self.position_x = pos[0]
        self.position_y = pos[1]
        self.coverage_good_radius_m = cfg.get("coverage_good_radius_m", 3000)
        self.coverage_degraded_radius_m = cfg.get("coverage_degraded_radius_m", 6000)
        self.capacity_bps = cfg.get("capacity_bps", 100_000_000)
        self.buffer_capacity_msgs = cfg.get("buffer_capacity_msgs", 500)

        # Runtime state (reset per step)
        self.connected_uams = []
        self.arrival_rate_bps = 0.0
        self.load_factor = 0.0
        self.queue_delay_s = 0.0
        self.buffer_occupancy = 0
        self.msgs_dropped = 0
        self.msgs_processed = 0
        self.total_msgs_arrived = 0

    def distance_to(self, uam_position_m, corridor_altitude_m):
        """2D distance from BS to UAM projected position (along corridor + altitude)."""
        dx = self.position_x - uam_position_m
        dy = self.position_y  # UAM is on corridor at y=0 (projected)
        dz = corridor_altitude_m  # altitude difference (BS on ground)
        return math.sqrt(dx * dx + dy * dy + dz * dz)

    def coverage_quality(self, distance_m):
        """Return coverage quality: 'good', 'degraded', or 'none'."""
        if distance_m <= self.coverage_good_radius_m:
            return "good"
        elif distance_m <= self.coverage_degraded_radius_m:
            return "degraded"
        return "none"

    def compute_queue_delay(self):
        """M/M/1 queuing delay approximation.

        latency_queue = L_min / (1 - rho) for rho < 1
        where L_min is a base processing delay.
        """
        L_min = 0.005  # 5ms base processing delay
        if self.capacity_bps <= 0:
            return float("inf")
        rho = self.arrival_rate_bps / self.capacity_bps
        self.load_factor = min(rho, 1.0)
        if rho >= 1.0:
            # Saturated: very high delay
            self.queue_delay_s = 2.0  # cap at 2 seconds
        elif rho > 0:
            self.queue_delay_s = L_min / (1.0 - rho)
        else:
            self.queue_delay_s = L_min
        return self.queue_delay_s

    def reset_step(self):
        """Reset per-step counters."""
        self.connected_uams = []
        self.arrival_rate_bps = 0.0
        self.msgs_dropped = 0
        self.msgs_processed = 0
        self.total_msgs_arrived = 0


class CommGraph:
    """Dynamic communication graph using adjacency dictionaries.

    Nodes: UAM IDs (str), BS IDs (str), "GCS" (ground control)
    Edges: (src, dst) -> attributes dict
    """

    def __init__(self):
        self.nodes = {}   # node_id -> {"type": ..., "attrs": {...}}
        self.edges = {}   # (src, dst) -> {"quality": ..., "rtt": ..., ...}

    def clear(self):
        self.nodes.clear()
        self.edges.clear()

    def add_node(self, node_id, node_type, **attrs):
        self.nodes[node_id] = {"type": node_type, **attrs}

    def add_edge(self, src, dst, **attrs):
        self.edges[(src, dst)] = attrs

    def remove_edge(self, src, dst):
        self.edges.pop((src, dst), None)

    def get_edges_from(self, node_id):
        return {k: v for k, v in self.edges.items() if k[0] == node_id}

    def get_edges_to(self, node_id):
        return {k: v for k, v in self.edges.items() if k[1] == node_id}

    def get_neighbors(self, node_id):
        return [dst for (src, dst) in self.edges if src == node_id]
