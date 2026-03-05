"""
HTML report generator for UAM corridor simulation.

Produces a single self-contained HTML file with:
  - Configuration summary
  - Interactive time-series plots (SVG-based)
  - Histograms for RTT and separation times
  - Per-BS summary table
  - Spatial corridor view with time slider
  - Scenario comparison (when multiple results provided)
"""

import json
import math
import datetime


def generate_html_report(results, output_path, scenario_name=None):
    """Generate a self-contained HTML report.

    Args:
        results: single result dict or list of result dicts from run_simulation()
        output_path: path to write the HTML file
        scenario_name: optional name for the report header
    """
    if isinstance(results, dict):
        results = [results]

    scenario_name = scenario_name or "UAM Corridor Simulation Report"
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Prepare data for embedding
    scenarios_data = []
    for i, res in enumerate(results):
        cfg = res["config"]
        m = res["metrics"]
        md = m.to_dict()

        # Downsample time series for reasonable HTML size
        ds = _downsample_factor(len(md["time"]), max_points=500)

        scenario = {
            "name": cfg.get("scenario_name", f"Scenario {i+1}"),
            "narrative": cfg.get("scenario_narrative", ""),
            "config": _config_summary(cfg),
            "summary": md["summary"],
            "rationale": _build_rationale(md["summary"], cfg),
            "time": md["time"][::ds],
            "num_uams_active": md["num_uams_active"][::ds],
            "num_uams_hwtl": md["num_uams_hwtl"][::ds],
            "min_separation_time": [
                min(v, 200) for v in md["min_separation_time"][::ds]
            ],
            "mean_rtt": md["mean_rtt"][::ds],
            "max_rtt": md["max_rtt"][::ds],
            "p95_rtt": md["p95_rtt"][::ds],
            "total_msgs_dropped": md["total_msgs_dropped"][::ds],
            "handoff_count": md["handoff_count"][::ds],
            "no_coverage_count": md["no_coverage_count"][::ds],
            "separation_violations": md["separation_violations"][::ds],
            "total_msgs_processed": md["total_msgs_processed"][::ds],
            "bs_load_factor": {
                k: v[::ds] for k, v in md["bs_load_factor"].items()
            },
            "bs_queue_delay": {
                k: v[::ds] for k, v in md["bs_queue_delay"].items()
            },
            "bs_summary": md["summary"].get("bs", {}),
            "bs_external_load": {
                k: v[::ds] for k, v in md.get("bs_external_load", {}).items()
            },
            "ext_load_events": [
                {
                    "t_start": ev["t_start"],
                    "t_end": ev["t_end"],
                    "label": ev.get("label", "External load"),
                    "load_mbps": ev.get("load_bps", 0) / 1e6,
                }
                for ev in cfg.get("external_load", {}).get("events", [])
                if cfg.get("external_load", {}).get("enabled", False)
            ],
            "mode_switch_events": md["mode_switch_events"][:500],
            "rtt_samples": md["rtt_samples"][:5000],
            "separation_samples": md["separation_samples"][:5000],
            "spatial_snapshots": md["spatial_snapshots"][:200],
            "base_stations": [
                {"id": bs["id"], "x": bs["position"][0], "y": bs["position"][1]}
                for bs in cfg["base_stations"]
            ],
            "corridor_length": cfg["corridors"][0]["length_m"],
        }
        scenarios_data.append(scenario)

    html = _build_html(scenarios_data, scenario_name, timestamp)

    with open(output_path, "w") as f:
        f.write(html)

    return output_path


def _downsample_factor(n, max_points=500):
    if n <= max_points:
        return 1
    return max(1, n // max_points)


def _config_summary(cfg):
    """Extract key config params for display."""
    corridor = cfg["corridors"][0]
    return {
        "corridor_id": corridor["id"],
        "corridor_length_km": corridor["length_m"] / 1000,
        "num_lanes": corridor["num_lanes"],
        "altitude_m": corridor["altitude_m"],
        "num_uams": cfg["uams"]["num_uams"],
        "speed_range_mps": cfg["uams"]["speed_mps"],
        "T_sep_min_s": cfg["uams"]["T_sep_min_s"],
        "sep_time_min_s": cfg["thresholds"]["sep_time_min_s"],
        "num_base_stations": len(cfg["base_stations"]),
        "bs_capacity_mbps": cfg["base_stations"][0]["capacity_bps"] / 1e6,
        "bsm_rate_hz": cfg["traffic"]["bsm_rate_hz"],
        "hotl_rate_kbps": cfg["traffic"]["hotl_rate_bps"] / 1000,
        "hwtl_rate_mbps": cfg["traffic"]["hwtl_rate_bps"] / 1e6,
        "RTT_max_ms": cfg["traffic"]["RTT_max_s"] * 1000,
        "mode_switch_model": cfg["mode_switch"]["model"],
        "lambda_per_hour": cfg["mode_switch"]["lambda_per_hour"],
        "handoff_delay_ms": cfg["handoff"]["delay_s"] * 1000,
        "handoff_p_drop": cfg["handoff"]["p_drop"],
        "sim_duration_s": cfg["simulation"]["t_end"] - cfg["simulation"]["t_start"],
        "dt_s": cfg["simulation"]["dt"],
        "random_seed": cfg["simulation"]["random_seed"],
        "load_warning": cfg["thresholds"]["load_warning"],
        "load_critical": cfg["thresholds"]["load_critical"],
    }


def _build_rationale(summary, cfg):
    """Build a structured rationale explaining the scenario classification."""
    thresholds = cfg["thresholds"]
    traffic = cfg["traffic"]

    checks = []

    # 1. Separation time
    min_sep = summary.get("min_separation_time_s", float("inf"))
    sep_thresh = thresholds["sep_time_min_s"]
    sep_ok = min_sep >= sep_thresh
    checks.append({
        "label": "Min Separation Time",
        "measured": f"{min_sep:.2f} s" if min_sep < 9999 else "N/A",
        "threshold": f"≥ {sep_thresh} s",
        "pass": sep_ok,
        "detail": (
            f"Observed {summary.get('total_separation_violations', 0)} step(s) with separation below {sep_thresh} s. "
            "Separation time = gap / follower velocity. Values below threshold indicate insufficient "
            "braking margin and risk of near mid-air collision (NMAC)."
            if not sep_ok else
            f"All observed separation times ≥ {sep_thresh} s."
        ),
    })

    # 2. Max RTT
    max_rtt_ms = summary.get("max_rtt_s", 0) * 1000
    rtt_thresh_ms = traffic["RTT_max_s"] * 1000
    rtt_ok = max_rtt_ms <= rtt_thresh_ms
    checks.append({
        "label": "Max Round-Trip Time (RTT)",
        "measured": f"{max_rtt_ms:.1f} ms",
        "threshold": f"≤ {rtt_thresh_ms:.0f} ms",
        "pass": rtt_ok,
        "detail": (
            f"Peak RTT of {max_rtt_ms:.1f} ms exceeds the {rtt_thresh_ms:.0f} ms safety limit "
            "(sourced from FY26 ASU Proposal edge-attribute table). "
            "Above this limit, HWTL pilot commands and DAA responses may expire before delivery."
            if not rtt_ok else
            f"Peak RTT of {max_rtt_ms:.1f} ms is within the {rtt_thresh_ms:.0f} ms limit."
        ),
    })

    # 3. Overall drop rate
    drop_rate = summary.get("drop_rate", 0)
    drop_ok = drop_rate < 0.05
    checks.append({
        "label": "Message Drop Rate",
        "measured": f"{drop_rate * 100:.2f}%",
        "threshold": "< 5%",
        "pass": drop_ok,
        "detail": (
            f"Drop rate of {drop_rate*100:.2f}% exceeds the 5% acceptable limit. "
            "Drops result from BS buffer overflow (arrivals > buffer_capacity_msgs) and "
            "handoff-period packet loss. Safety-critical BSM and control messages may be lost."
            if not drop_ok else
            f"Drop rate of {drop_rate*100:.2f}% is within the 5% acceptable limit."
        ),
    })

    # 4. BS hotspot analysis
    bs_data = summary.get("bs", {})
    worst_bs = max(bs_data.items(), key=lambda x: x[1]["max_load"], default=(None, {}))
    worst_id, worst_info = worst_bs
    load_crit = thresholds["load_critical"]
    bs_ok = worst_info.get("max_load", 0) <= load_crit
    checks.append({
        "label": f"Peak BS Load ({worst_id or 'N/A'})",
        "measured": f"{worst_info.get('max_load', 0)*100:.1f}%",
        "threshold": f"≤ {load_crit*100:.0f}%",
        "pass": bs_ok,
        "detail": (
            f"{worst_id} reached {worst_info.get('max_load',0)*100:.1f}% load "
            f"and accumulated {worst_info.get('total_drops',0):,} dropped messages. "
            f"This BS spent {worst_info.get('time_in_red_frac',0)*100:.1f}% of the simulation above the "
            f"{load_crit*100:.0f}% critical threshold. Per the M/M/1 model, "
            "queueing delay grows as 1/(1−ρ) — approaching saturation causes exponential latency growth "
            "and buffer overflow (CascadeFailureScenario.docx §Key Simplification)."
            if not bs_ok else
            f"Highest loaded BS ({worst_id}) peaked at {worst_info.get('max_load',0)*100:.1f}%, "
            f"below the {load_crit*100:.0f}% critical threshold."
        ),
    })

    # 5. RTT safety violations (steps above RTT_max)
    rtt_max_ms = traffic["RTT_max_s"] * 1000
    # We derive violation rate from avg vs max — approximation since we don't
    # store step-by-step counts here; the summary carries max_rtt_s already.
    rtt_crit_ok = summary.get("max_rtt_s", 0) <= traffic["RTT_max_s"]
    # Check for severe violation (> 2× limit indicates saturation)
    rtt_severe = summary.get("max_rtt_s", 0) > 2 * traffic["RTT_max_s"]
    checks.append({
        "label": "RTT Safety Threshold Violations",
        "measured": f"{summary.get('max_rtt_s', 0)*1000:.0f} ms peak",
        "threshold": f"≤ {rtt_max_ms:.0f} ms",
        "pass": rtt_crit_ok,
        "detail": (
            f"Peak RTT reached {summary.get('max_rtt_s',0)*1000:.0f} ms — "
            f"{'more than 2×' if rtt_severe else ''} the {rtt_max_ms:.0f} ms operational limit. "
            "This is a direct consequence of M/M/1 queuing saturation: as BS load ρ → 1, "
            "queuing delay grows as L_min/(1−ρ) → ∞. "
            "At saturation (ρ=1.0) RTT becomes unbounded; "
            "HWTL pilot commands and DAA responses expire before delivery "
            "(CascadeFailureScenario.docx §3.6 'Failure Threshold Breach')."
            if not rtt_crit_ok else
            f"Peak RTT of {summary.get('max_rtt_s',0)*1000:.0f} ms is within the {rtt_max_ms:.0f} ms limit."
        ),
    })

    # 6. Time in red zone (any BS)
    max_time_red = max(
        (v.get("time_in_red_frac", 0) for v in bs_data.values()), default=0
    )
    red_bs = [k for k, v in bs_data.items() if v.get("time_in_red_frac", 0) > 0.1]
    red_ok = max_time_red <= 0.10
    checks.append({
        "label": "BS Time in Red Zone",
        "measured": f"{max_time_red*100:.1f}% (worst BS)",
        "threshold": "≤ 10% of run",
        "pass": red_ok,
        "detail": (
            f"Base station(s) {', '.join(red_bs)} spent more than 10% of the simulation above the "
            f"critical load threshold. Sustained overload prevents timely delivery of "
            "time-sensitive HWTL video and C2 command messages."
            if not red_ok else
            "No base station spent more than 10% of the simulation above the critical load threshold."
        ),
    })

    # Overall verdict
    cls = summary.get("classification", "normal")
    verdict_map = {
        "normal": "All safety and performance thresholds satisfied.",
        "degraded": "Communication quality is degraded (high drop rate or BS overload) but safety separation margins are maintained.",
        "unsafe": "One or more safety-critical thresholds are violated — this configuration is NOT acceptable for operational deployment.",
    }

    return {
        "classification": cls,
        "verdict": verdict_map.get(cls, ""),
        "checks": checks,
    }


def _build_html(scenarios_data, title, timestamp):
    """Build the complete HTML string."""
    data_json = json.dumps(scenarios_data, default=_json_default)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(title)}</title>
