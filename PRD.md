# UAM Corridor Communication–Transportation Simulator  
**Product Requirements Document (PRD)**  

---

## 1. Overview

### 1.1 Purpose

Define detailed requirements for a simulation model that jointly captures:

- Urban Air Mobility (UAM) **corridor traffic dynamics** (vehicles, lanes, safety)
- **Communication network behavior** (cellular base stations, coverage, queues, failures)
- **Mode switching** between human-over-the-loop (HOTL) and human-within-the-loop (HWTL)

The goal is to implement:

- **Core engine:** Python-only implementation of graph-based system dynamics
- **Output visualization:** A **single, self-contained HTML file** (no external JS/CSS/CDN or runtime dependencies) with interactive plots and controls, suitable for use on a code-execution platform.

Toyota/TEMA will use this tool to explore capacity, safety, and deployment questions for future UAM systems.

---

## 2. Scope

### 2.1 In-Scope

- Graph-based simulator of:
  - UAM vehicles, corridors, lanes, and movement rules
  - Cellular/base-station coverage, handoff, and load
  - Communication traffic (BSMs, control, and HOTL/HWTL traffic)
  - M/M/1-based queuing and latency at infrastructure nodes
  - Abstracted mode-switch triggers and their impact on network load
- Scenario configuration and batch runs
- Computation of key performance indicators (KPIs)
- Generation of an **interactive single HTML** report per run:
  - Input parameters summary
  - Plots (time series, histograms, spatial diagrams)
  - Ability to toggle scenarios/metrics and inspect details

### 2.2 Out-of-Scope (for this phase)

- High-fidelity RF/channel modeling (fading, multipath, detailed PHY)
- Full 3D aerodynamics or trajectory optimization
- Real-time hardware or network integration
- Multi-file web apps, servers, or external JS frameworks

---

## 3. Users and Use Cases

### 3.1 Primary Users

- Toyota/TEMA researchers (communications and transportation)
- Academic collaborators (e.g., ASU)

### 3.2 Key Use Cases

1. **Corridor capacity study**
   - “Given a corridor geometry and base-station layout, how many UAMs can we safely support?”

2. **Mode-switch robustness**
   - “How often can HOTL→HWTL switches occur before network or safety metrics become unacceptable?”

3. **Infrastructure planning**
   - “For a given UAM density, what base-station density/capacity is required?”

4. **Sensitivity to assumptions**
   - “Which parameters (coverage radius, buffer size, BSM rate, lane count, etc.) dominate failures?”

---

## 4. High-Level Functional Requirements

### 4.1 System Architecture

1. **Core engine in Python**
   - No non-standard language dependencies.
   - May use standard scientific Python stack (e.g., `numpy`, `scipy`) if available on platform; if uncertain, design so basic mode works with Python standard library only.

2. **Graph-based system representation**
   - Use an internal graph structure (e.g., adjacency lists / dictionaries) to represent:
     - Nodes: UAMs, base stations (BS), ground control node(s)
     - Edges: communication links with time-varying attributes

3. **Simulation scheduler**
   - Discrete-time simulation (e.g., fixed time step Δt, configurable) or event-driven with a global clock.
   - At each step:
     - Update UAM positions and corridor state.
     - Re-compute coverage, handoffs, and graph connectivity.
     - Update traffic generation, queues, and link metrics.
     - Record KPIs.

4. **Scenario configuration**
   - Read a configuration object (e.g., Python dict or JSON-like) describing:
     - Corridor geometry and lanes
     - UAM population and behavior
     - Base-station layout
     - Communication parameters
     - Mode-switch parameters
     - Simulation time, step size
   - Ability to specify multiple scenarios and run them sequentially in one Python session.

5. **Result collection**
   - For each scenario, store:
     - Time series of KPIs
     - Per-node and per-link statistics
     - Aggregated metrics at the end of the run
   - Provide a well-defined, documented Python data structure for programmatic access.

6. **HTML visualization generator**
   - A Python function that takes the simulation result object(s) and writes a **single HTML file** that:
     - Embeds all scripts/styles inline (no external references).
     - Provides interactive plots using pure inline JavaScript and SVG/Canvas.
     - Allows toggling metrics, hovering for values, and switching scenarios.

---

## 5. Detailed Modeling Requirements

### 5.1 Transportation / Corridor Model

#### 5.1.1 Corridor Geometry

