import pathlib
import sys

# Ensure the project root is on sys.path so `from app.* import …` resolves when
# running locally as `streamlit run ui/streamlit_app.py` from the project root.
# Streamlit adds ui/ automatically; this adds the parent directory (project root).
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import json

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from plotly.subplots import make_subplots

from app.optimize import OptimizationResult, optimize_demand
from charts import (
    daily_profile,
    gas_weekly_profile,
    make_region_map,
    make_summary_fig,
    weekly_profile,
)
from data_utils import (
    API_TIMEOUT,
    API_URL,
    ELECTRIC_COLS,
    GAS_COLS,
    TOP_N_DAYS,
    _load_example_files,
    _merge_api_response,
    aggregate_electric,
)

_geojson_path = pathlib.Path(__file__).parent / "caiso_north.geojson"
try:
    with open(_geojson_path) as f:
        _caiso_geojson = json.load(f)
except OSError:
    st.warning(f"Could not load region map: {_geojson_path} not found.")
    _caiso_geojson = {"coordinates": []}

_svg_path = pathlib.Path(__file__).parent / "co2_molecule.svg"
try:
    _svg_content = _svg_path.read_text()
    _svg_icon = _svg_content.replace('width="300" height="300"', 'width="60" height="60"')
except OSError:
    _svg_content = ""
    _svg_icon = ""

st.set_page_config(page_title="Green Button CO\u2082e Calculator", layout="wide", page_icon=str(_svg_path))

st.markdown(
    f'<h1 style="display:flex;align-items:center;gap:0.5rem">'
    f'Green Button CO\u2082e Calculator {_svg_icon}'
    f'</h1>',
    unsafe_allow_html=True,
)
st.markdown(
    "Upload PG&E 'Green Button' CSV files to visualize the CO\u2082e emissions "
    "from your energy usage over time."
)

# --- Session state ---
if "electric_df" not in st.session_state:
    st.session_state.electric_df = pd.DataFrame(columns=ELECTRIC_COLS)
if "gas_df" not in st.session_state:
    st.session_state.gas_df = pd.DataFrame(columns=GAS_COLS)
if "processed_files" not in st.session_state:
    st.session_state.processed_files = set()
if "using_example_data" not in st.session_state:
    st.session_state.using_example_data = False

with st.sidebar:
    st.header("How to use this app")

    st.subheader("Step 1 — Download your data from PG&E")
    st.markdown(
        "Log in to your PG&E account at [pge.com](https://www.pge.com) and navigate to "
        "**Usage and Rates** → **Energy Use Details** → **Green Button**. "
        "Download results in CSV format for a bill period or a range of days. "
        "If you want, delete your name, address, and account number from the files."
    )

    st.subheader("Step 2 — Upload your files")
    st.markdown(
        "Use the upload widget on this page to upload one or more CSV files "
        "of electric and/or gas usage data."
    )

    st.subheader("Step 3 — View your data")
    st.markdown(
        "Use the plots to inspect your CO\u2082e emissions over time. "
        "Emissions from natural gas use can be displayed when the time resolution "
        "is set to 'Daily'."
    )

    st.subheader("Step 4 — Analyze load shifting")
    st.markdown(
        "Select the percentage of electricity usage in your data to shift and the "
        "maximum number of hours by which any single hour of usage can be shifted. "
        "You can then view a CO\u2082e-optimized version of your hourly electricity usage. "
        "Optimization is performed with a greedy algorithm that swaps pairs of hours."
    )

    st.divider()

    st.subheader("Supported region")
    st.markdown(
        "Calculations are only valid for customers in the **CAISO_NORTH** grid region,"
        "which covers most of PG&E's service territory in Northern and Central California."
    )
    st.plotly_chart(make_region_map(_caiso_geojson), width='stretch')

    st.divider()

    st.subheader("Note on GHG intensity values")
    st.markdown(
        "The electricity emissions factors come from [WattTime](https://www.watttime.org)'s "
        "`co2_moer` signal for the CAISO_NORTH region as a whole. If you are enrolled in a "
        "**Community Choice Aggregation (CCA)** program, the actual carbon intensity "
        "of your electricity supply may differ from what this app shows."
    )

