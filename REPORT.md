# UAM Corridor Communication–Transportation Simulation
## Technical Model Report

**Authors:** Yanbing Wang (Arizona State University) · Toyota ITL

**Date:** March 2026

---

## 1. Overview

This report describes the mathematical and implementation-level structure of a discrete-time coupled simulation that co-models the **traffic dynamics** and **cellular communication infrastructure** of a single Urban Air Mobility (UAM) corridor. The simulator is written in Python and organized into four layers: 
1. corridor/UAM kinematics
2. base-station infrastructure
3. communication networking
4. metrics calculation

Four scenarios are run to probe failure modes relevant to shared 5G infrastructure.

The simulator is intentionally minimal: it uses closed-form analytical approximations rather than physics-based flight dynamics or link-level radio models. This is appropriate for a first-pass study of *coupling* between traffic density and communication load, and for identifying the parameter regimes in which that coupling becomes safety-critical.

---

## 2. Traffic Layer

### 2.1 Corridor Definition

The simulation models a single one-dimensional corridor representing the San Francisco – San Jose (SF–SJ) route.

| Parameter | Symbol | Value |
|-----------|--------|-------|
| Corridor length | $L$ | 80,000 m (80 km) |
| Cruise altitude AGL | $h$ | 300 m |
| Vertical band thickness | $\Delta h$ | 33 m |
| Number of lanes | $N_\ell$ | 1 (baseline), 2 (high-density) |
| Origin hub | SF | $x = 0$ m |
| Destination hub | SJ | $x = L$ |

The corridor is modeled as a 1D segment parameterized by horizontal position $x \in [0, L]$. UAMs travel one-way from SF ($x=0$) to SJ ($x=L$). Lateral lane separation is tracked as a discrete integer label but lane-switching logic is not implemented. When a UAM reaches $x \geq L$ it is marked as arrived and removed from all subsequent computations; no respawning is implemented in the current prototype. Future work will replace the linear segment with geographic waypoints specified in the configuration.

### 2.2 UAV Kinematic Model

Each UAM $i$ carries state $(x_i, v_i, \text{mode}_i, s_i^{\text{BS}})$ at each time step, where $x_i$ is longitudinal position, $v_i$ is speed, $\text{mode}_i \in \{\text{HOTL}, \text{HWTL}\}$ is the human–control mode, and $s_i^{\text{BS}}$ is the index of the currently serving base station.

#### 2.2.1 Spawn Pattern

UAMs are initialized at $t = 0$ with a **uniform spacing** pattern:

$$x_i(0) = \frac{L}{N+1} \cdot i, \quad i = 1, \ldots, N$$

where $N$ is the number of UAMs and lane assignment is $\ell_i = i \bmod N_\ell$.

**Density validation.** For uniform spawn, UAMs interleave across lanes so the intra-lane gap is:

$$\Delta x_{\text{lane}} = N_\ell \cdot \frac{L}{N+1}$$

The minimum safe spacing at the slowest design speed is $v_{\min} \cdot \tau_{\min}$. The simulator raises a `ValueError` at initialization if:

$$\Delta x_{\text{lane}} < v_{\min} \cdot \tau_{\min}$$

The maximum feasible fleet size is:

$$N_{\max} = N_\ell \cdot \left\lfloor \frac{L}{v_{\min} \cdot \tau_{\min}} \right\rfloor - 1$$

**Initial speed assignment.** Rather than drawing speeds independently, speeds are assigned in a post-spawn pass to be consistent with the car-following model. Within each lane, UAMs are processed from leader (highest $x$) to last follower; each follower's initial speed is capped:

$$v_i(0) = \min\!\left(v_i^{\text{rand}},\ \frac{x_{i-1}(0) - x_i(0)}{\tau_{\min}}\right)$$

where $v_i^{\text{rand}} \sim \mathcal{U}(v_{\min}, v_{\max})$. This ensures the initial state is a valid car-following configuration. In practice, for all current scenarios the uniform spacing is large enough that the cap is never active (see density validation numbers above).