- Represent one or more **corridors**:
  - Each corridor:
    - `id`
    - `length_m` (e.g., distance between hubs)
    - `altitude_m` (nominal flight altitude)
    - `height_m` (default ~30–33 m for vertical thickness)
    - `num_lanes` (start with 1; allow up to at least 3)
- Corridors are 1D lines parameterized by distance `s ∈ [0, length]` plus lane index.

#### 5.1.2 Hubs

- Define **hubs** (e.g., airports, vertiports) as:
  - Nodes at the ends of corridors.
  - May serve as origin/destination for UAMs.

#### 5.1.3 UAM Dynamics

- Each UAM has:
  - `id`
  - Assigned corridor and lane
  - Position along corridor: `s(t)` (distance from origin)
  - Velocity: `v(t)` (m/s), bounded in `[v_min, v_max]`
  - Mode: HOTL or HWTL (binary state)
- Movement rules:
  - UAMs move forward along the corridor with velocity `v(t)`.
  - Simple car-like following rules:
    - Maintain minimum **separation time** `T_sep_min` from vehicle ahead (e.g., 2–10 seconds, configurable).
    - Optionally support simple lane changes (for future phases; start with single lane or fixed lanes).

#### 5.1.4 Safety Metrics Computation

- At each time step:
  - Compute **separation time** between each UAM and the one ahead in the same lane:  
    `T_sep = (s_lead - s_follow) / v_follow` (handle edge cases).
  - Compute **time-to-conflict** approximations for closely spaced pairs.
- Store:
  - Minimum separation time over the corridor per step.
  - Distribution of separation times over simulation.
  - Flags when separation/time-to-conflict breaches thresholds.

---

### 5.2 Communication / Network Model

#### 5.2.1 Nodes

- **UAM nodes**:
  - Each has:
    - Position in 2D (projected along corridor) and altitude.
    - Communication demand characteristics:
      - BSM-like safety/control messages.
      - Optional high-rate stream in HWTL (e.g., video/telematics).
- **Base-station (BS) nodes**:
  - Each BS:
    - Spatial coordinates (x, y, optional z)
    - Coverage parameters:
      - `coverage_good_radius_m` (e.g., ~1000 m)
      - `coverage_degraded_radius_m` (e.g., ~3000 m)
    - Capacity parameters:
      - Max processing rate (messages/s or bits/s)
      - Queue capacity (messages)
      - Buffer capacity (messages)
- **Ground control / core node**:
  - Abstracted as having ample capacity; no bottleneck in first phase.
  - Can be represented as a single node with unconstrained throughput.

#### 5.2.2 Coverage and Link Creation

- For each UAM at each time step:
  - Determine set of BS within coverage radii:
    - `d <= coverage_good_radius` → “good coverage”
    - `coverage_good_radius < d <= coverage_degraded_radius` → “degraded coverage”
    - `d > coverage_degraded_radius` → “no coverage”
  - Assign a **serving BS** based on:
    - Strongest signal proxy (e.g., nearest BS), and/or
    - Hysteresis to avoid ping-pong handoff.
- Construct edges:
  - UAM–BS link if in coverage.
  - BS–ground link (assumed always available and high-capacity for now).

#### 5.2.3 Handoffs

- When a UAM’s serving BS changes:
  - Trigger a **handoff event** with:
    - `handoff_delay_s` (configurable, may be deterministic or random)
    - During the delay:
      - Mark link as “in handoff” state.
      - Apply message drop probability `p_drop_handoff` or reduced capacity.
- Record:
  - Number of handoffs per UAM and per BS.
  - Fraction of messages lost during handoffs.

#### 5.2.4 Traffic Generation

- Each UAM generates traffic per time step:
  - **BSM-like messages:**
    - Size: default 300 bytes.
    - Rate: default 10 Hz.
    - Effective data rate: ~3 Kbps per UAM (configurable).
  - **HOTL/HWTL mode-specific traffic:**
    - HOTL mode:
      - Low-rate control/telemetry traffic (e.g., O(10) Kbps total; configurable).
    - HWTL mode:
      - High-rate video/data stream (e.g., 6 Mbps total; configurable).
  - Total offered load from a UAM is a function of mode and BSM parameters.

#### 5.2.5 Queuing and Latency

- At each BS:
  - Maintain an **M/M/1-style queue** abstraction:
    - Arrival rate λ from all attached UAMs (based on generated traffic).
    - Service rate μ corresponding to BS capacity.
  - Approximate **queueing delay** and **latency**:
    - Use M/M/1 formula or discrete approximations:
      - `delay_q = f(λ, μ)` that grows sharply as ρ = λ/μ → 1.
  - Model **buffering**:
    - If instantaneous arrivals exceed service capacity:
      - Place messages in a finite buffer (capacity B).
      - If buffer full, mark messages as dropped.