<style>
{_CSS}
</style>
</head>
<body>
<div id="app">
  <header>
    <h1>{_esc(title)}</h1>
    <p class="subtitle">Generated: {timestamp} | Scenarios: {len(scenarios_data)}</p>
    <div class="scenario-selector" id="scenarioSelector"></div>
  </header>

  <section id="configSection" class="card collapsible">
    <h2 onclick="toggleSection('configContent')">Configuration Summary &#x25BC;</h2>
    <div id="configContent" class="content"></div>
  </section>

  <section id="summarySection" class="card">
    <h2>Results Summary</h2>
    <div id="summaryContent"></div>
  </section>

  <section id="narrativeSection" class="card" style="display:none">
    <h2>Scenario Overview</h2>
    <div id="narrativeContent"></div>
  </section>

  <section id="rationaleSection" class="card">
    <h2>Classification Rationale</h2>
    <div id="rationaleContent"></div>
  </section>

  <section class="card">
    <h2>Time Series</h2>
    <div class="chart-controls">
      <label><input type="checkbox" checked data-series="uams"> UAMs Active</label>
      <label><input type="checkbox" checked data-series="hwtl"> HWTL Count</label>
      <label><input type="checkbox" checked data-series="sep"> Min Separation (s)</label>
      <label><input type="checkbox" checked data-series="rtt"> Mean RTT (ms)</label>
      <label><input type="checkbox" checked data-series="maxrtt"> Max RTT (ms)</label>
      <label><input type="checkbox" data-series="p95rtt"> P95 RTT (ms)</label>
      <label><input type="checkbox" checked data-series="droprate"> Drop Rate (%)</label>
      <label><input type="checkbox" data-series="drops"> Msgs Dropped/Step</label>
      <label><input type="checkbox" data-series="sepviol"> Sep Violations/Step</label>
      <label><input type="checkbox" data-series="nocov"> No-Coverage Count</label>
      <label><input type="checkbox" data-series="handoffs"> Handoffs/Step</label>
    </div>
    <div id="timeSeriesCharts"></div>
  </section>

  <section class="card">
    <h2>BS Load Factor</h2>
    <div class="chart-controls">
      <select id="bsSelector"></select>
    </div>
    <div id="bsLoadChart"></div>
  </section>

  <section class="card">
    <h2>Distributions</h2>
    <div class="hist-row">
      <div id="rttHistogram" class="hist-container">
        <h3>RTT Distribution</h3>
      </div>
      <div id="sepHistogram" class="hist-container">
        <h3>Separation Time Distribution</h3>
      </div>
    </div>
  </section>

  <section class="card">
    <h2>Base Station Summary</h2>
    <div id="bsTable"></div>
  </section>

  <section class="card">
    <h2>Spatial Corridor View</h2>
    <div class="slider-container">
      <input type="range" id="timeSlider" min="0" max="0" value="0">
      <span id="timeLabel">t = 0.0s</span>
      <button id="playBtn" onclick="togglePlay()">&#9654; Play</button>
    </div>
    <div id="spatialView"></div>
    <div id="spatialTooltip" class="tooltip"></div>
  </section>

  <section class="card" id="spaceTimeSection">
    <h2>Time–Space Diagram</h2>
    <div id="spaceTimeTabs" class="tab-bar" style="display:none"></div>
    <div id="spaceTimeChart"></div>
  </section>

  <section class="card" id="comparisonSection" style="display:none">
    <h2>Scenario Comparison</h2>
    <div id="comparisonCharts"></div>
  </section>
</div>

<script>
const DATA = {data_json};
let currentScenario = 0;
let playInterval = null;
let _stLane = 0;
let _stTrajs = null;
let _stZoom = null;      // null = full view; {{t0, t1, pos0, pos1}} when zoomed
let _stDragStart = null; // {{svgX, svgY}} when drag in progress

// --- Initialization ---
function init() {{
  buildScenarioSelector();
  loadScenario(0);
  if (DATA.length > 1) {{
    document.getElementById('comparisonSection').style.display = 'block';
    renderComparison();
  }}

  // Wire up chart toggles
  document.querySelectorAll('.chart-controls input[type=checkbox]').forEach(cb => {{
    cb.addEventListener('change', () => renderTimeSeries());
  }});
  document.getElementById('bsSelector').addEventListener('change', () => renderBSLoad());
  document.getElementById('timeSlider').addEventListener('input', (e) => {{
    renderSpatial(parseInt(e.target.value));
  }});
  // Cancel space-time zoom drag if mouse released outside SVG
  window.addEventListener('mouseup', () => {{
    if (_stDragStart) stDragCancel();
  }});
}}