| Scenario | $N$ | $v_{\min}$ (m/s) | $v_{\max}$ (m/s) | $\Delta x_{\text{lane}}$ (m) | $v_{\min}\tau_{\min}$ (m) |
|----------|-----|-----------------|-----------------|------------------------------|--------------------------|
| Baseline | 50 | 40 | 60 | 1,569 | 200 |
| High density | 150 | 35 | 55 | 1,060 | 105 |
| Frequent switches | 80 | 40 | 60 | 988 | 200 |
| Cascade failure | 60 | 40 | 55 | 1,311 | 200 |

#### 2.2.2 Car-Following Law

The longitudinal dynamics follow a **time-gap car-following rule** applied within each lane. At each step, UAMs in a lane are sorted by position in descending order; the vehicle at the head of the queue is the *leader*.

**Leader (free-flow):** no vehicle ahead, constant speed:

$$x_{\text{lead}}(t + \Delta t) = x_{\text{lead}}(t) + v_{\text{lead}} \cdot \Delta t$$

**Follower:** let $\Delta x_{i} = x_{i-1}(t) - x_i(t)$ be the gap to the vehicle immediately ahead, and $\tau_{\min}$ the minimum safe time gap. The safe gap criterion is:

$$g_{\text{safe},i} = v_i \cdot \tau_{\min}$$

If $\Delta x_i < g_{\text{safe},i}$, the follower decelerates to maintain the minimum headway:

$$v_i^{*} = \max\!\left(\frac{\Delta x_i}{\tau_{\min}},\ 0\right)$$
$$v_i \leftarrow v_i^{*}$$

A **hard collision guard** is applied immediately after the car-following speed adjustment, before advancing position. Because the leader's position has already been updated to $x_{i-1}(t+\Delta t)$ earlier in the same loop iteration, the maximum physically admissible speed for the follower is:

$$v_i^{\text{guard}} = \max\!\left(0,\ \frac{x_{i-1}(t + \Delta t) - x_i(t)}{\Delta t}\right)$$

$$v_i \leftarrow \min(v_i,\ v_i^{\text{guard}})$$

This is a strict invariant: no follower can reach or overtake its leader within a single time step, regardless of any other dynamics. Position is then advanced:

$$x_i(t + \Delta t) = x_i(t) + v_i \cdot \Delta t$$

There is no explicit maximum deceleration constraint in the current prototype; the model directly sets speed to $v_i^*$ in one step (instantaneous response). This is a known simplification to be replaced with an IDM or similar model in future work.

| Parameter | Symbol | Baseline | Cascade |
|-----------|--------|----------|---------|
| Minimum safe time gap | $\tau_{\min}$ | 5.0 s | 5.0 s |
| Separation violation threshold | $\tau_{\text{viol}}$ | 2.0 s | 2.0 s |
| Time step | $\Delta t$ | 1.0 s | 1.0 s |

#### 2.2.3 Separation Metric

At each recorded step, pairwise separation times are computed for all consecutive UAM pairs within a lane:

$$T_{\text{sep},i} = \frac{x_{i+1} - x_i}{v_i}$$

where the index ordering is by ascending position ($x_{i+1} > x_i$). A **separation violation** is recorded when $T_{\text{sep},i} < \tau_{\text{viol}} = 2.0\,\text{s}$. Summary statistics include the per-step minimum and mean, plus the cumulative violation count over the run.

### 2.3 Human–Control Mode Switching

Each UAM operates in one of two modes at any instant:

- **HOTL** (Human-Over-The-Loop): supervisory monitoring; automation handles flight.
- **HWTL** (Human-Within-The-Loop): remote piloting via live video feed; human directly commands the aircraft.

Mode transitions follow a **Poisson process model** (default). The inter-arrival time to the next HOTL→HWTL switch for vehicle $i$ is drawn from an exponential distribution:

$$T_{\text{switch},i} \sim \text{Exp}(\lambda), \quad \lambda = \lambda_{\text{hr}} / 3600\ [\text{s}^{-1}]$$

HWTL episode duration is independently drawn:

$$D_{\text{HWTL},i} \sim \text{Exp}(\mu_{\text{HWTL}}), \quad \mu_{\text{HWTL}} = 1 / \bar{d}\ [\text{s}^{-1}]$$

Upon episode expiry, the vehicle returns to HOTL and a new inter-arrival time is drawn.

An alternative **zone-based trigger model** is also implemented: UAMs entering designated hot-zones (e.g., the first and last 5 km near hubs) switch to HWTL with per-step probability $p_{\text{zone}} \cdot \Delta t$.

| Scenario | $\lambda_{\text{hr}}$ | $\bar{d}$ (s) |
|----------|-----------------------|---------------|
| Baseline | 0.5 / UAM / hr | 60 |
| Frequent switches | 5.0 / UAM / hr | 45 |
| Cascade failure | 8.0 / UAM / hr | 90 |

An optional `max_concurrent_hwtl` cap can enforce a fleet-wide HWTL concurrency limit (set to `None` in all prototype scenarios).

---

## 3. Infrastructure Layer

### 3.1 Base Station Specifications

Base stations (BS) represent ground-based cellular radio access points (conceptually 5G NR gNB nodes). Each BS is modeled with a fixed capacity and a simplified **M/M/1 queuing model** for uplink congestion.

| Parameter | Symbol | Baseline | High Density | Cascade Failure |
|-----------|--------|----------|--------------|-----------------|
| Number of BS | $M$ | 16 | 16 | 6 |
| BS capacity | $C$ | 100 Mbps | 50 Mbps | 20 Mbps |
| Good-coverage radius | $r_{\text{good}}$ | 3,000 m | 3,000 m | 5,000 m |
| Degraded-coverage radius | $r_{\text{deg}}$ | 6,000 m | 6,000 m | 9,000 m |
| Message buffer capacity | $B$ | 500 msgs | 300 msgs | 500 msgs |

Coverage radii are measured in 3D Euclidean distance from the BS to the UAM. A UAM receives "good" service if $d \leq r_{\text{good}}$, "degraded" service if $r_{\text{good}} < d \leq r_{\text{deg}}$, and no service otherwise.

#### M/M/1 Queuing Model

The queuing delay at each BS is approximated with the M/M/1 mean sojourn time formula. Let $\lambda_{\text{arr}}$ [bps] be the total UAM traffic arriving at the BS in a given step, and $C$ [bps] be the BS capacity. The traffic intensity is:

$$\rho = \frac{\lambda_{\text{arr}}}{C}$$

The mean queuing delay is:

$$W = \frac{L_{\min}}{1 - \rho}, \quad \rho < 1$$

where $L_{\min} = 5\,\text{ms}$ is a base processing latency (serialization + scheduling overhead). For $\rho \geq 1$ (saturated), $W$ is capped at 2.0 s to bound numerical divergence. Load factor thresholds for alerting:

| Level | Threshold |
|-------|-----------|
| Warning | $\rho \geq 0.60$ |
| Critical | $\rho \geq 0.85$ |
| Saturated | $\rho \geq 1.00$ |

Buffer overflow is checked separately: if the number of messages arriving in a step exceeds $B$, the excess is counted as dropped.

### 3.2 Infrastructure Placement

Base stations are placed at **uniform intervals along the corridor**, offset 500 m laterally from the centerline:

$$x_j^{\text{BS}} = \frac{L}{M+1} \cdot j, \quad j = 1, \ldots, M$$
$$y_j^{\text{BS}} = 500\,\text{m}$$

This yields a spacing of:

- Baseline / high-density (16 BS): $\Delta x \approx 4{,}706\,\text{m}$ ≈ 4.7 km
- Cascade failure (6 BS): $\Delta x \approx 11{,}429\,\text{m}$ ≈ 11.4 km

The 3D Euclidean distance from BS $j$ to UAM $i$ at position $x_i$ and altitude $h = 300\,\text{m}$ is:

$$d_{ij} = \sqrt{(x_j^{\text{BS}} - x_i)^2 + (y_j^{\text{BS}})^2 + h^2}$$