# --- File upload section ---
uploaded_files = st.file_uploader(
    "Upload PG&E CSV file(s)",
    type="csv",
    accept_multiple_files=True,
    key="file_uploader",
    max_upload_size=25,
)

# Process new files
if uploaded_files and st.session_state.using_example_data:
    st.session_state.electric_df = pd.DataFrame(columns=ELECTRIC_COLS)
    st.session_state.gas_df = pd.DataFrame(columns=GAS_COLS)
    st.session_state.processed_files = set()
    st.session_state.using_example_data = False

for f in uploaded_files or []:
    file_id = f"{f.name}:{f.size}"
    if file_id not in st.session_state.processed_files:
        with st.spinner(f"Processing {f.name}..."):
            try:
                resp = requests.post(
                    f"{API_URL}/process_auto",
                    files={"file": (f.name, f.getvalue(), "text/csv")},
                    timeout=API_TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()
                _merge_api_response(data)
                st.session_state.processed_files.add(file_id)
                st.success(f"Loaded {len(data['records'])} {data['file_type']} records from {f.name}")
            except requests.exceptions.HTTPError as e:
                detail = ""
                try:
                    detail = e.response.json().get("detail", "")
                except Exception:
                    pass
                st.error(f"Error processing {f.name}: {e}" + (f"\n\n{detail}" if detail else ""))
            except Exception as e:
                st.error(f"Error processing {f.name}: {e}")

electric_df = st.session_state.electric_df
gas_df = st.session_state.gas_df

if electric_df.empty and gas_df.empty:
    st.info(
        "Upload one or more PG&E CSV files above to get started, "
        "or click the button below to view example data."
    )
    if st.button("View example data"):
        _load_example_files()
        st.session_state.using_example_data = True
        st.rerun()
    st.stop()

# --- Resolution toggle ---
resolution = st.radio("Time resolution", ["15 min", "Hourly", "Daily"], horizontal=True)

st.subheader(f"CO\u2082e emissions profile")

elec = aggregate_electric(electric_df, resolution)
gas = gas_df.copy() if not gas_df.empty else gas_df

# Gas data is only shown at daily resolution
has_gas = not gas.empty and resolution == "Daily"

# --- Build combined figure with shared x-axis ---
fig = make_subplots(
    rows=2,
    cols=1,
    shared_xaxes=True,
    vertical_spacing=0.1,
    subplot_titles=("CO\u2082e Emissions", "Usage & Carbon Intensity"),
    specs=[[{"secondary_y": False}], [{"secondary_y": True}]],
)

# --- Row 1: CO2e time series ---
if resolution in ("15 min", "Hourly"):
    if not elec.empty:
        fig.add_trace(
            go.Scatter(
                x=elec["timestamp"],
                y=elec["co2e_kg"],
                name="Electric CO\u2082e (kg)",
                line=dict(color="black"),
                fill="tozeroy",
                fillcolor="rgba(128,128,128,0.15)",
                legendrank=1,
            ),
            row=1,
            col=1,
        )
else:  # Daily
    if not elec.empty:
        fig.add_trace(
            go.Bar(
                x=elec["timestamp"],
                y=elec["co2e_kg"],
                name="Electric CO\u2082e (kg)",
                marker_color="black",
                legendrank=1,
            ),
            row=1,
            col=1,
        )
    if has_gas:
        fig.add_trace(
            go.Bar(
                x=gas["date"],
                y=gas["co2_kg"],
                name="Gas CO\u2082 (kg)",
                marker_color="#d30000",
                legendrank=2,
            ),
            row=1,
            col=1,
        )
    if not elec.empty and has_gas:
        fig.update_layout(barmode="stack")

# --- Row 2: Usage + Carbon Intensity ---
if not elec.empty:
    fig.add_trace(
        go.Bar(
            x=elec["timestamp"],
            y=elec["kwh"],
            name="Electricity (kWh)",
            marker_color="#aec7e8",
            legendrank=3,
            legend="legend2",
        ),
        row=2,
        col=1,
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=elec["timestamp"],
            y=elec["emissions_factor_kg_per_kwh"],
            name="Carbon Intensity (kg CO\u2082e/kWh)",
            line=dict(color="green"),
            mode="lines",
            legendrank=4,
            legend="legend2",
        ),
        row=2,
        col=1,
        secondary_y=True,
    )