function buildScenarioSelector() {{
  const el = document.getElementById('scenarioSelector');
  if (DATA.length <= 1) return;
  DATA.forEach((s, i) => {{
    const btn = document.createElement('button');
    btn.textContent = s.name;
    btn.className = 'scenario-btn' + (i === 0 ? ' active' : '');
    btn.onclick = () => {{
      document.querySelectorAll('.scenario-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      loadScenario(i);
    }};
    el.appendChild(btn);
  }});
}}

function loadScenario(idx) {{
  currentScenario = idx;
  _stLane = 0;
  _stZoom = null;
  const s = DATA[idx];
  renderConfig(s.config);
  renderSummary(s.summary);
  renderNarrative(s.narrative);
  renderRationale(s.rationale);
  renderTimeSeries();
  populateBSSelector(s);
  renderBSLoad();
  renderHistograms(s);
  renderBSTable(s);
  setupSpatial(s);
  renderSpaceTime();
}}

// --- Narrative ---
function renderNarrative(text) {{
  const section = document.getElementById('narrativeSection');
  const el = document.getElementById('narrativeContent');
  if (!text) {{
    section.style.display = 'none';
    el.innerHTML = '';
    return;
  }}
  section.style.display = '';
  el.innerHTML = `<p class="narrative-text">${{text}}</p>`;
}}

// --- Config ---
function renderConfig(cfg) {{
  const el = document.getElementById('configContent');
  let html = '<table class="config-table">';
  const labels = {{
    corridor_id: 'Corridor', corridor_length_km: 'Length (km)',
    num_lanes: 'Lanes', altitude_m: 'Altitude (m)',
    num_uams: 'UAM Count', speed_range_mps: 'Speed Range (m/s)',
    T_sep_min_s: 'CF Time Gap τ_min (s)', sep_time_min_s: 'Sep Violation Threshold (s)', num_base_stations: 'Base Stations',
    bs_capacity_mbps: 'BS Capacity (Mbps)', bsm_rate_hz: 'BSM Rate (Hz)',
    hotl_rate_kbps: 'HOTL Rate (kbps)', hwtl_rate_mbps: 'HWTL Rate (Mbps)',
    RTT_max_ms: 'RTT Max (ms)', mode_switch_model: 'Mode Switch Model',
    lambda_per_hour: 'Switch Rate (/hr)', handoff_delay_ms: 'Handoff Delay (ms)',
    handoff_p_drop: 'Handoff Drop Prob', sim_duration_s: 'Duration (s)',
    dt_s: 'Time Step (s)', random_seed: 'Random Seed',
    load_warning: 'Load Warning', load_critical: 'Load Critical',
  }};
  for (const [k, label] of Object.entries(labels)) {{
    let v = cfg[k];
    if (Array.isArray(v)) v = v.join(' - ');
    if (typeof v === 'number') v = Number.isInteger(v) ? v : v.toFixed(3);
    html += `<tr><td>${{label}}</td><td>${{v}}</td></tr>`;
  }}
  html += '</table>';
  el.innerHTML = html;
}}

// --- Summary ---
function renderSummary(summary) {{
  const el = document.getElementById('summaryContent');
  const cls = summary.classification;
  const clsColor = cls === 'normal' ? '#2ecc71' : cls === 'degraded' ? '#f39c12' : '#e74c3c';
  let html = `<div class="summary-badge" style="background:${{clsColor}}">${{cls.toUpperCase()}}</div>`;
  html += '<div class="summary-grid">';
  html += _summaryCard('Avg RTT', (summary.avg_rtt_s * 1000).toFixed(1) + ' ms');
  html += _summaryCard('Max RTT', (summary.max_rtt_s * 1000).toFixed(1) + ' ms');
  html += _summaryCard('Min Separation', summary.min_separation_time_s !== undefined ?
    summary.min_separation_time_s.toFixed(1) + ' s' : 'N/A');
  html += _summaryCard('Drop Rate', (summary.drop_rate * 100).toFixed(2) + '%');
  html += _summaryCard('Mode Switches', summary.total_mode_switches);
  html += _summaryCard('Sep Violations', summary.total_separation_violations);
  html += '</div>';
  el.innerHTML = html;
}}

function _summaryCard(label, value) {{
  return `<div class="summary-card"><div class="sc-value">${{value}}</div><div class="sc-label">${{label}}</div></div>`;
}}

// --- Classification Rationale ---
function renderRationale(rationale) {{
  const el = document.getElementById('rationaleContent');
  if (!rationale) {{ el.innerHTML = ''; return; }}

  const cls = rationale.classification;
  const clsColor = cls === 'normal' ? '#2ecc71' : cls === 'degraded' ? '#f39c12' : '#e74c3c';
  const clsIcon = cls === 'normal' ? '✅' : cls === 'degraded' ? '⚠️' : '🚨';

  let html = `<div class="rationale-verdict" style="border-left:4px solid ${{clsColor}};padding:10px 14px;background:#fafafa;border-radius:4px;margin-bottom:14px">
    <span style="font-size:1.2em">${{clsIcon}}</span>
    <strong style="color:${{clsColor}};text-transform:uppercase;margin-left:6px">${{cls}}</strong>
    <span style="color:#555;margin-left:10px">${{rationale.verdict}}</span>
  </div>`;

  html += '<div class="check-grid">';
  rationale.checks.forEach(check => {{
    const ok = check.pass;
    const rowColor = ok ? '#f0fdf4' : cls === 'degraded' ? '#fffbeb' : '#fef2f2';
    const borderColor = ok ? '#86efac' : cls === 'degraded' ? '#fde68a' : '#fca5a5';
    const icon = ok ? '✅' : '❌';
    html += `<div class="check-row" style="background:${{rowColor}};border:1px solid ${{borderColor}};border-radius:6px;padding:10px 14px;margin-bottom:8px">
      <div class="check-header">
        <span class="check-icon">${{icon}}</span>
        <strong class="check-label">${{check.label}}</strong>
        <span class="check-measured" style="color:${{ok?'#16a34a':'#dc2626'}}">${{check.measured}}</span>
        <span class="check-threshold">(threshold: ${{check.threshold}})</span>
      </div>
      <div class="check-detail">${{check.detail}}</div>
    </div>`;
  }});
  html += '</div>';

  el.innerHTML = html;
}}

// --- Time Series Charts (SVG) ---
function renderTimeSeries() {{
  const s = DATA[currentScenario];
  const el = document.getElementById('timeSeriesCharts');
  el.innerHTML = '';

  // Pull safety thresholds from scenario config
  const sepThresh  = s.config.sep_time_min_s;         // violation threshold (2.0 s), NOT the CF time gap (T_sep_min_s)
  const rttThresh  = s.config.RTT_max_ms;             // e.g. 500 ms
  const dropThresh = 5.0;                             // 5 % operational limit

  const rttThreshOpts = {{ thresholds: [{{ value: rttThresh, color: '#e74c3c', label: rttThresh + 'ms' }}] }};
  const sepThreshOpts  = {{ thresholds: [{{ value: sepThresh,  color: '#e74c3c', label: sepThresh + 's'  }}] }};
  const dropThreshOpts = {{ thresholds: [{{ value: dropThresh, color: '#e74c3c', label: '5%' }}], yMin: 0 }};

  // Per-step drop rate (%)
  const dropRateData = s.total_msgs_dropped.map((d, i) => {{
    const total = d + (s.total_msgs_processed[i] || 0);
    return total > 0 ? (d / total) * 100 : 0;
  }});

  const series = [];
  const checks = document.querySelectorAll('.chart-controls input[type=checkbox]');
  checks.forEach(cb => {{
    if (!cb.checked) return;
    const key = cb.dataset.series;
    if (key === 'uams')
      series.push({{ data: s.num_uams_active, label: 'UAMs Active', color: '#3498db', opts: {{}} }});
    if (key === 'hwtl')
      series.push({{ data: s.num_uams_hwtl, label: 'HWTL Count', color: '#e74c3c', opts: {{}} }});
    if (key === 'sep')
      series.push({{ data: s.min_separation_time, label: 'Min Separation Time (s)', color: '#2ecc71', opts: sepThreshOpts }});
    if (key === 'rtt')
      series.push({{ data: s.mean_rtt.map(v => v * 1000), label: 'Mean RTT (ms)', color: '#9b59b6', opts: rttThreshOpts }});
    if (key === 'maxrtt')
      series.push({{ data: s.max_rtt.map(v => v * 1000), label: 'Max RTT (ms)', color: '#c0392b', opts: rttThreshOpts }});
    if (key === 'p95rtt')
      series.push({{ data: s.p95_rtt.map(v => v * 1000), label: 'P95 RTT (ms)', color: '#e67e22', opts: rttThreshOpts }});
    if (key === 'droprate')
      series.push({{ data: dropRateData, label: 'Drop Rate (%)', color: '#e74c3c', opts: dropThreshOpts }});
    if (key === 'drops')
      series.push({{ data: s.total_msgs_dropped, label: 'Msgs Dropped/Step', color: '#f39c12', opts: {{}} }});
    if (key === 'sepviol')
      series.push({{ data: s.separation_violations, label: 'Separation Violations/Step', color: '#e74c3c',
        opts: {{ yMin: 0, thresholds: [{{ value: 0.5, color: '#e74c3c', label: 'zero-tol', dash: '3,2' }}] }} }});
    if (key === 'nocov')
      series.push({{ data: s.no_coverage_count, label: 'No-Coverage Count/Step', color: '#e67e22', opts: {{ yMin: 0 }} }});
    if (key === 'handoffs')
      series.push({{ data: s.handoff_count, label: 'Handoffs/Step', color: '#1abc9c', opts: {{ yMin: 0 }} }});
  }});

  const events = s.ext_load_events || [];
  series.forEach(sr => {{
    const div = document.createElement('div');
    div.className = 'ts-chart';
    div.innerHTML = `<h4>${{sr.label}}</h4>` +
      svgLineChart(s.time, sr.data, sr.color, 700, 150, sr.opts, events);
    el.appendChild(div);
  }});
}}

function svgLineChart(times, values, color, w, h, opts, extEvents) {{
  opts = opts || {{}};
  extEvents = extEvents || [];
  const pad = {{ top: 20, right: 46, bottom: 30, left: 55 }};
  const cw = w - pad.left - pad.right;
  const ch = h - pad.top - pad.bottom;

  const tMin = times[0], tMax = times[times.length - 1];
  let vMin = opts.yMin !== undefined ? opts.yMin : Math.min(...values);
  let vMax = opts.yMax !== undefined ? opts.yMax : Math.max(...values);

  // Extend vMax so every threshold line stays visible in the plot area
  if (opts.thresholds && opts.yMax === undefined) {{
    const maxTh = Math.max(...opts.thresholds.map(t => t.value));
    if (maxTh > vMax) vMax = maxTh * 1.08;
  }}
  if (vMin === vMax) {{ vMax = vMin + 1; }}
  const yRange = vMax - vMin;

  const sx = (t) => pad.left + ((t - tMin) / (tMax - tMin || 1)) * cw;
  const sy = (v) => pad.top + ch - ((v - vMin) / yRange) * ch;

  // Shaded regions for external load events
  let regions = '';
  extEvents.forEach(ev => {{
    const x1 = sx(Math.max(ev.t_start, tMin)).toFixed(1);
    const x2 = sx(Math.min(ev.t_end,   tMax)).toFixed(1);
    if (parseFloat(x2) <= parseFloat(x1)) return;
    regions += `<rect x="${{x1}}" y="${{pad.top}}" width="${{(parseFloat(x2)-parseFloat(x1)).toFixed(1)}}"
      height="${{ch}}" fill="#f97316" opacity="0.10" rx="2">
      <title>${{ev.label}} (+${{ev.load_mbps.toFixed(0)}} Mbps/BS, t=${{ev.t_start}}–${{ev.t_end}}s)</title></rect>`;
    regions += `<line x1="${{x1}}" y1="${{pad.top}}" x2="${{x1}}" y2="${{pad.top+ch}}"
      stroke="#f97316" stroke-width="1" stroke-dasharray="4,3" opacity="0.6"/>`;
    regions += `<line x1="${{x2}}" y1="${{pad.top}}" x2="${{x2}}" y2="${{pad.top+ch}}"
      stroke="#f97316" stroke-width="1" stroke-dasharray="4,3" opacity="0.6"/>`;
    const mid = ((parseFloat(x1)+parseFloat(x2))/2).toFixed(1);
    regions += `<text x="${{mid}}" y="${{pad.top - 4}}" text-anchor="middle"
      font-size="9" fill="#f97316" font-weight="600">Terrestrial surge</text>`;
  }});

  let path = '';
  for (let i = 0; i < times.length; i++) {{
    const x = sx(times[i]).toFixed(1);
    const y = sy(Math.min(Math.max(values[i], vMin), vMax)).toFixed(1);
    path += (i === 0 ? 'M' : 'L') + x + ',' + y;
  }}

  // Y axis ticks
  const nTicks = 5;
  let yTicks = '';
  for (let i = 0; i <= nTicks; i++) {{
    const v = vMin + (yRange * i / nTicks);
    const y = sy(v).toFixed(1);
    yTicks += `<line x1="${{pad.left}}" y1="${{y}}" x2="${{pad.left + cw}}" y2="${{y}}" stroke="#eee"/>`;
    yTicks += `<text x="${{pad.left - 5}}" y="${{y}}" text-anchor="end" dy="4" class="tick">${{fmtNum(v)}}</text>`;
  }}

  // X axis ticks
  let xTicks = '';
  const nXTicks = 6;
  for (let i = 0; i <= nXTicks; i++) {{
    const t = tMin + ((tMax - tMin) * i / nXTicks);
    const x = sx(t).toFixed(1);
    xTicks += `<text x="${{x}}" y="${{h - 5}}" text-anchor="middle" class="tick">${{fmtTime(t)}}</text>`;
  }}

  // Horizontal threshold lines (rendered above grid, below data)
  let threshLines = '';
  if (opts.thresholds) {{
    opts.thresholds.forEach(th => {{
      if (th.value < vMin || th.value > vMax) return; // out of visible range
      const y = sy(th.value).toFixed(1);
      const dash = th.dash || '5,3';
      threshLines += `<line x1="${{pad.left}}" y1="${{y}}" x2="${{pad.left + cw}}" y2="${{y}}"
        stroke="${{th.color}}" stroke-width="1.5" stroke-dasharray="${{dash}}" opacity="0.85"/>`;
      threshLines += `<text x="${{pad.left + cw + 4}}" y="${{parseFloat(y) + 4}}"
        font-size="9" fill="${{th.color}}" font-weight="600">${{th.label}}</text>`;
    }});
  }}

  // Hover overlay
  const hoverRect = `<rect class="hover-zone" x="${{pad.left}}" y="${{pad.top}}" width="${{cw}}" height="${{ch}}"
    fill="transparent" onmousemove="showTip(evt,this)" onmouseleave="hideTip(evt)"/>`;

  return `<svg width="${{w}}" height="${{h}}" class="chart-svg" data-times='${{JSON.stringify(times.map(t=>+t.toFixed(2)))}}'
    data-values='${{JSON.stringify(values.map(v=>+v.toFixed(4)))}}'>
    ${{regions}}${{yTicks}}${{xTicks}}${{threshLines}}
    <path d="${{path}}" fill="none" stroke="${{color}}" stroke-width="1.5"/>
    ${{hoverRect}}
    <line class="crosshair" x1="0" y1="0" x2="0" y2="0" stroke="#999" stroke-dasharray="3"/>
    <text class="tip-text" x="0" y="0" font-size="11"></text>
  </svg>`;
}}

function fmtNum(v) {{
  if (Math.abs(v) >= 1000) return (v/1000).toFixed(1) + 'k';
  if (Math.abs(v) >= 1) return v.toFixed(1);
  return v.toFixed(3);
}}

function fmtTime(t) {{
  if (t >= 3600) return (t/3600).toFixed(1) + 'h';
  if (t >= 60) return (t/60).toFixed(1) + 'm';
  return t.toFixed(0) + 's';
}}

function showTip(evt, rect) {{
  const svg = rect.closest('svg');
  const times = JSON.parse(svg.dataset.times);
  const values = JSON.parse(svg.dataset.values);
  const pt = svg.createSVGPoint();
  pt.x = evt.clientX; pt.y = evt.clientY;
  const svgP = pt.matrixTransform(svg.getScreenCTM().inverse());
  const pad = 55;
  const cw = 700 - 55 - 46;
  const frac = (svgP.x - pad) / cw;
  const idx = Math.max(0, Math.min(times.length - 1, Math.round(frac * (times.length - 1))));
  const line = svg.querySelector('.crosshair');
  line.setAttribute('x1', svgP.x); line.setAttribute('x2', svgP.x);
  line.setAttribute('y1', 20); line.setAttribute('y2', 150 - 30);
  const tip = svg.querySelector('.tip-text');
  tip.setAttribute('x', svgP.x + 5); tip.setAttribute('y', 15);
  tip.textContent = `t=${{fmtTime(times[idx])}} v=${{fmtNum(values[idx])}}`;
}}

function hideTip(evt) {{
  const svg = evt.target.closest('svg');
  svg.querySelector('.crosshair').setAttribute('x1', -10);
  svg.querySelector('.tip-text').textContent = '';
}}

// --- BS Load Chart ---
function populateBSSelector(s) {{
  const sel = document.getElementById('bsSelector');
  sel.innerHTML = '';
  Object.keys(s.bs_load_factor).forEach(bsId => {{
    const opt = document.createElement('option');
    opt.value = bsId; opt.textContent = bsId;
    sel.appendChild(opt);
  }});
}}

function renderBSLoad() {{
  const s = DATA[currentScenario];
  const bsId = document.getElementById('bsSelector').value;
  const el = document.getElementById('bsLoadChart');
  if (!bsId || !s.bs_load_factor[bsId]) {{ el.innerHTML = ''; return; }}

  const loadData  = s.bs_load_factor[bsId];
  const delayData = s.bs_queue_delay[bsId];
  const events    = s.ext_load_events || [];
  const W = 700, H = 150;

  const loadOpts = {{
    yMin: 0, yMax: 1,
    thresholds: [
      {{ value: s.config.load_warning, color: '#f39c12', label: (s.config.load_warning * 100).toFixed(0) + '% warn' }},
      {{ value: s.config.load_critical, color: '#e74c3c', label: (s.config.load_critical * 100).toFixed(0) + '% crit' }},
    ],
  }};

  el.innerHTML =
    '<h4>Load Factor (ρ) — warning at ' + (s.config.load_warning * 100).toFixed(0) +
    '%, critical at ' + (s.config.load_critical * 100).toFixed(0) + '%</h4>' +
    svgLineChart(s.time, loadData, '#e74c3c', W, H, loadOpts, events) +
    '<h4>Queue Delay (s) — M/M/1: delay = L_min / (1−ρ)</h4>' +
    svgLineChart(s.time, delayData, '#3498db', W, H, {{}}, events);
}}

// --- Histograms ---
function renderHistograms(s) {{
  document.getElementById('rttHistogram').innerHTML =
    '<h3>RTT Distribution</h3>' + svgHistogram(s.rtt_samples.map(v => v * 1000), 'ms', '#9b59b6', 340, 200);
  document.getElementById('sepHistogram').innerHTML =
    '<h3>Separation Time Distribution</h3>' + svgHistogram(s.separation_samples, 's', '#2ecc71', 340, 200);
}}

function svgHistogram(data, unit, color, w, h) {{
  if (!data || data.length === 0) return '<p>No data</p>';
  const pad = {{ top: 15, right: 15, bottom: 30, left: 50 }};
  const cw = w - pad.left - pad.right;
  const ch = h - pad.top - pad.bottom;

  // Compute bins
  const sorted = [...data].sort((a,b) => a - b);
  const lo = sorted[0];
  const hi = sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.99))];
  const nBins = 25;
  const binW = (hi - lo) / nBins || 1;
  const bins = new Array(nBins).fill(0);
  data.forEach(v => {{
    const idx = Math.min(nBins - 1, Math.max(0, Math.floor((v - lo) / binW)));
    bins[idx]++;
  }});
  const maxCount = Math.max(...bins);

  let bars = '';
  const barW = cw / nBins;
  bins.forEach((count, i) => {{
    const bh = (count / maxCount) * ch;
    const x = pad.left + i * barW;
    const y = pad.top + ch - bh;
    bars += `<rect x="${{x.toFixed(1)}}" y="${{y.toFixed(1)}}" width="${{(barW - 1).toFixed(1)}}"
      height="${{bh.toFixed(1)}}" fill="${{color}}" opacity="0.8">
      <title>${{(lo + i * binW).toFixed(2)}}${{unit}}: ${{count}}</title></rect>`;
  }});

  // X axis
  let xTicks = '';
  for (let i = 0; i <= 5; i++) {{
    const v = lo + (hi - lo) * i / 5;
    const x = pad.left + (i / 5) * cw;
    xTicks += `<text x="${{x.toFixed(1)}}" y="${{h - 5}}" text-anchor="middle" class="tick">${{fmtNum(v)}}</text>`;
  }}

  return `<svg width="${{w}}" height="${{h}}" class="chart-svg">
    ${{bars}}${{xTicks}}
    <text x="${{w/2}}" y="${{h}}" text-anchor="middle" class="tick">${{unit}}</text>
  </svg>`;
}}