Note that UAM lateral position (within-lane) is projected onto the corridor centerline ($y_{\text{UAM}} = 0$) for coverage computation; only longitudinal position is resolved. Each BS is also permanently connected to the Ground Control Station (GCS) via a lossless backhaul link with fixed RTT = 10 ms.

---

## 4. Network Layer

### 4.1 Communication Type

The communication substrate is modeled as a **cellular uplink/downlink** network, abstracting a 5G NR-like air–ground link. No explicit radio propagation model (path loss, fading, SINR) is implemented; connectivity is a deterministic threshold on 3D distance. This is a first-order approximation consistent with the prototype scope.

**Communication graph** $\mathcal{G} = (\mathcal{V}, \mathcal{E})$:

- $\mathcal{V}$: UAM nodes, BS nodes, one GCS node
- $\mathcal{E}$: directed edges $(u, \text{BS})$ and $(\text{BS}, u)$ for each connected UAM; edges $(\text{BS}, \text{GCS})$ always present

Each edge carries attributes: `quality` ∈ {good, degraded}, `rtt` (seconds), `rtt_ok` (bool).

### 4.2 Messages Exchanged

Each UAM generates two classes of messages per time step, independent of mode:

#### Basic Safety Message (BSM)

Conceptually aligned with ASTM F3548 / GUTMA UTM message formats:

| Field | Value |
|-------|-------|
| Payload size | 300 bytes |
| Broadcast rate | 10 Hz |
| Bit rate | 300 × 8 × 10 = **24,000 bps** (24 kbps) |
| Purpose | Position, velocity, identity; shared with all network nodes |

#### Control / Telemetry Stream

The uplink/downlink control channel has two bandwidth regimes depending on mode:

| Mode | Payload | Bit Rate | Purpose |
|------|---------|----------|---------|
| HOTL | Supervisory telemetry | **35 kbps** | Aircraft health, automation status; human monitors only |
| HWTL | Live video + command | **6 Mbps** | Full video feed to ground pilot; human actively commands |

**Total per-UAM demand on serving BS:**

$$R_i = R_{\text{BSM}} + R_{\text{ctrl}} = \begin{cases} 59\,\text{kbps} & \text{mode} = \text{HOTL} \\ 6{,}024\,\text{kbps} \approx 6\,\text{Mbps} & \text{mode} = \text{HWTL} \end{cases}$$

This ~100× bandwidth ratio between modes is the primary driver of network stress: a single HWTL aircraft consumes as much bandwidth as roughly 100 HOTL aircraft.

**Per-step message count:** At $\Delta t = 1\,\text{s}$, each UAM generates $10$ BSM messages and $10$ control messages = **20 messages/step/UAM** at the serving BS. This count is used for buffer-overflow tracking independent of bit-rate accounting.

#### External (Terrestrial) Load

In the Cascade Failure scenario, non-UAM ground users (modeled as a stadium event) inject additional traffic on all BS simultaneously:

$$R_{\text{ext}}(t) = \begin{cases} 8\,\text{Mbps} & 120\,\text{s} \leq t \leq 360\,\text{s} \\ 0 & \text{otherwise} \end{cases}$$

This load competes for BS bandwidth with UAM traffic but is not attributed to the UAM message queue (terrestrial users have logically separate queues; only the bandwidth competition effect is modeled).

### 4.3 RTT Computation

End-to-end round-trip time for UAM $i$ served by BS $j$ is composed of three additive terms:

$$\text{RTT}_i = 2\left(t_{\text{prop},ij} + W_j + t_{\text{backhaul}}\right) + \delta_{\text{handoff}}$$

| Component | Formula / Value | Notes |
|-----------|----------------|-------|
| Propagation delay | $t_{\text{prop}} = d_{ij} / c$, $c = 3 \times 10^8$ m/s | Dominated by altitude; $d \approx 300$–3000 m → $t_{\text{prop}} \approx 1$–10 µs |
| Queuing delay | $W_j = L_{\min}/(1-\rho_j)$ | M/M/1; grows without bound as $\rho \to 1$ |
| Backhaul delay | $t_{\text{backhaul}} = 10\,\text{ms}$ | Fixed BS–GCS link latency |
| Handoff penalty | $\delta_{\text{handoff}} = 100\,\text{ms}$ (if in handoff) | Added once during active handoff period |