if resolution in ("15 min", "Hourly"):
    fig.add_trace(
        go.Scatter(
            x=[None],
            y=[None],
            name="CO\u2082e (kg)",
            mode="lines",
            line=dict(color="black"),
            fill="tozeroy",
            fillcolor="rgba(128,128,128,0.15)",
            legend="legend2",
            legendrank=2,
        ),
    )

# --- Axis labels ---
fig.update_yaxes(title_text="CO\u2082e (kg)", row=1, col=1)
fig.update_yaxes(title_text="kWh", row=2, col=1, secondary_y=False)
if not elec.empty:
    fig.update_yaxes(title_text="kg CO\u2082e/kWh", row=2, col=1, secondary_y=True)
fig.update_xaxes(
    tickfont=dict(color="black"),
    title_font=dict(color="black"),
    showgrid=True,
    gridcolor="rgba(0,0,0,0.12)",
)
fig.update_yaxes(tickfont=dict(color="black"), title_font=dict(color="black"))

# Enforce legend order by controlling fig.data position
_name_rank = {
    "Electric CO\u2082e (kg)": 3,
    "Gas CO\u2082 (kg)": 2,
    "Electricity (kWh)": 1,
    "Carbon Intensity (kg CO\u2082e/kWh)": 0,
}
fig.data = tuple(sorted(fig.data, key=lambda t: _name_rank.get(t.name, -1), reverse=True))

fig.update_layout(
    height=700,
    hovermode="x unified",
    font=dict(color="black"),
    margin=dict(b=80),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    legend2=dict(orientation="h", yanchor="top", y=-0.1, xanchor="center", x=0.5, font=dict(size=14)),
)
if resolution == "Daily":
    fig.update_xaxes(hoverformat="%a %b %d, %Y")
else:
    fig.update_xaxes(hoverformat="%a %b %d, %Y %H:%M")

st.plotly_chart(fig, width='stretch')

# --- Typical daily and weekly profiles ---
col_daily, col_weekly = st.columns(2)

with col_daily:
    if resolution == "Daily":
        st.info(
            "Choose a different time resolution to show hour-level averages."
        )
    else:
        st.markdown("**Average by Hour of Day**")
        fig_day = make_summary_fig(daily_profile(electric_df, resolution), pd.DataFrame(), resolution)
        fig_day.update_xaxes(tickformat="%H:%M")
        st.plotly_chart(fig_day, width='stretch')

with col_weekly:
    st.markdown("**Average by Day of Week**")
    gas_wp = gas_weekly_profile(gas_df) if resolution == "Daily" else pd.DataFrame()
    fig_week = make_summary_fig(weekly_profile(electric_df, resolution), gas_wp, resolution)
    fig_week.update_xaxes(tickformat="%a", dtick=86400000)
    st.plotly_chart(fig_week, width='stretch')

# Summary results section
total_elec_co2e = electric_df["co2e_kg"].sum()
total_gas_co2e = gas_df["co2_kg"].sum() if not gas_df.empty else 0.0
total_co2e = total_elec_co2e + total_gas_co2e

if not electric_df.empty:
    elec_daily = electric_df.copy()
    elec_daily["timestamp"] = elec_daily["timestamp"].dt.tz_convert("America/Los_Angeles")
    elec_daily["date"] = elec_daily["timestamp"].dt.date
    elec_daily = elec_daily.groupby("date")["co2e_kg"].sum().reset_index()
    elec_daily = elec_daily.rename(columns={"co2e_kg": "elec_co2e"})