// --- BS Table ---
function renderBSTable(s) {{
  const el = document.getElementById('bsTable');
  let html = '<table class="data-table"><thead><tr><th>BS ID</th><th>Avg Load</th><th>Max Load</th><th>Drops</th><th>Time in Red</th><th>Status</th></tr></thead><tbody>';
  const bsSummary = s.bs_summary || {{}};
  Object.entries(bsSummary).forEach(([bsId, info]) => {{
    const status = info.max_load > 0.85 ? '🔴' : info.max_load > 0.6 ? '🟡' : '🟢';
    html += `<tr><td>${{bsId}}</td><td>${{(info.avg_load * 100).toFixed(1)}}%</td>
      <td>${{(info.max_load * 100).toFixed(1)}}%</td><td>${{info.total_drops}}</td>
      <td>${{(info.time_in_red_frac * 100).toFixed(1)}}%</td><td>${{status}}</td></tr>`;
  }});
  html += '</tbody></table>';
  el.innerHTML = html;
}}

// --- Spatial View ---
function setupSpatial(s) {{
  const slider = document.getElementById('timeSlider');
  slider.max = s.spatial_snapshots.length - 1;
  slider.value = 0;
  renderSpatial(0);
}}

function renderSpatial(idx) {{
  const s = DATA[currentScenario];
  const snaps = s.spatial_snapshots;
  if (!snaps || snaps.length === 0) return;
  idx = Math.max(0, Math.min(idx, snaps.length - 1));
  const snap = snaps[idx];
  document.getElementById('timeLabel').textContent = `t = ${{snap.t.toFixed(1)}}s`;

  const w = 750, h = 200;
  const pad = {{ left: 40, right: 20, top: 30, bottom: 40 }};
  const cw = w - pad.left - pad.right;
  const ch = h - pad.top - pad.bottom;
  const L = s.corridor_length;
  const sx = (pos) => pad.left + (pos / L) * cw;

  // Corridor line
  let svg = `<svg width="${{w}}" height="${{h}}" class="spatial-svg">`;
  svg += `<line x1="${{pad.left}}" y1="${{h/2}}" x2="${{pad.left + cw}}" y2="${{h/2}}" stroke="#bdc3c7" stroke-width="3"/>`;

  // BS markers
  s.base_stations.forEach(bs => {{
    const x = sx(bs.x);
    const load = snap.bs_loads[bs.id] || 0;
    const color = load > 0.85 ? '#e74c3c' : load > 0.6 ? '#f39c12' : '#2ecc71';
    svg += `<rect x="${{x-6}}" y="${{h/2 + 15}}" width="12" height="12" fill="${{color}}" rx="2">
      <title>${{bs.id}}: load=${{(load*100).toFixed(1)}}%</title></rect>`;
    svg += `<text x="${{x}}" y="${{h/2 + 40}}" text-anchor="middle" class="tick">${{bs.id.replace('BS','')}}</text>`;
  }});

  // UAM dots
  snap.uams.forEach(uam => {{
    const x = sx(uam.pos);
    const y = h/2 - 10 - uam.lane * 15;
    const color = uam.mode === 'HWTL' ? '#e74c3c' : '#3498db';
    const stroke = uam.handoff ? '#f39c12' : 'none';
    svg += `<circle cx="${{x.toFixed(1)}}" cy="${{y}}" r="4" fill="${{color}}" stroke="${{stroke}}" stroke-width="2"
      onmouseover="showSpatialTip(evt,'${{uam.id}}','${{uam.mode}}','${{uam.bs}}','${{uam.pos.toFixed(0)}}m')"
      onmouseout="hideSpatialTip()">
      <title>${{uam.id}} (${{uam.mode}}) @ ${{uam.pos.toFixed(0)}}m -> ${{uam.bs}}</title></circle>`;

    // Line to serving BS
    if (uam.bs) {{
      const bsObj = s.base_stations.find(b => b.id === uam.bs);
      if (bsObj) {{
        const bx = sx(bsObj.x);
        svg += `<line x1="${{x.toFixed(1)}}" y1="${{y}}" x2="${{bx.toFixed(1)}}" y2="${{h/2 + 15}}" stroke="${{color}}" stroke-width="0.5" opacity="0.3"/>`;
      }}
    }}
  }});

  // Legend
  svg += `<circle cx="${{pad.left}}" cy="15" r="4" fill="#3498db"/><text x="${{pad.left+8}}" y="19" class="tick">HOTL</text>`;
  svg += `<circle cx="${{pad.left+60}}" cy="15" r="4" fill="#e74c3c"/><text x="${{pad.left+68}}" y="19" class="tick">HWTL</text>`;
  svg += `<rect x="${{pad.left+120}}" y="11" width="8" height="8" fill="#2ecc71" rx="1"/><text x="${{pad.left+132}}" y="19" class="tick">BS OK</text>`;
  svg += `<rect x="${{pad.left+180}}" y="11" width="8" height="8" fill="#e74c3c" rx="1"/><text x="${{pad.left+192}}" y="19" class="tick">BS Overloaded</text>`;

  // Hub labels
  svg += `<text x="${{pad.left}}" y="${{h - 5}}" text-anchor="middle" class="tick" font-weight="bold">SF</text>`;
  svg += `<text x="${{pad.left + cw}}" y="${{h - 5}}" text-anchor="middle" class="tick" font-weight="bold">SJ</text>`;

  svg += '</svg>';
  document.getElementById('spatialView').innerHTML = svg;
}}