The RTT safety threshold is $\text{RTT}_{\max} = 500\,\text{ms}$. Violations ($\text{RTT} > \text{RTT}_{\max}$) are flagged per UAM per step; the maximum fleet-wide RTT is tracked as a KPI.

### 4.4 Handoff Between Base Stations

Serving BS assignment and handoff follow a nearest-BS-with-hysteresis rule executed at every time step.

**Step 1 — Coverage scan.** For each active UAM, compute $d_{ij}$ to every BS and identify the candidate set:

$$\mathcal{C}_i = \{ j : d_{ij} \leq r_{\text{deg}} \}$$

If $\mathcal{C}_i = \emptyset$, the UAM is in a coverage gap; all graph edges to that UAM are removed.

**Step 2 — Best BS selection.** Sort $\mathcal{C}_i$ by distance; the nearest BS is the candidate $j^*$.

**Step 3 — Hysteresis check.** If UAM $i$ is already associated with BS $j_{\text{prev}}$ and $j^* \neq j_{\text{prev}}$, a handoff is triggered only if the candidate is at least 20% closer than the current server:

$$d_{ij^*} \leq 0.8 \cdot d_{i,j_{\text{prev}}}$$

If this condition is not met and $j_{\text{prev}}$ still provides coverage, the UAM stays on $j_{\text{prev}}$. This prevents ping-pong at cell edges.

**Step 4 — Handoff execution.** When a handoff is triggered:
- The old BS–UAM edges are removed from $\mathcal{G}$.
- `in_handoff = True` for a period $T_{\text{HO}} = 200\,\text{ms}$.
- During $T_{\text{HO}}$: each message is independently dropped with probability $p_{\text{drop}} = 0.1$; RTT is penalized by $+100\,\text{ms}$.
- After $T_{\text{HO}}$ elapses, the UAM associates cleanly with $j^*$ and new edges are added.

**Step 5 — Graph update.** New directed edges $(u_i, j^*)$ and $(j^*, u_i)$ are written with `quality` set to "good" or "degraded" based on $d_{ij^*}$ vs. $r_{\text{good}}$.

| Parameter | Symbol | Value |
|-----------|--------|-------|
| Handoff execution delay | $T_{\text{HO}}$ | 200 ms |
| Message drop probability during handoff | $p_{\text{drop}}$ | 0.10 |
| RTT penalty during handoff | $\delta_{\text{HO}}$ | 100 ms |
| Hysteresis margin | — | 20% distance reduction required |

---

## 5. Simulation Execution

The simulator advances in uniform discrete time steps $\Delta t = 1\,\text{s}$ over a horizon $T = 600\,\text{s}$ (10 minutes). Each step executes five phases in strict order:

1. **Position update** — car-following law applied to all UAMs.
2. **Mode switching** — Poisson timers decremented; HOTL↔HWTL transitions executed.
3. **Coverage and handoff** — serving BS re-evaluated; handoff timers decremented.
4. **Traffic and queuing** — per-BS traffic loads computed; M/M/1 delay and buffer overflow evaluated; RTT computed per UAM.
5. **KPI recording** — all time-series metrics written to collector.

All scenarios use a seeded pseudo-random number generator (`random.Random(seed)`) for reproducibility.

---

## 6. Simulation Scenarios

| # | Name | $N$ | $M$ | $C$ [Mbps] | $\lambda_{\text{hr}}$ | External Load | Classification |
|---|------|-----|-----|------------|----------------------|---------------|----------------|
| 1 | Baseline | 50 | 16 | 100 | 0.5 | None | Normal |
| 2 | High Density | 150 | 16 | 50 | 0.5 | None | Unsafe |
| 3 | Frequent Switches | 80 | 16 | 100 | 5.0 | None | Normal |
| 4 | Cascade Failure | 60 | 6 | 20 | 8.0 | +8 Mbps @ t=120–360 s | Unsafe |

---

## 7. Known Limitations and Future Work

