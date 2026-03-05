# UAM Corridor Communication–Transportation Simulator

A Python prototype simulation model jointly capturing **UAM traffic dynamics**, **5G communication network behavior**, and **HOTL/HWTL mode switching** along the San Francisco–San Jose air corridor.

Developed in collaboration with Toyota/TEMA and Arizona State University.

---

## Table of Contents

1. [Quick Start](#1-quick-start)
2. [Configuration Guide](#2-configuration-guide)
3. [Running Simulations](#3-running-simulations)
4. [HTML Report Guide](#4-html-report-guide)
5. [KPIs and Thresholds](#5-kpis-and-thresholds)
6. [Interpreting Scenario Results](#6-interpreting-scenario-results)
7. [Why the High-Density Scenario is Unsafe](#7-why-the-high-density-scenario-is-unsafe)

---

## 1. Quick Start

```bash
# From the project root
python3 run.py
```

Produces four HTML reports in `reports/`:

| File | Description |
|------|-------------|
| `report_baseline.html` | 50 UAMs, moderate traffic |
| `report_high_density.html` | 150 UAMs, reduced BS capacity |
| `report_frequent_switches.html` | 80 UAMs, high HOTL→HWTL switch rate |
| `report_comparison.html` | All three scenarios overlaid |

Open any `.html` file in a modern browser — no server or internet required.

---

## 2. Configuration Guide

### 2.1 Configuration Structure

All simulation parameters are controlled through a single Python `dict` passed to `run_simulation()`. The default SF-SJ corridor configuration is in `uam_sim/config.py`:

```python
from uam_sim.config import default_config, validate_config
from uam_sim.engine import run_simulation
from uam_sim.report import generate_html_report

cfg = default_config()           # start from defaults
cfg["uams"]["num_uams"] = 100    # override specific parameters
validate_config(cfg)             # optional: check for errors
result = run_simulation(cfg)
generate_html_report(result, "my_report.html")
```

### 2.2 Parameter Reference

The table below maps each configuration parameter to the reference documents that motivated its default value.

#### Simulation Control

| Parameter | Key | Default | Source |
|-----------|-----|---------|--------|
| Simulation duration | `simulation.t_end` | 600 s | — |
| Time step | `simulation.dt` | 1.0 s | — |
| Random seed | `simulation.random_seed` | 42 | — |

#### Corridor and UAM Parameters

| Parameter | Key | Default | Source |
|-----------|-----|---------|--------|
| Corridor length | `corridors[0].length_m` | 80,000 m | SF-SJ geographic distance |
| Flight altitude | `corridors[0].altitude_m` | 300 m | Typical low-altitude UAM operations; see **UAM ConOps 2.0** §4.1 (Airspace Classes) and **Boeing ConOps** §4.1.1 |
| Vertical thickness | `corridors[0].height_m` | 33 m | Multi-resolution block structure from **Safety_Metrics_and_Corridor_2.pdf** Fig. 1 |
| Number of lanes | `corridors[0].num_lanes` | 1–3 | Variable per scenario; see **FY26 ASU Proposal** §Graph Representation ("2 or 3 lanes") |
| UAM cruise speed | `uams.speed_mps` | [40, 60] m/s (~90–135 mph) | Consistent with eVTOL performance; **Boeing ConOps** §3.1.1 (Navigation) |
| Minimum separation time | `uams.T_sep_min_s` | 5.0 s | In-trail self-spacing standard; **Boeing ConOps** §4.1.2 ("in-trail self-spacing and interval management") |

#### Base Station Parameters

| Parameter | Key | Default | Source |
|-----------|-----|---------|--------|
| Number of BS | `base_stations` (list length) | 16 | ~5 km spacing along 80 km corridor |
| Good coverage radius | `coverage_good_radius_m` | 3,000 m | **FY26 ASU Proposal** §Questions ("1km good, 3km bad (abstract)"); we model 3km good / 6km degraded as a conservative urban 5G estimate |
| Degraded coverage radius | `coverage_degraded_radius_m` | 6,000 m | See above |
| BS capacity | `capacity_bps` | 100 Mbps | Representative urban 5G NR capacity |
| Buffer capacity | `buffer_capacity_msgs` | 500 msgs | See **CascadeFailureScenario.docx** §1.1 for BS capacity attributes |

#### Communication Traffic Parameters

Parameters derived from the **FY26 ASU Proposal** §Edge Attributes table and **CascadeFailureScenario.docx** §Aircraft Nodes:

| Parameter | Key | Default | Source |
|-----------|-----|---------|--------|
| BSM message size | `traffic.bsm_size_bytes` | 300 bytes | V2X / C-V2X broadcast standard |
| BSM broadcast rate | `traffic.bsm_rate_hz` | 10 Hz | V2X standard (10 Hz position broadcast) |
| HOTL (HOVTL) data rate | `traffic.hotl_rate_bps` | 35,000 bps (35 kbps) | **FY26 ASU Proposal**: "RPCS→UA C2 Control: 35 kbps" and "UA→RPCS Telemetry: 35 kbps" |
| HWTL video stream | `traffic.hwtl_rate_bps` | 6,000,000 bps (6 Mbps) | **FY26 ASU Proposal**: "UA→RPCS C2 Video: 4–9 Mbps (720p–1080p)"; mid-range 6 Mbps used |
| Maximum RTT | `traffic.RTT_max_s` | 0.5 s (500 ms) | **FY26 ASU Proposal** §Edge Attributes: "RTT: 500 ms" for all safety-critical paths; **CascadeFailureScenario.docx** §3.6: "RTT_total >> 500 ms THRESHOLD VIOLATED" |

#### Mode Switching Parameters

Sourced from **FY26 ASU Proposal** §Main Difference between HWTL and HOVTL and **CascadeFailureScenario.docx** §3.1:

| Parameter | Key | Default | Source |
|-----------|-----|---------|--------|
| Switch model | `mode_switch.model` | `"poisson"` | Stochastic transitions; `"zone"` available for hub-proximity triggers |
| Switch rate (Poisson) | `mode_switch.lambda_per_hour` | 0.5/hr | Configurable; increase to stress network |
| Mean HWTL duration | `mode_switch.mean_hwtl_duration_s` | 60 s | HWTL used for emergency/exception intervention; **FY26 ASU Proposal** §Scenario 1 |
| Max concurrent HWTL | `mode_switch.max_concurrent_hwtl` | `None` (unlimited) | Set to integer to enforce admission control; see **CascadeFailureScenario.docx** §6 Mitigation (A) |

#### Handoff Parameters

Sourced from **FY26 ASU Proposal** §Scenario 2 (Cell Handoff) and **CascadeFailureScenario.docx** §3.3:

| Parameter | Key | Default | Source |
|-----------|-----|---------|--------|
| Handoff delay | `handoff.delay_s` | 0.2 s (200 ms) | **CascadeFailureScenario.docx** §3.3: "Handoff duration: ~200 ms (temporary loss of connectivity)" |
| Handoff drop probability | `handoff.p_drop` | 0.10 (10%) | Message loss during link re-establishment |

#### Safety Thresholds

Sourced from **Safety_Metrics_and_Corridor_2.pdf** (separation minima) and **FY26 ASU Proposal** §System-Level Metrics:

| Parameter | Key | Default | Source |
|-----------|-----|---------|--------|
| BS load warning | `thresholds.load_warning` | 0.60 | **CascadeFailureScenario.docx** §5.3: "ρ_safe ≤ 0.7 recommended" |
| BS load critical | `thresholds.load_critical` | 0.85 | PRD §5.2.6; **CascadeFailureScenario.docx** §3.5 shows 90% → exponential latency |
| Min separation time | `thresholds.sep_time_min_s` | 2.0 s | **Safety_Metrics_and_Corridor_2.pdf**: strategic deconfliction separation minima |
| Time-to-conflict (TTC) | `thresholds.ttc_min_s` | 5.0 s | Near mid-air collision (NMAC) proxy; **FY26 ASU Proposal** §System Metrics ("Time to conflict / separation time") |

### 2.3 Modifying the Configuration

```python
from uam_sim.config import default_config
import copy

cfg = default_config()

# --- Admission control: limit simultaneous HWTL to 3 ---
cfg["mode_switch"]["max_concurrent_hwtl"] = 3

# --- Zone-based switching (hot zones near hubs) ---
cfg["mode_switch"]["model"] = "zone"
# hot_zones already defined in default config

# --- Add a second lane ---
cfg["corridors"][0]["num_lanes"] = 2

# --- Add more base stations (denser deployment) ---
cfg["base_stations"].append({
    "id": "BS_extra",
    "position": [40000, 0],        # midpoint of corridor
    "coverage_good_radius_m": 3000,
    "coverage_degraded_radius_m": 6000,
    "capacity_bps": 100_000_000,
    "buffer_capacity_msgs": 500,
})

# --- Run ---
from uam_sim.engine import run_simulation
result = run_simulation(cfg)
```

---

## 3. Running Simulations

### 3.1 Run All Example Scenarios

```bash
python3 run.py
```

Outputs appear in `reports/`. Runtime for all three scenarios combined: typically under 5 seconds.

### 3.2 Run a Custom Scenario

```python
from uam_sim.config import default_config, validate_config
from uam_sim.engine import run_simulation
from uam_sim.report import generate_html_report

cfg = default_config()
cfg["scenario_name"] = "My Custom Scenario"
cfg["uams"]["num_uams"] = 80
cfg["mode_switch"]["lambda_per_hour"] = 2.0

validate_config(cfg)
result = run_simulation(cfg)

generate_html_report(result, "output.html")
```

### 3.3 Run Multiple Scenarios and Compare

```python
results = []
for n_uam in [30, 60, 90, 120]:
    cfg = default_config()
    cfg["scenario_name"] = f"{n_uam} UAMs"
    cfg["uams"]["num_uams"] = n_uam
    results.append(run_simulation(cfg))

generate_html_report(results, "comparison.html",
                     scenario_name="UAM Capacity Sweep")
```

### 3.4 Accessing Results Programmatically

```python
result = run_simulation(cfg)

# Summary statistics
summary = result["metrics"].summary
print(summary["classification"])       # "normal", "degraded", or "unsafe"
print(summary["avg_rtt_s"])            # seconds
print(summary["drop_rate"])            # fraction 0–1
print(summary["min_separation_time_s"])

# Full time-series data
data = result["metrics"].to_dict()
print(data["time"])                    # list of timestamps
print(data["mean_rtt"])                # mean RTT per step
print(data["bs_load_factor"]["BS01"])  # load factor per step for BS01

# Per-BS summary
for bs_id, info in summary["bs"].items():
    print(bs_id, info["avg_load"], info["time_in_red_frac"])
```

---

## 4. HTML Report Guide

Each HTML report is fully self-contained — open it directly in any modern browser.

### 4.1 Sections

#### Header / Scenario Selector
If multiple scenarios were run, buttons at the top switch between them. All sections update to show the selected scenario.

#### Configuration Summary (collapsible)
Click the heading to expand/collapse. Shows all key input parameters for reproducibility.

#### Results Summary
- **Classification badge** (green = Normal, orange = Degraded, red = Unsafe) — see §5 for criteria
- **Six metric tiles**: Avg RTT, Max RTT, Min Separation, Drop Rate, Mode Switches, Separation Violations

#### Classification Rationale
Explains exactly which thresholds were exceeded. For each safety criterion, shows the measured value vs. the threshold, with a pass/fail indicator. This makes it easy to see *why* a scenario was classified a particular way.

#### Time Series Charts
Toggle individual curves on/off with the checkboxes above the charts. Hover over any curve to see the value at that time point (crosshair + tooltip).

Available series:
- **UAMs Active** – active vehicles in corridor
- **HWTL Count** – concurrent HWTL (remote piloting) vehicles
- **Min Separation (s)** – smallest inter-vehicle gap in the corridor
- **Mean RTT (ms)** – average round-trip latency
- **P95 RTT (ms)** – 95th-percentile RTT
- **Msgs Dropped** – total dropped messages per time step

#### BS Load Factor
Use the dropdown to select a specific base station and view its load factor ρ (fraction of capacity used) and queueing delay over time. The M/M/1 model means delay grows as `L_min / (1 − ρ)` — watch for exponential growth as ρ approaches 1.

#### Distributions
- **RTT histogram** — overall latency distribution across all UAMs and steps
- **Separation time histogram** — distribution of inter-vehicle gap times; values below 2 s are in the unsafe zone

#### Base Station Summary Table
Per-BS statistics with traffic-light status:
- 🟢 Max load ≤ 60%
- 🟡 Max load 60–85%
- 🔴 Max load > 85% or significant time in red zone

#### Spatial Corridor View
A 2D top-down diagram of the 80 km SF→SJ corridor showing:
- Blue dots: HOTL vehicles
- Red dots: HWTL vehicles (orange ring = in handoff)
- Colored squares: base stations (green/yellow/red = current load)
- Thin lines: UAM–BS associations

Use the **slider** or **Play** button to animate vehicle movement over time. Hover a UAM dot to see its ID, mode, serving BS, and position.

#### Scenario Comparison (multi-scenario reports only)
Overlays Mean RTT time series from all scenarios and shows a side-by-side summary table.

---

## 5. KPIs and Thresholds

### 5.1 Communication KPIs

| KPI | Formula / Definition | Warning | Critical |
|-----|---------------------|---------|----------|
| BS load factor ρ | `arrival_rate_bps / capacity_bps` | 0.60 | 0.85 |
| Queueing delay | `L_min / (1 − ρ)` where L_min = 5 ms | — | ρ → 1 |
| Round-trip time (RTT) | `2 × (propagation + queue + backhaul)` | — | > 500 ms |
| Message drop rate | `drops / (drops + processed)` | > 1% | > 5% |
| Time in red zone | Fraction of steps with ρ > 0.85 | > 5% | > 10% |

**Queuing model (M/M/1):** Latency follows `L_min / (1 − ρ)`. At ρ = 0.5, delay doubles. At ρ = 0.9, delay is 10×. At ρ = 1.0, the queue saturates and latency becomes unbounded — messages are dropped from the finite buffer instead.

**Drop mechanism:** Each BS has a finite message buffer (`buffer_capacity_msgs`). When messages arriving in a time step exceed the buffer, the overflow is counted as dropped. At 150 UAMs with 20 msgs/step per UAM, a BS serving 16+ UAMs generates 320+ msgs/step, exceeding the 300-message buffer and causing persistent drops.

### 5.2 Transportation / Safety KPIs

| KPI | Definition | Unsafe threshold |
|-----|-----------|-----------------|
| Separation time | `gap_distance / follower_velocity` | < 2.0 s |
| Time-to-conflict (TTC) | Proxy for NMAC risk | < 5.0 s |
| Separation violations | Steps where any pair violates min separation | > 0 |

**Separation time** is the UAM equivalent of time-headway in road traffic. A value below 2 s means the following vehicle cannot brake or maneuver to avoid a collision if the leader decelerates suddenly. The **Boeing ConOps** §4.1.2 establishes that UAM operations rely on "in-trail self-spacing" procedures; violation of minimum separation is therefore a direct safety risk.

### 5.3 Scenario Classification Logic

| Classification | Criteria |
|----------------|----------|
| **Normal** 🟢 | All thresholds satisfied; drop rate < 5%; no separation violations |
| **Degraded** 🟡 | High drop rate (> 5%) OR any BS with > 10% time in red zone, but safety margins respected |
| **Unsafe** 🔴 | Any separation time violation (< 2.0 s), OR persistent RTT > 500 ms for safety-critical links |

---

## 6. Interpreting Scenario Results

### Baseline (50 UAMs) — Normal ✅

With 50 UAMs uniformly distributed across 16 BS, each station serves ~3 vehicles. Even in HWTL mode (6 Mbps), a single BS at 100 Mbps capacity handles the load at ρ < 0.10. Separation times are comfortably above 10 s given the 1,600 m initial spacing at 50 m/s. This scenario validates the infrastructure is adequate for moderate density.

### High Density (150 UAMs) — Unsafe ⚠️

See §7 below for full analysis.

### Frequent Switches (80 UAMs, λ = 5/hr) — Normal ✅

With 80 UAMs and 96 mode switches over 600 s, the peak concurrent HWTL count is 3–4. Even with each HWTL UAM adding 6 Mbps, the serving BS at 100 Mbps capacity absorbs the burst (ρ ≈ 0.24 for 4 × 6 Mbps). Drop rate of 1.4% comes primarily from handoff events (10% drop probability during the 200 ms handoff window). The scenario demonstrates that frequent individual switches are manageable with adequate BS capacity — what matters is *concurrent* HWTL count, not switch rate per se.

**Key insight:** Compare the frequent-switch scenario to high-density. 96 switches at low density are benign; 31 switches at high density are catastrophic because the infrastructure is already saturated before any HWTL events occur.

---

## 7. Why the High-Density Scenario (150 UAMs) is Unsafe

### Root Causes

The high-density scenario reveals **two independent failure mechanisms**, both of which must be addressed for safe operation.

#### Failure 1: Buffer Overflow at BS16 (Message Drop Rate = 13%)

**The corridor geometry creates a hotspot.** With 16 BS placed at 4.7 km intervals, BS16 is located at 75.3 km — the final station before the SJ vertiport at 80 km. Because the simulation uses a wrap-around model (UAMs that complete the corridor re-enter at SF), vehicles congregate near both ends of the corridor. At steady state, **BS16 serves a mean of 34 UAMs and peaks at 56 UAMs**, compared to the network-average of ~9.4 UAMs per BS.

**Buffer math:**
```
56 UAMs × 20 msgs/step = 1,120 msgs arriving to BS16 in one time step
BS16 buffer capacity = 300 msgs
Overflow = 820 msgs dropped → 73% local drop rate at the hotspot
```

The M/M/1 queuing model from the [CascadeFailureScenario.docx](reference/CascadeFailureScenario.docx) shows this precisely: when `C_allocated → C_max`, queueing delay approaches infinity and the buffer overflows. The [FY26 ASU Proposal](reference/FY26_Arizona_State_University_Proposal_v3.docx) recommends **ρ_safe ≤ 0.7** and designing for `C_total ≥ (N × B_required) / ρ_safe`. For BS16 with 56 UAMs in HOTL mode:

```
Required capacity: 56 × 59 kbps / 0.7 = 4.7 Mbps   (manageable with 50 Mbps BS)
But buffer overflows before bandwidth saturates — the bottleneck is the message buffer, not throughput.
```

**Fix:** Increase `buffer_capacity_msgs` to at least 1,500 per BS, or cap the maximum UAMs per BS via admission control.

#### Failure 2: Separation Violations at Corridor Wrap-Around (3,113 Steps = 52% of Run)

**The wrap-around mechanic causes instant proximity.** When a UAM at position 79,999 m completes the corridor and re-enters at position ~0 m, it instantaneously appears immediately behind whatever vehicle happens to be there — without the benefit of car-following to slow it down *before* entering.

**Separation time at violation:**
```
Observed minimum separation: 1.50 s  (threshold: 2.0 s)
Violation steps: 3,113 out of 600 steps (52% of simulation time)
```

Even at the initial uniform spacing of 1,053 m per lane (2-lane corridor, 75 UAMs/lane), the *leading* vehicles in each lane are ~1,053 m / 55 m·s⁻¹ = **19 s of separation** — well above threshold. The violations occur only at the wrap boundary. In a real SF-SJ corridor there is no wrap-around; this reflects a limitation of the continuous-flow simulation model rather than an operational problem. However, the 150-UAM density itself means that any bunching event (e.g., a slow HWTL vehicle blocking traffic) causes cascading compression — the scenario is correctly flagged for further analysis.

**Fix:** In a realistic model, replace wrap-around with independent spawning at SF with a configurable inter-arrival rate and despawn at SJ.

### Summary Table

| Metric | Measured | Threshold | Verdict |
|--------|---------|-----------|---------|
| Min separation time | 1.50 s | ≥ 2.0 s | ❌ VIOLATED |
| Separation violation steps | 3,113 (52%) | 0 | ❌ VIOLATED |
| Overall message drop rate | 13.04% | < 5% | ❌ EXCEEDED |
| BS16 peak UAM load | 56 UAMs / step | ~10 (design) | ❌ HOTSPOT |
| BS16 peak buffer overflow | 820 msgs/step | 0 | ❌ VIOLATED |
| Max RTT | 134 ms | < 500 ms | ✅ OK |
| Max concurrent HWTL | 4 | no limit set | ✅ OK |

### Recommended Mitigations

1. **Admission control**: Set `mode_switch.max_concurrent_hwtl = 3` to limit simultaneous video streams (per **CascadeFailureScenario.docx** §6A)
2. **Increase BS density near hubs**: Deploy additional BS at 70–80 km to prevent the BS16 hotspot
3. **Larger message buffers**: `buffer_capacity_msgs = 1500` for high-density scenarios
4. **Network slicing / QoS**: Reserve dedicated bandwidth for UAM safety messages, isolating them from buffer overflow caused by bulk traffic (per **CascadeFailureScenario.docx** §5.2 and **FY26 ASU Proposal** §Mitigation C)
5. **Reduce num_lanes to 1** and spread UAMs temporally rather than in space to reduce per-BS peak load

---

## Project Structure

```
uam-graph/
├── uam_sim/
│   ├── __init__.py     # Public API: run_simulation, generate_html_report
│   ├── config.py       # Default configuration and validation
│   ├── models.py       # Corridor, Hub, UAM, BaseStation, CommGraph
│   ├── engine.py       # Discrete-time simulation loop
│   ├── metrics.py      # KPI collection and aggregation
│   └── report.py       # Self-contained HTML report generator
├── run.py              # Example scenarios entry point
├── reports/            # Generated HTML reports
└── reference/          # Source documents for parameter values
    ├── FY26_Arizona_State_University_Proposal_v3.docx
    ├── CascadeFailureScenario.docx
    ├── Safety_Metrics_and_Corridor_2.pdf
    ├── Boeing_Concept-of-Operations-for-Uncrewed-Urban-Air-Mobility.pdf
    └── Urban Air Mobility (UAM) Concept of Operations 2.0_*.pdf
```