function showSpatialTip(evt, id, mode, bs, pos) {{
  const tip = document.getElementById('spatialTooltip');
  tip.style.display = 'block';
  tip.style.left = (evt.pageX + 10) + 'px';
  tip.style.top = (evt.pageY - 20) + 'px';
  tip.innerHTML = `<b>${{id}}</b> | Mode: ${{mode}} | BS: ${{bs}} | Pos: ${{pos}}`;
}}

function hideSpatialTip() {{
  document.getElementById('spatialTooltip').style.display = 'none';
}}

function togglePlay() {{
  const slider = document.getElementById('timeSlider');
  const btn = document.getElementById('playBtn');
  if (playInterval) {{
    clearInterval(playInterval);
    playInterval = null;
    btn.innerHTML = '&#9654; Play';
  }} else {{
    btn.innerHTML = '&#9646;&#9646; Pause';
    playInterval = setInterval(() => {{
      let v = parseInt(slider.value) + 1;
      if (v > parseInt(slider.max)) v = 0;
      slider.value = v;
      renderSpatial(v);
    }}, 100);
  }}
}}

// --- Time–Space Diagram ---
function renderSpaceTime() {{
  const s = DATA[currentScenario];
  const snaps = s.spatial_snapshots;
  const tabsEl = document.getElementById('spaceTimeTabs');
  const el = document.getElementById('spaceTimeChart');
  if (!snaps || snaps.length === 0) {{ el.innerHTML = '<p>No data</p>'; return; }}

  // Build per-UAM trajectories from spatial snapshots
  const trajMap = {{}};
  snaps.forEach(snap => {{
    snap.uams.forEach(u => {{
      if (!trajMap[u.id]) trajMap[u.id] = {{lane: u.lane, pts: []}};
      trajMap[u.id].pts.push({{t: snap.t, pos: u.pos, vel: u.vel !== undefined ? u.vel : 0}});
    }});
  }});

  // Group by lane
  const laneMap = {{}};
  Object.values(trajMap).forEach(tr => {{
    const l = tr.lane;
    if (!laneMap[l]) laneMap[l] = [];
    laneMap[l].push(tr);
  }});
  const laneIds = Object.keys(laneMap).map(Number).sort();
  _stTrajs = {{laneMap, laneIds}};

  // Build lane tabs (only when >1 lane)
  tabsEl.innerHTML = '';
  if (laneIds.length > 1) {{
    tabsEl.style.display = 'flex';
    if (!laneIds.includes(_stLane)) _stLane = laneIds[0];
    laneIds.forEach(l => {{
      const btn = document.createElement('button');
      btn.className = 'tab-btn' + (l === _stLane ? ' active' : '');
      btn.textContent = 'Lane ' + l;
      btn.onclick = () => {{
        _stLane = l;
        tabsEl.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        _drawSpaceTime(s);
      }};
      tabsEl.appendChild(btn);
    }});
  }} else {{
    tabsEl.style.display = 'none';
    _stLane = laneIds[0] !== undefined ? laneIds[0] : 0;
  }}
  _drawSpaceTime(s);
}}