The following are deliberate simplifications in the current prototype, flagged for replacement with validated sub-models:

| Component | Current Model | Planned Replacement |
|-----------|--------------|---------------------|
| UAV kinematics | Instantaneous speed adjustment, no dynamics | IDM or Wiedemann car-following; eVTOL thrust/drag model |
| Safe separation time | $\tau_{\min}$ = 2–5 s (placeholder) | Calibrated from Joby S4 / Toyota NX performance envelope |
| Radio propagation | Binary threshold on 3D distance | A2G path-loss model (free-space + terrain shielding) |
| Link capacity | Fixed BS capacity | SINR-based spectral efficiency; frequency reuse |
| 5G queuing | M/M/1 | M/M/1/K or M/D/1; multi-class priority queuing for UAM vs. ground users |
| Corridor geometry | 1D linear | SF–SJ geographic waypoints, no-fly zones, multi-lane 3D |
| Network topology | Static BS placement | Dynamic HAPS or moving-relay topology |
| HWTL switch trigger | Poisson (stationary) | Event-triggered: weather, airspace conflict, ATC instruction |

---

## Appendix A: Key Equations Summary

| Equation | Description |
|----------|-------------|
| $d_{ij} = \sqrt{(x_j^{\text{BS}}-x_i)^2 + (y_j^{\text{BS}})^2 + h^2}$ | 3D UAM–BS distance |
| $\rho_j = \sum_{i \in S_j} R_i \;/\; C_j$ | BS traffic intensity (utilization) |
| $W_j = L_{\min}/(1-\rho_j)$, $\rho_j < 1$ | M/M/1 mean queuing delay |
| $\text{RTT}_i = 2(d_{ij}/c + W_j + t_{\text{bh}}) + \delta_{\text{HO}}$ | Round-trip time |
| $T_{\text{sep},i} = (x_{i+1} - x_i) / v_i$ | Longitudinal separation time |
| $v_i^* = \max(\Delta x_i / \tau_{\min},\, 0)$ | Car-following speed adjustment |
| $T_{\text{switch}} \sim \text{Exp}(\lambda_{\text{hr}}/3600)$ | Poisson mode-switch inter-arrival |
| $D_{\text{HWTL}} \sim \text{Exp}(1/\bar{d})$ | HWTL episode duration |

---

## Appendix B: Default Parameter Table

| Parameter | Symbol | Default Value |
|-----------|--------|---------------|
| Simulation horizon | $T$ | 600 s |
| Time step | $\Delta t$ | 1.0 s |
| Corridor length | $L$ | 80,000 m |
| Corridor altitude | $h$ | 300 m AGL |
| UAM speed range | $[v_{\min}, v_{\max}]$ | [40, 60] m/s |
| Min separation time | $\tau_{\min}$ | 5.0 s |
| Violation threshold | $\tau_{\text{viol}}$ | 2.0 s |
| BS spacing (baseline) | $\Delta x$ | ≈ 4,706 m |
| BS capacity (baseline) | $C$ | 100 Mbps |
| Good-coverage radius | $r_{\text{good}}$ | 3,000 m |
| Degraded-coverage radius | $r_{\text{deg}}$ | 6,000 m |
| Buffer capacity | $B$ | 500 msgs |
| BSM size | — | 300 bytes |
| BSM rate | — | 10 Hz |
| HOTL control rate | $R_{\text{HOTL}}$ | 35 kbps |
| HWTL video rate | $R_{\text{HWTL}}$ | 6 Mbps |
| RTT safety threshold | $\text{RTT}_{\max}$ | 500 ms |
| Base processing delay | $L_{\min}$ | 5 ms |
| Backhaul delay | $t_{\text{bh}}$ | 10 ms |
| Handoff duration | $T_{\text{HO}}$ | 200 ms |
| Drop probability (handoff) | $p_{\text{drop}}$ | 0.10 |
| Default switch rate | $\lambda_{\text{hr}}$ | 0.5 / UAM / hr |
| Default HWTL duration | $\bar{d}$ | 60 s |
| Load warning threshold | — | 60% |
| Load critical threshold | — | 85% |