- Compute per UAM link:
  - Round-trip time (RTT) = propagation delay + queueing delay.
  - Mark if RTT exceeds configured maximum `RTT_max`.

#### 5.2.6 Load Metrics

- For each BS at each step:
  - **Load factor ρ** = λ/μ.
  - **Channel busy ratio** ~ fraction of time BS is busy (can equate to ρ or refine).
  - Flag status:
    - `0 <= ρ <= warning_threshold` (e.g., 0.6) → green.
    - `warning_threshold < ρ <= critical_threshold` (e.g., 0.85) → yellow.
    - `ρ > critical_threshold` → red (degraded).

---

### 5.3 Mode Switching Model (HOTL ↔ HWTL)

#### 5.3.1 State

- Each UAM has mode ∈ {HOTL, HWTL}.

#### 5.3.2 Triggers (Configurable Models)

Support at least two trigger models (selectable per run):

1. **Poisson / stochastic triggers**
   - Each UAM has a rate λ_switch (events per hour).
   - Switches occur randomly with exponential inter-arrival times.
2. **Scenario- / location-based triggers**
   - Define “hot zones” along the corridor (e.g., near hubs or intersections).
   - UAMs entering these zones have an elevated probability of switching to HWTL.

Configuration:

- Per-UAM or global switch rates.
- Mean duration of HWTL episodes.
- Maximum allowed number of concurrent HWTL vehicles (optional).

#### 5.3.3 Effects on Traffic

- On mode switch:
  - Adjust UAM’s traffic profile immediately:
    - HOTL → HWTL: increase offered load to target (e.g., 6 Mbps).
    - HWTL → HOTL: reduce to lower load.
- Record:
  - Number of switches per unit time (per corridor, per BS, global).
  - Impact on BS loads, RTT, and safety metrics.

---

## 6. KPIs and Failure Criteria

### 6.1 Communications KPIs

Per scenario and over time:

1. **Per-link throughput**
   - UAM–BS link throughput (sent and successfully delivered).
2. **Per-BS throughput and load factor**
   - Total bits/sec or messages/sec processed.
   - Load factor ρ and channel busy ratio.
3. **Latency / RTT**
   - Average, min, max, and selected quantiles for RTT per message class.
4. **Message drop rate**
   - Due to buffer overflow, no coverage, handoffs.
5. **Number and duration of red-load intervals**
   - Time spent above critical thresholds per BS.

### 6.2 Transportation & Safety KPIs

1. **Corridor capacity**
   - Average and maximum number of UAMs in corridor and per lane.
2. **Separation time**
   - Distribution of separation times; minimum separation time observed.
3. **Time-to-conflict proxy**
   - Count/percentage of time steps where time-to-conflict < threshold.
4. **Mode-switch statistics**
   - Total number of switches.
   - Switches per second (corridor-level).
   - Correlation with communication degradation.
5. **Outcome classification**
   - **Normal:** below all thresholds.
   - **Degraded:** e.g., high delay or moderate drop rate but safety margins respected.
   - **Unsafe/unacceptable:** safety thresholds violated (separation/time-to-conflict, persistent RTT > max for critical messages).

---

## 7. Simulation Control and Configuration

### 7.1 Core Configuration Schema (Conceptual)

Design a Python-friendly configuration structure, e.g.:

```python
config = {
    "simulation": {
        "t_start": 0.0,
        "t_end": 3600.0,          # seconds
        "dt": 0.1,                # time step
        "random_seed": 42,
    },
    "corridors": [
        {
            "id": "SF-SJ",
            "length_m": 80000,
            "altitude_m": 300,
            "height_m": 33,
            "num_lanes": 1
        }
    ],
    "hubs": [
        {"id": "SF", "corridor_id": "SF-SJ", "position_m": 0.0},
        {"id": "SJ", "corridor_id": "SF-SJ", "position_m": 80000.0}
    ],
    "uams": {
        "num_uams": 50,
        "spawn_pattern": "uniform",   # or "batch", etc.
        "speed_mps": [30, 50],        # range or fixed
        "T_sep_min_s": 5.0
    },
    "base_stations": [
        {
            "id": "BS1",
            "position": [x1, y1],
            "coverage_good_radius_m": 1000,
            "coverage_degraded_radius_m": 3000,
            "capacity_msgs_per_s": 1000,
            "buffer_capacity_msgs": 200
        },
        # more BS...
    ],
    "traffic": {
        "bsm_size_bytes": 300,
        "bsm_rate_hz": 10,
        "hotl_rate_kbps": 35,
        "hwtl_rate_mbps": 6,
        "RTT_max_s": 0.2
    },
    "mode_switch": {
        "model": "poisson",  # or "zone"
        "lambda_per_hour": 0.5,
        "mean_hwtl_duration_s": 60
    },
    "handoff": {
        "delay_s": 0.2,
        "p_drop": 0.1
    },
    "thresholds": {
        "load_warning": 0.6,
        "load_critical": 0.85,
        "sep_time_min_s": 2.0,
        "ttc_min_s": 5.0
    }
}
```