function _drawSpaceTime(s) {{
  const el = document.getElementById('spaceTimeChart');
  if (!_stTrajs) {{ el.innerHTML = ''; return; }}
  const {{laneMap, laneIds}} = _stTrajs;
  const laneData = laneMap[_stLane] || [];

  const W = 750, H = 360;
  const pad = {{left: 72, right: 58, top: 20, bottom: 44}};
  const cw = W - pad.left - pad.right;
  const ch = H - pad.top - pad.bottom;
  const L = s.corridor_length;
  const tArr = s.time;
  const tFull0 = tArr[0] || 0;
  const tFull1 = tArr[tArr.length - 1] || 600;
  const vMin = 20;  // fixed colour scale across all scenarios (m/s)
  const vMax = 60;

  // Apply zoom if active
  const tMin   = _stZoom ? _stZoom.t0   : tFull0;
  const tMax   = _stZoom ? _stZoom.t1   : tFull1;
  const posMin = _stZoom ? _stZoom.pos0 : 0;
  const posMax = _stZoom ? _stZoom.pos1 : L;

  const sx  = t   => pad.left + ((t   - tMin)   / (tMax - tMin || 1)) * cw;
  const sy  = pos => pad.top  + ((posMax - pos)  / (posMax - posMin || 1)) * ch;

  // Zoom hint / reset button (rendered as HTML above SVG)
  const zoomCtrl = _stZoom
    ? `<div style="text-align:right;margin-bottom:4px">
         <button class="tab-btn active" onclick="stResetZoom()" style="font-size:0.8em">&#8634; Reset Zoom</button>
       </div>`
    : `<div style="text-align:right;margin-bottom:4px;color:#94a3b8;font-size:0.78em">Drag to zoom</div>`;

  const parts = [];
  // Drag overlay vars stored as data attributes on the SVG; actual handlers are global functions
  parts.push(`<svg id="stSvg" width="${{W}}" height="${{H}}" class="chart-svg" style="cursor:crosshair;user-select:none"
    onmousedown="stDragStart(event,${{pad.left}},${{pad.top}},${{cw}},${{ch}})"
    onmousemove="stDragMove(event)"
    onmouseup="stDragEnd(event,${{pad.left}},${{pad.top}},${{cw}},${{ch}},${{tMin}},${{tMax}},${{posMin}},${{posMax}})">`);
  parts.push(`<rect x="${{pad.left}}" y="${{pad.top}}" width="${{cw}}" height="${{ch}}" fill="#f8fafc" rx="2"/>`);

  // Y-axis grid + labels
  const nY = 8;
  for (let i = 0; i <= nY; i++) {{
    const pos = posMin + (posMax - posMin) * i / nY;
    const y = sy(pos).toFixed(1);
    parts.push(`<line x1="${{pad.left}}" y1="${{y}}" x2="${{pad.left + cw}}" y2="${{y}}" stroke="#e2e8f0"/>`);
    parts.push(`<text x="${{pad.left - 6}}" y="${{parseFloat(y) + 4}}" text-anchor="end" class="tick">${{(pos / 1000).toFixed(1)}}</text>`);
  }}

  // X-axis grid + labels
  const nX = 6;
  for (let i = 0; i <= nX; i++) {{
    const t = tMin + (tMax - tMin) * i / nX;
    const x = sx(t).toFixed(1);
    parts.push(`<line x1="${{x}}" y1="${{pad.top}}" x2="${{x}}" y2="${{pad.top + ch}}" stroke="#e2e8f0"/>`);
    parts.push(`<text x="${{x}}" y="${{H - 8}}" text-anchor="middle" class="tick">${{fmtTime(t)}}</text>`);
  }}

  // BS reference lines (dashed, labeled on RIGHT side)
  s.base_stations.forEach(bs => {{
    if (bs.x < posMin || bs.x > posMax) return; // skip out-of-view
    const y = sy(bs.x).toFixed(1);
    parts.push(`<line x1="${{pad.left}}" y1="${{y}}" x2="${{pad.left + cw}}" y2="${{y}}" stroke="#94a3b8" stroke-width="0.8" stroke-dasharray="5,3"/>`);
    parts.push(`<text x="${{pad.left + cw + 5}}" y="${{parseFloat(y) + 3}}" text-anchor="start" font-size="7.5" fill="#94a3b8">${{bs.id}}</text>`);
  }});

  // UAM trajectory segments coloured by speed (clipped to plot area)
  parts.push(`<clipPath id="stClip"><rect x="${{pad.left}}" y="${{pad.top}}" width="${{cw}}" height="${{ch}}"/></clipPath>`);
  parts.push('<g clip-path="url(#stClip)">');
  laneData.forEach(traj => {{
    const pts = traj.pts;
    for (let i = 0; i < pts.length - 1; i++) {{
      const p0 = pts[i], p1 = pts[i + 1];
      // Skip segments entirely outside zoom window
      if (p1.t < tMin || p0.t > tMax) continue;
      if (Math.max(p0.pos, p1.pos) < posMin || Math.min(p0.pos, p1.pos) > posMax) continue;
      const x1 = sx(p0.t).toFixed(1), y1 = sy(p0.pos).toFixed(1);
      const x2 = sx(p1.t).toFixed(1), y2 = sy(p1.pos).toFixed(1);
      const col = _stColor((p0.vel + p1.vel) / 2, vMin, vMax);
      parts.push(`<line x1="${{x1}}" y1="${{y1}}" x2="${{x2}}" y2="${{y2}}" stroke="${{col}}" stroke-width="1.3" opacity="0.72"/>`);
    }}
  }});
  parts.push('</g>');

  // Selection rectangle (drawn during drag; initially hidden)
  parts.push(`<rect id="stSelRect" x="0" y="0" width="0" height="0" fill="rgba(52,152,219,0.12)" stroke="#3498db" stroke-width="1" stroke-dasharray="4,2"/>`);

  // Axis border
  parts.push(`<rect x="${{pad.left}}" y="${{pad.top}}" width="${{cw}}" height="${{ch}}" fill="none" stroke="#cbd5e1" stroke-width="1"/>`);

  // Axis labels
  parts.push(`<text x="${{pad.left + cw / 2}}" y="${{H - 1}}" text-anchor="middle" font-size="11" fill="#475569" font-weight="600">Time</text>`);
  parts.push(`<text x="14" y="${{pad.top + ch / 2}}" text-anchor="middle" font-size="11" fill="#475569" font-weight="600" transform="rotate(-90 14,${{(pad.top + ch / 2).toFixed(0)}})">Position (km)</text>`);
  parts.push('</svg>');

  // Speed colour scale legend
  const lw = 220, lh = 14, lx = (W - lw) / 2;
  const steps = 40, sw = lw / steps;
  let legendParts = [`<svg width="${{W}}" height="30" class="chart-svg">`];
  for (let i = 0; i < steps; i++) {{
    const col = _stColor(vMin + (i / (steps - 1)) * (vMax - vMin), vMin, vMax);
    legendParts.push(`<rect x="${{(lx + i * sw).toFixed(1)}}" y="2" width="${{(sw + 0.6).toFixed(1)}}" height="${{lh}}" fill="${{col}}"/>`);
  }}
  legendParts.push(`<text x="${{lx.toFixed(1)}}" y="28" text-anchor="middle" class="tick">Slow (${{vMin}} m/s)</text>`);
  legendParts.push(`<text x="${{(lx + lw / 2).toFixed(1)}}" y="28" text-anchor="middle" class="tick" font-weight="600">Speed</text>`);
  legendParts.push(`<text x="${{(lx + lw).toFixed(1)}}" y="28" text-anchor="middle" class="tick">Fast (${{vMax}} m/s)</text>`);
  legendParts.push('</svg>');

  el.innerHTML = zoomCtrl + parts.join('') + legendParts.join('');
}}