else:
    elec_daily = pd.DataFrame(columns=["date", "elec_co2e"])

if not gas_df.empty:
    gas_daily = gas_df[["date", "co2_kg"]].copy()
    gas_daily["date"] = pd.to_datetime(gas_daily["date"]).dt.date
    merged = pd.merge(elec_daily, gas_daily, on="date", how="outer").fillna(0)
else:
    merged = elec_daily.copy()
    merged["co2_kg"] = 0.0
merged["total"] = merged["elec_co2e"] + merged["co2_kg"]

top_days = merged.nlargest(
    min(TOP_N_DAYS, len(merged)),
    "total"
).sort_values("total", ascending=True)
top_days_labels = [str(d) for d in top_days["date"]]
top_days_positions = list(range(len(top_days)))

col_summary, col_top_days = st.columns(2)

with col_summary:
    st.metric("Total CO\u2082e emitted", f"{total_co2e:,.1f} kg")

    donut_labels, donut_values, donut_colors = [], [], []
    if not gas_df.empty and total_gas_co2e > 0:
        donut_labels.append("Gas")
        donut_values.append(total_gas_co2e)
        donut_colors.append("#d30000")
    if not electric_df.empty and total_elec_co2e > 0:
        donut_labels.append("Electric")
        donut_values.append(total_elec_co2e)
        donut_colors.append("black")

    fig_donut = go.Figure(go.Pie(
        labels=donut_labels,
        values=donut_values,
        hole=0.5,
        marker=dict(colors=donut_colors),
        sort=False,
        hovertemplate=(
            "%{percent} from %{label}<br>"
            "%{value:.2f} kg"
        ),
        textfont_size=15,
    ))
    fig_donut.update_traces(textinfo='percent+label')
    fig_donut.update_layout(
        height=330,
        font=dict(color="black"),
        showlegend=False,
        margin=dict(t=20, b=20, l=20, r=20),
    )
    st.plotly_chart(fig_donut, width='stretch')

with col_top_days:
    st.markdown(f"**Days with highest total CO\u2082e**")
    fig_top_days = go.Figure()
    if not electric_df.empty:
        fig_top_days.add_trace(go.Bar(
            y=top_days_positions,
            x=top_days["elec_co2e"],
            name="Electric CO\u2082e (kg)",
            orientation="h",
            marker_color="black",
        ))
    if not gas_df.empty:
        fig_top_days.add_trace(go.Bar(
            y=top_days_positions,
            x=top_days["co2_kg"],
            name="Gas CO\u2082 (kg)",
            orientation="h",
            marker_color="#d30000",
        ))
    fig_top_days.update_layout(
        barmode="stack",
        height=390,
        font=dict(color="black"),
        xaxis_title="CO\u2082e (kg)",
        yaxis=dict(tickmode="array", tickvals=top_days_positions, ticktext=top_days_labels),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(t=40, b=40, l=80, r=20),
    )
    fig_top_days.update_layout(legend_traceorder="grouped+reversed", font=dict(color="black"))
    fig_top_days.update_xaxes(
        tickfont=dict(color="black"),
        title_font=dict(color="black"),
        showgrid=True,
        gridcolor="rgba(0,0,0,0.12)",
    )
    fig_top_days.update_yaxes(
        tickfont=dict(color="black"),
        title_font=dict(color="black")
    )
    st.plotly_chart(fig_top_days, width='stretch')

# --- Load Shifting Analysis ---
st.divider()
st.subheader("Load Shifting Analysis")


@st.cache_data
def _run_load_shift_optimization(
    demand,
    intensity,
    budget_fraction: float,
    max_shift_hours: int,
) -> OptimizationResult:
    """Run the greedy load-shift optimizer; cached so Streamlit doesn't recompute on every rerun."""
    return optimize_demand(demand, intensity, budget_fraction=budget_fraction, max_shift_hours=max_shift_hours)