Implementation must not be tied to this exact schema but should provide something similar and clearly documented.

---

## 8. HTML Visualization Requirements

### 8.1 General

- Output: a **single `.html` file** per run.
- Must be **self-contained**:
  - All HTML, CSS, and JavaScript embedded inline.
  - No references to external URLs, JS libraries (e.g., no CDN), images, or fonts.
- Must be viewable in a modern browser without a server.

### 8.2 Content Sections

At minimum, the HTML should contain:

1. **Header**
   - Scenario name.
   - Date/time of simulation.
   - High-level description (automatically generated).

2. **Configuration Summary**
   - Collapsible panel showing key input parameters:
     - Corridor(s) layout.
     - Number of UAMs.
     - BS locations and capacities.
     - Mode-switch and handoff settings.
     - Thresholds for KPIs.

3. **Key Metrics Dashboard**
   - At least the following interactive plots/tables:
     - Time series of:
       - Number of UAMs in corridor.
       - Min separation time.
       - Average (or 95th percentile) RTT.
       - BS load factor (select BS with a dropdown).
     - Histogram or distribution of:
       - Separation times.
       - RTTs.
       - Message drops per UAM or per BS.
     - Summary table:
       - For each BS: avg load, max load, drop rate, time in red zone.
       - For each scenario: classification (normal/degraded/unsafe).

4. **Spatial View (Simplified)**
   - 2D diagram showing:
     - Corridor as a line.
     - BS positions.
   - Optional animation or step slider:
     - At selected time step, show approximate UAM positions and which BS they’re attached to.
   - Interactivity:
     - Hover to show UAM id, mode, attached BS, and local metrics.

5. **Scenario Comparison (if multiple scenarios run)**
   - Plots overlaying key KPIs across scenarios.
   - Dropdown to select which scenarios to display.

### 8.3 Interactivity and Implementation Notes

- Implement interactivity using **inline JavaScript**:
  - Plain JS (no frameworks) is acceptable.
  - Use `<svg>` or `<canvas>` for charts, or hand-coded interactions.
- Required interactions:
  - Toggle visibility of metric curves.
  - Hover to see numerical values (e.g., tooltip).
  - Drop-down or buttons to switch scenario and metric.
  - Slider or play/pause to move along time steps for spatial view.

---

## 9. Non-Functional Requirements

### 9.1 Performance

- Aim to handle:
  - O(10^2) UAMs,
  - O(10) base stations,
  - Simulation durations of up to 1 hour with Δt on the order of 0.1–1.0 seconds,
  - On a typical laptop within a few minutes.
- Provide options to:
  - Reduce logging frequency (e.g., record metrics every N steps).
  - Downsample data for visualization to keep HTML size manageable.

### 9.2 Extensibility

- Code should be modular, separating:
  - Configuration parsing
  - Graph and state representation
  - Simulation loop
  - Metrics calculation
  - HTML report generation
- Make it straightforward to:
  - Add new KPIs.
  - Change trigger models.
  - Add additional corridors or lanes.

### 9.3 Reproducibility

- All stochastic elements must use a configurable random seed.
- The seed and key parameters must appear in the HTML report.

---

## 10. Deliverables

1. **Python module/package** containing:
   - Core simulation engine.
   - API entry points:
     - `run_simulation(config) -> result`
     - `generate_html_report(result, output_path)`
2. **Configuration examples**:
   - Single-corridor toy scenario.
   - Higher-density scenario stressing BS capacity.
   - Scenario with frequent HOTL→HWTL switches.
3. **Sample HTML reports** for each example.
4. **Documentation**:
   - Brief README describing how to:
     - Set up the configuration.
     - Run simulations.
     - Generate and view HTML reports.
   - Description of KPIs and thresholds.