function _stColor(vel, vMin, vMax) {{
  const t = Math.max(0, Math.min(1, (vel - vMin) / Math.max(vMax - vMin, 0.01)));
  // red (hue 0) → yellow (60) → green (120)
  const hue = Math.round(t * 120);
  return `hsl(${{hue}},80%,46%)`;
}}

// --- Time–Space Diagram Drag-to-Zoom ---
function _stSvgCoords(evt) {{
  const svg = document.getElementById('stSvg');
  if (!svg) return null;
  const rect = svg.getBoundingClientRect();
  return {{
    x: evt.clientX - rect.left,
    y: evt.clientY - rect.top,
  }};
}}

function stDragStart(evt, padL, padT, cw, ch) {{
  evt.preventDefault();
  const c = _stSvgCoords(evt);
  if (!c) return;
  // Only start drag inside the plot area
  if (c.x < padL || c.x > padL + cw || c.y < padT || c.y > padT + ch) return;
  _stDragStart = {{x: c.x, y: c.y, padL, padT, cw, ch}};
  const sel = document.getElementById('stSelRect');
  if (sel) {{ sel.setAttribute('x', c.x); sel.setAttribute('y', c.y); sel.setAttribute('width', 0); sel.setAttribute('height', 0); }}
}}

function stDragMove(evt) {{
  if (!_stDragStart) return;
  evt.preventDefault();
  const c = _stSvgCoords(evt);
  if (!c) return;
  const x0 = Math.min(_stDragStart.x, c.x);
  const y0 = Math.min(_stDragStart.y, c.y);
  const dx = Math.abs(c.x - _stDragStart.x);
  const dy = Math.abs(c.y - _stDragStart.y);
  const sel = document.getElementById('stSelRect');
  if (sel) {{ sel.setAttribute('x', x0); sel.setAttribute('y', y0); sel.setAttribute('width', dx); sel.setAttribute('height', dy); }}
}}

function stDragEnd(evt, padL, padT, cw, ch, tMin, tMax, posMin, posMax) {{
  if (!_stDragStart) return;
  evt.preventDefault();
  const c = _stSvgCoords(evt);
  const saved = _stDragStart;
  _stDragStart = null;
  if (!c) {{ _drawSpaceTime(DATA[currentScenario]); return; }}
  const dx = Math.abs(c.x - saved.x);
  const dy = Math.abs(c.y - saved.y);
  if (dx < 8 || dy < 8) {{ _drawSpaceTime(DATA[currentScenario]); return; }} // too small → treat as click
  // Use selection rect pixel bounding box (set continuously by stDragMove)
  const sel = document.getElementById('stSelRect');
  let nx0 = padL, nx1 = padL + cw, ny0 = padT, ny1 = padT + ch;
  if (sel) {{
    nx0 = parseFloat(sel.getAttribute('x'));
    ny0 = parseFloat(sel.getAttribute('y'));
    nx1 = nx0 + parseFloat(sel.getAttribute('width'));
    ny1 = ny0 + parseFloat(sel.getAttribute('height'));
  }}
  // Clamp to plot area
  nx0 = Math.max(nx0, padL); nx1 = Math.min(nx1, padL + cw);
  ny0 = Math.max(ny0, padT); ny1 = Math.min(ny1, padT + ch);
  if (nx1 - nx0 < 8 || ny1 - ny0 < 8) {{ _drawSpaceTime(DATA[currentScenario]); return; }}
  // Map pixel → data (y axis is inverted: top = posMax)
  const newT0   = tMin   + ((nx0 - padL) / cw) * (tMax - tMin);
  const newT1   = tMin   + ((nx1 - padL) / cw) * (tMax - tMin);
  const newPos1 = posMax - ((ny0 - padT) / ch) * (posMax - posMin); // top = higher pos
  const newPos0 = posMax - ((ny1 - padT) / ch) * (posMax - posMin); // bottom = lower pos
  _stZoom = {{t0: newT0, t1: newT1, pos0: newPos0, pos1: newPos1}};
  _drawSpaceTime(DATA[currentScenario]);
}}