if not electric_df.empty:
    col_ls1, col_ls2 = st.columns(2)
    with col_ls1:
        budget_percent = st.number_input(
            "Percent of electricity usage that can be shifted",
            min_value=0,
            max_value=50,
            value=15,
            step=1,
            help="Number between 0 and 50",
            width=300,
        )
        max_shift = st.number_input(
            "Maximum hours by which load can be shifted",
            min_value=1,
            max_value=8,
            value=5,
            step=1,
            help="Integer between 1 and 8",
            width=300,
        )

    hourly = aggregate_electric(electric_df, "Hourly")
    demand = hourly["kwh"].fillna(0).values
    intensity = hourly["emissions_factor_kg_per_kwh"].fillna(0).values

    with st.spinner("Running load shift optimization..."):
        result = _run_load_shift_optimization(
            demand,
            intensity,
            budget_fraction=int(budget_percent) / 100,
            max_shift_hours=int(max_shift),
        )

    with col_ls2:
        st.metric(
            "CO\u2082e savings",
            f"{result.reduction_percent:.1f}% ({result.reduction_absolute:.2f} kg)",
        )

    opt_demand = result.optimized_demand
    timestamps = hourly["timestamp"]

    # Stacked bar segments for Row 1:
    #   bottom (light blue) = min(actual, optimized) — the "unchanged" portion
    #   white cap           = max(0, actual - optimized) — demand shifted away
    #   gray extension      = max(0, optimized - actual) — demand shifted in
    bar_bottom      = [float(min(demand[i], opt_demand[i])) for i in range(len(demand))]
    removal_overlay   = [float(max(0.0, demand[i] - opt_demand[i])) for i in range(len(demand))]
    addition_overlay    = [float(max(0.0, opt_demand[i] - demand[i])) for i in range(len(demand))]
    # Per-bar border width: 0 for zero-height bars so no hairline artifacts
    white_widths    = [1.0 if demand[i] > opt_demand[i] else 0.0 for i in range(len(demand))]
    # gray_widths     = [1.0 if opt_demand[i] > demand[i] else 0.0 for i in range(len(demand))]

    actual_emissions = demand * intensity
    optimized_emissions = opt_demand * intensity
    emissions_delta = optimized_emissions - actual_emissions
    delta_colors = ["#d62728" if d > 0 else "#2ca02c" for d in emissions_delta]

    fig_opt = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.15,
        subplot_titles=("Optimized Load & Carbon Intensity", "Hourly Emissions Change (kg CO\u2082e)"),
        specs=[[{"secondary_y": True}], [{"secondary_y": False}]],
    )
    fig_opt.add_trace(
        go.Bar(x=timestamps, y=bar_bottom, name="Actual Electricity (kWh)",
               marker=dict(color="#aec7e8"), legendrank=1, legend="legend",
               hoverinfo="skip"),
        row=1, col=1, secondary_y=False,
    )
    fig_opt.add_trace(
        go.Bar(x=timestamps, y=removal_overlay, name="Reduced Load (kWh)",
               marker=dict(color="white", line=dict(color="black", width=white_widths),
                           pattern=dict(shape="/", fgcolor="gray", solidity=0.15)),
               legendrank=3, legend="legend"),
        row=1, col=1, secondary_y=False,
    )
    fig_opt.add_trace(
        go.Bar(x=timestamps, y=addition_overlay, name="Added Load (kWh)",
               marker=dict(color="#919191"),
               legendrank=4, legend="legend"),
        row=1, col=1, secondary_y=False,
    )
    fig_opt.add_trace(
        go.Scatter(x=timestamps, y=intensity,
                   name="Carbon Intensity (kg CO\u2082e/kWh)",
                   line=dict(color="green"), mode="lines",
                   legendrank=2, legend="legend"),
        row=1, col=1, secondary_y=True,
    )
    fig_opt.add_trace(
        go.Bar(x=timestamps, y=emissions_delta,
               name="Emissions Change (kg CO\u2082e)",
               marker_color=delta_colors, showlegend=False),
        row=2, col=1,
    )
    fig_opt.add_hline(y=0, line=dict(color="black", width=1.5), row=2, col=1)
    fig_opt.update_yaxes(title_text="kWh", row=1, col=1, secondary_y=False)
    fig_opt.update_yaxes(title_text="kg CO\u2082e/kWh", row=1, col=1, secondary_y=True)
    fig_opt.update_yaxes(title_text="kg CO\u2082e", row=2, col=1)
    fig_opt.update_xaxes(
        tickfont=dict(color="black"), title_font=dict(color="black"),
        showgrid=True, gridcolor="rgba(0,0,0,0.12)",
    )
    fig_opt.update_yaxes(tickfont=dict(color="black"), title_font=dict(color="black"))
    fig_opt.update_layout(
        barmode="stack",
        height=700,
        hovermode="x unified",
        font=dict(color="black"),
        legend=dict(orientation="h", yanchor="top", y=0.56, xanchor="center", x=0.5),
    )
    fig_opt.update_xaxes(hoverformat="%a %b %d, %Y %H:%M")
    st.plotly_chart(fig_opt, width='stretch')

    # Summary plots: electricity usage change by hour of day and by day of week
    demand_delta = opt_demand - demand

    usage_df = pd.DataFrame({
        "hour": timestamps.dt.hour.values,
        "delta": demand_delta,
    })

    hod_delta = usage_df.groupby("hour")["delta"].sum().reindex(range(24), fill_value=0.0)

    affected_indices = set()
    for swap in result.swaps:
        affected_indices.add(swap.hour_i)
        affected_indices.add(swap.hour_j)

    dow_kwh = [0.0] * 7
    for idx in affected_indices:
        dow_kwh[timestamps.iloc[idx].dayofweek] += abs(demand_delta[idx])

    total_kwh_shifted = sum(dow_kwh) or 1.0
    dow_pct = [kwh / total_kwh_shifted * 100 for kwh in dow_kwh]
    dow_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    fig_hod = go.Figure()
    fig_hod.add_trace(go.Bar(
        x=list(range(24)), y=hod_delta.values,
        marker_color="#aec7e8",
        name="Usage Change (kWh)",
    ))
    fig_hod.add_hline(y=0, line=dict(color="black", width=1.5))
    fig_hod.update_layout(
        title="Electricity Usage Change by Hour of Day",
        xaxis_title="Hour of Day",
        yaxis_title="kWh",
        xaxis=dict(tickmode="linear", tick0=0, dtick=1,
                   tickfont=dict(color="black"), title_font=dict(color="black"),
                   showgrid=True, gridcolor="rgba(0,0,0,0.12)"),
        yaxis=dict(tickfont=dict(color="black"), title_font=dict(color="black")),
        font=dict(color="black"),
        showlegend=False,
    )

    fig_dow = go.Figure()
    fig_dow.add_trace(go.Bar(
        x=dow_names, y=dow_pct,
        marker_color="black",
        name="% of kWh Shifted",
    ))
    fig_dow.update_layout(
        title="Shifted Load by Day of Week",
        xaxis_title="Day of Week",
        yaxis_title="% of Total kWh Shifted",
        xaxis=dict(tickfont=dict(color="black"), title_font=dict(color="black"),
                   showgrid=True, gridcolor="rgba(0,0,0,0.12)"),
        yaxis=dict(tickfont=dict(color="black"), title_font=dict(color="black"),
                   range=[0, max(dow_pct) * 1.15 if any(dow_pct) else 10]),
        font=dict(color="black"),
        showlegend=False,
    )

    col_sum1, col_sum2 = st.columns(2)
    with col_sum1:
        st.plotly_chart(fig_hod, width='stretch')
    with col_sum2:
        st.plotly_chart(fig_dow, width='stretch')

else:
    st.info("Upload electric usage data to see load shifting analysis.")