function stDragCancel() {{
  _stDragStart = null;
  const sel = document.getElementById('stSelRect');
  if (sel) {{ sel.setAttribute('width', 0); sel.setAttribute('height', 0); }}
}}

function stResetZoom() {{
  _stZoom = null;
  _drawSpaceTime(DATA[currentScenario]);
}}

// --- Scenario Comparison ---
function renderComparison() {{
  if (DATA.length < 2) return;
  const el = document.getElementById('comparisonCharts');
  el.innerHTML = '<h3>Mean RTT Comparison</h3>';

  // Overlay RTT from all scenarios
  const w = 700, h = 200;
  const colors = ['#3498db', '#e74c3c', '#2ecc71', '#9b59b6', '#f39c12'];
  const pad = {{ top: 20, right: 20, bottom: 30, left: 55 }};
  const cw = w - pad.left - pad.right;
  const ch = h - pad.top - pad.bottom;

  // Find global ranges
  let allTimes = [], allVals = [];
  DATA.forEach(s => {{ allTimes.push(...s.time); allVals.push(...s.mean_rtt.map(v=>v*1000)); }});
  const tMin = Math.min(...allTimes), tMax = Math.max(...allTimes);
  const vMin = 0, vMax = Math.max(...allVals) * 1.1 || 1;

  const sx = (t) => pad.left + ((t - tMin) / (tMax - tMin || 1)) * cw;
  const sy = (v) => pad.top + ch - ((v - vMin) / (vMax - vMin)) * ch;

  let paths = '';
  let legend = '';
  DATA.forEach((s, i) => {{
    const c = colors[i % colors.length];
    let d = '';
    s.time.forEach((t, j) => {{
      const x = sx(t).toFixed(1);
      const y = sy(s.mean_rtt[j] * 1000).toFixed(1);
      d += (j === 0 ? 'M' : 'L') + x + ',' + y;
    }});
    paths += `<path d="${{d}}" fill="none" stroke="${{c}}" stroke-width="1.5"/>`;
    legend += `<text x="${{pad.left + i * 120}}" y="15" fill="${{c}}" class="tick" font-weight="bold">${{s.name}}</text>`;
  }});

  el.innerHTML += `<svg width="${{w}}" height="${{h}}" class="chart-svg">${{legend}}${{paths}}</svg>`;

  // Summary comparison table
  let table = '<h3>Summary Comparison</h3><table class="data-table"><thead><tr><th>Scenario</th><th>Classification</th><th>Avg RTT (ms)</th><th>Max RTT (ms)</th><th>Drop Rate</th><th>Mode Switches</th></tr></thead><tbody>';
  DATA.forEach(s => {{
    const sm = s.summary;
    const clsColor = sm.classification === 'normal' ? '#2ecc71' : sm.classification === 'degraded' ? '#f39c12' : '#e74c3c';
    table += `<tr><td>${{s.name}}</td><td style="color:${{clsColor}};font-weight:bold">${{sm.classification.toUpperCase()}}</td>
      <td>${{(sm.avg_rtt_s*1000).toFixed(1)}}</td><td>${{(sm.max_rtt_s*1000).toFixed(1)}}</td>
      <td>${{(sm.drop_rate*100).toFixed(2)}}%</td><td>${{sm.total_mode_switches}}</td></tr>`;
  }});
  table += '</tbody></table>';
  el.innerHTML += table;
}}

// --- Utils ---
function toggleSection(id) {{
  const el = document.getElementById(id);
  el.style.display = el.style.display === 'none' ? 'block' : 'none';
}}

window.addEventListener('DOMContentLoaded', init);
</script>
</body>
</html>"""


_CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: #f5f6fa; color: #2c3e50; padding: 20px; max-width: 820px; margin: 0 auto; }
header { text-align: center; margin-bottom: 20px; }
header h1 { font-size: 1.6em; color: #2c3e50; }
.subtitle { color: #7f8c8d; font-size: 0.9em; margin-top: 4px; }
.card { background: #fff; border-radius: 8px; padding: 16px 20px; margin-bottom: 16px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.card h2 { font-size: 1.1em; margin-bottom: 10px; color: #34495e; cursor: pointer; }
.collapsible .content { display: block; }
.config-table { width: 100%; border-collapse: collapse; font-size: 0.85em; }
.config-table td { padding: 3px 8px; border-bottom: 1px solid #ecf0f1; }
.config-table td:first-child { font-weight: 600; color: #7f8c8d; width: 200px; }
.summary-badge { display: inline-block; padding: 6px 18px; border-radius: 20px; color: #fff;
  font-weight: bold; font-size: 1.1em; margin-bottom: 12px; }
.summary-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.summary-card { text-align: center; padding: 10px; background: #f8f9fa; border-radius: 6px; }
.sc-value { font-size: 1.4em; font-weight: bold; color: #2c3e50; }
.sc-label { font-size: 0.8em; color: #7f8c8d; margin-top: 2px; }
.chart-controls { margin-bottom: 8px; display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.chart-controls label { font-size: 0.85em; cursor: pointer; }
.chart-controls select { padding: 4px 8px; border-radius: 4px; border: 1px solid #bdc3c7; }
.ts-chart { margin-bottom: 6px; }
.ts-chart h4 { font-size: 0.85em; color: #7f8c8d; margin-bottom: 2px; }
.chart-svg { display: block; }
.chart-svg .tick { font-size: 10px; fill: #7f8c8d; }
.narrative-text { font-size: 0.95em; line-height: 1.7; color: #34495e;
  border-left: 4px solid #3498db; padding: 10px 16px; background: #f0f7ff;
  border-radius: 0 6px 6px 0; }
.hist-row { display: flex; gap: 16px; flex-wrap: wrap; }
.hist-container { flex: 1; min-width: 300px; }
.hist-container h3 { font-size: 0.9em; color: #7f8c8d; margin-bottom: 4px; }
.data-table { width: 100%; border-collapse: collapse; font-size: 0.85em; }
.data-table th { background: #f8f9fa; padding: 6px 8px; text-align: left; border-bottom: 2px solid #ecf0f1; }
.data-table td { padding: 5px 8px; border-bottom: 1px solid #ecf0f1; }
.slider-container { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.slider-container input[type=range] { flex: 1; }
.slider-container span { font-size: 0.9em; min-width: 80px; }
.slider-container button { padding: 4px 12px; border: 1px solid #bdc3c7; border-radius: 4px;
  background: #fff; cursor: pointer; font-size: 0.9em; }
.spatial-svg .tick { font-size: 9px; fill: #7f8c8d; }
.tooltip { display: none; position: absolute; background: rgba(44,62,80,0.9); color: #fff;
  padding: 5px 10px; border-radius: 4px; font-size: 0.8em; pointer-events: none; z-index: 100; }
.scenario-btn { padding: 6px 16px; border: 2px solid #3498db; background: #fff; color: #3498db;
  border-radius: 20px; cursor: pointer; margin: 4px; font-size: 0.85em; }
.scenario-btn.active { background: #3498db; color: #fff; }
.check-header { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; margin-bottom: 4px; }
.check-icon { font-size: 1em; }
.check-label { font-size: 0.9em; font-weight: 600; color: #2c3e50; }
.check-measured { font-size: 0.95em; font-weight: 700; }
.check-threshold { font-size: 0.8em; color: #7f8c8d; }
.check-detail { font-size: 0.82em; color: #555; line-height: 1.5; margin-top: 2px; }
.check-grid { display: flex; flex-direction: column; gap: 0; }
.rationale-verdict { font-size: 0.9em; }
.tab-bar { display: flex; gap: 6px; margin-bottom: 10px; flex-wrap: wrap; }
.tab-btn { padding: 4px 14px; border: 1px solid #94a3b8; background: #f8fafc; color: #475569;
  border-radius: 4px; cursor: pointer; font-size: 0.85em; }
.tab-btn.active { background: #3498db; color: #fff; border-color: #3498db; }
"""


def _esc(s):
    """HTML-escape a string."""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _json_default(obj):
    if isinstance(obj, float):
        if math.isinf(obj):
            return 9999
        if math.isnan(obj):
            return 0
    return str(obj)
