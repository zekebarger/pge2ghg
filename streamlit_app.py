import json
import os
import pathlib

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from plotly.subplots import make_subplots

from optimize import optimize_demand

API_URL = os.environ.get("API_URL", "http://localhost:8000")
API_TIMEOUT = 120  # seconds; WattTime fetches can be slow for long date ranges

ELECTRIC_COLS = ["timestamp", "kwh", "emissions_factor_kg_per_kwh", "co2e_kg"]
GAS_COLS = ["date", "therms", "co2_kg"]

TOP_N_DAYS = 7

_geojson_path = pathlib.Path(__file__).parent / "data" / "caiso_north.geojson"
with open(_geojson_path) as f:
    _caiso_geojson = json.load(f)

_svg_path = pathlib.Path(__file__).parent / "co2_molecule.svg"
_svg_content = _svg_path.read_text()
_svg_icon = _svg_content.replace('width="300" height="300"', 'width="60" height="60"')

st.set_page_config(page_title="Green Button CO\u2082e Calculator", layout="wide", page_icon=str(_svg_path))

st.markdown(
    f'<h1 style="display:flex;align-items:center;gap:0.5rem">'
    f'Green Button CO\u2082e Calculator {_svg_icon}'
    f'</h1>',
    unsafe_allow_html=True,
)
st.markdown("Upload PG&E 'Green Button' CSV files to visualize your CO\u2082e emissions over time.")

# --- Session state ---
if "electric_df" not in st.session_state:
    st.session_state.electric_df = pd.DataFrame(columns=ELECTRIC_COLS)
if "gas_df" not in st.session_state:
    st.session_state.gas_df = pd.DataFrame(columns=GAS_COLS)
if "processed_files" not in st.session_state:
    st.session_state.processed_files = set()
if "using_example_data" not in st.session_state:
    st.session_state.using_example_data = False


def make_region_map(geojson):
    lats, lons = [], []
    for polygon in geojson["coordinates"]:
        for ring in polygon:
            for lon, lat in ring:
                lons.append(lon)
                lats.append(lat)
            lons.append(None)
            lats.append(None)

    fig = go.Figure(go.Scattermapbox(
        lat=lats, lon=lons,
        mode="lines",
        line=dict(color="steelblue", width=2),
        hoverinfo="none",
    ))
    fig.update_layout(
        mapbox=dict(style="open-street-map", zoom=5,
                    center=dict(lat=37.5, lon=-120.5)),
        margin=dict(l=0, r=0, t=0, b=0),
        height=280,
        showlegend=False,
    )
    return fig


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
        "is set to 'Daily'. The two plots at the bottom of the page show averages "
        "at the daily and weekly levels."
    )

    st.divider()

    st.subheader("Supported region")
    st.markdown(
        "Calculations are only valid for customers in the **CAISO_NORTH** grid region,"
        "which covers most of PG&E's service territory in Northern and Central California."
    )
    st.plotly_chart(make_region_map(_caiso_geojson), use_container_width=True)

    st.divider()

    st.subheader("Note on GHG intensity values")
    st.markdown(
        "The electricity emissions factors come from [WattTime](https://www.watttime.org)'s "
        "`co2_moer` signal for the CAISO_NORTH region as a whole. If you are enrolled in a "
        "**Community Choice Aggregation (CCA)** program, the actual carbon intensity "
        "of your electricity supply may differ from what this app shows."
    )


def _merge_api_response(data: dict) -> None:
    """Merge a /process_auto API response into session state DataFrames."""
    records = data["records"]
    if data["file_type"] == "electric":
        new_df = pd.DataFrame(records)[ELECTRIC_COLS]
        new_df["timestamp"] = pd.to_datetime(new_df["timestamp"])
        combined = pd.concat(
            [st.session_state.electric_df, new_df]
        ).drop_duplicates(subset=["timestamp"])
        st.session_state.electric_df = combined.sort_values("timestamp").reset_index(drop=True)
    else:
        new_df = pd.DataFrame(records)[GAS_COLS]
        new_df["date"] = pd.to_datetime(new_df["date"])
        combined = pd.concat(
            [st.session_state.gas_df, new_df]
        ).drop_duplicates(subset=["date"])
        st.session_state.gas_df = combined.sort_values("date").reset_index(drop=True)


def _load_example_files():
    _data_dir = pathlib.Path(__file__).parent / "data"
    example_files = [
        "mar_2024_electric_example.csv",
        "mar_2024_gas_example.csv",
    ]
    for filename in example_files:
        filepath = _data_dir / filename
        file_bytes = filepath.read_bytes()
        file_id = f"{filename}:{len(file_bytes)}"
        if file_id in st.session_state.processed_files:
            continue
        with st.spinner(f"Loading {filename}..."):
            try:
                resp = requests.post(
                    f"{API_URL}/process_auto",
                    files={"file": (filename, file_bytes, "text/csv")},
                    timeout=API_TIMEOUT,
                )
                resp.raise_for_status()
                _merge_api_response(resp.json())
                st.session_state.processed_files.add(file_id)
            except Exception as e:
                st.error(f"Error loading example file {filename}: {e}")


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

st.subheader(f"kg CO\u2082e emitted, {resolution.lower()} resolution")

# --- Aggregate electric data ---
def aggregate_electric(df: pd.DataFrame, res: str) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.set_index("timestamp")
    # Convert UTC timestamps to Pacific time so that x-axis labels and bucket
    # boundaries align with local time rather than UTC.
    df.index = df.index.tz_convert("America/Los_Angeles")
    if res == "15 min":
        return df.reset_index()
    rules = {"Hourly": "1h", "Daily": "1D", "Weekly": "W"}
    agg = df.resample(rules[res]).agg({"kwh": "sum", "co2e_kg": "sum", "emissions_factor_kg_per_kwh": "mean"})
    return agg.reset_index()


# Monday Jan 3 2000, timezone-naive reference anchor for profile x-axes
REF_WEEK_START = pd.Timestamp("2000-01-03")


def daily_profile(df: pd.DataFrame, res: str) -> pd.DataFrame:
    """Average electric values by time-of-day slot across all days in the data."""
    if df.empty:
        return df
    df = df.copy().set_index("timestamp")
    df.index = df.index.tz_convert("America/Los_Angeles")
    if res == "Hourly":
        df = df.resample("1h").agg({"kwh": "sum", "co2e_kg": "sum", "emissions_factor_kg_per_kwh": "mean"})
    elif res == "Daily":
        df = df.resample("1D").agg({"kwh": "sum", "co2e_kg": "sum", "emissions_factor_kg_per_kwh": "mean"})
    df["slot"] = df.index.hour * 60 + df.index.minute
    grouped = df.groupby("slot")[["kwh", "co2e_kg", "emissions_factor_kg_per_kwh"]].mean()
    grouped["timestamp"] = REF_WEEK_START + pd.to_timedelta(grouped.index, unit="min")
    return grouped.reset_index(drop=True)


def weekly_profile(df: pd.DataFrame, res: str) -> pd.DataFrame:
    """Average electric values by day-of-week (and time slot) across all weeks in the data."""
    if df.empty:
        return df
    df = df.copy().set_index("timestamp")
    df.index = df.index.tz_convert("America/Los_Angeles")
    if res == "Hourly":
        df = df.resample("1h").agg({"kwh": "sum", "co2e_kg": "sum", "emissions_factor_kg_per_kwh": "mean"})
    elif res == "Daily":
        df = df.resample("1D").agg({"kwh": "sum", "co2e_kg": "sum", "emissions_factor_kg_per_kwh": "mean"})
    df["slot"] = df.index.dayofweek * 1440 + df.index.hour * 60 + df.index.minute
    grouped = df.groupby("slot")[["kwh", "co2e_kg", "emissions_factor_kg_per_kwh"]].mean()
    grouped["timestamp"] = REF_WEEK_START + pd.to_timedelta(grouped.index, unit="min")
    return grouped.reset_index(drop=True)


def gas_weekly_profile(df: pd.DataFrame) -> pd.DataFrame:
    """Average gas usage by day-of-week."""
    if df.empty:
        return df
    df = df.copy().set_index("date")
    df["dow"] = df.index.dayofweek
    grouped = df.groupby("dow")[["therms", "co2_kg"]].mean()
    grouped["date"] = REF_WEEK_START + pd.to_timedelta(grouped.index, unit="D")
    return grouped.reset_index(drop=True)


def make_summary_fig(elec: pd.DataFrame, gas: pd.DataFrame, res: str) -> go.Figure:
    has_gas = not gas.empty
    use_bars = res == "Daily"
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.12,
        specs=[[{"secondary_y": False}], [{"secondary_y": True}]],
    )
    if not elec.empty:
        if use_bars:
            fig.add_trace(
                go.Bar(x=elec["timestamp"], y=elec["co2e_kg"],
                       name="Electric CO\u2082e (kg)", marker_color="black", showlegend=False),
                row=1, col=1,
            )
        else:
            fig.add_trace(
                go.Scatter(x=elec["timestamp"], y=elec["co2e_kg"],
                           name="Electric CO\u2082e (kg)", line=dict(color="black"),
                           fill="tozeroy", fillcolor="rgba(128,128,128,0.15)", showlegend=False),
                row=1, col=1,
            )
    if has_gas:
        fig.add_trace(
            go.Bar(x=gas["date"], y=gas["co2_kg"],
                   name="Gas CO\u2082 (kg)", marker_color="#d30000", showlegend=False),
            row=1, col=1,
        )
    if not elec.empty and has_gas:
        fig.update_layout(barmode="stack")
    if not elec.empty:
        if use_bars:
            fig.add_trace(
                go.Bar(x=elec["timestamp"], y=elec["kwh"],
                       name="Electricity (kWh)", marker_color="#aec7e8", showlegend=False),
                row=2, col=1, secondary_y=False,
            )
        else:
            fig.add_trace(
                go.Scatter(x=elec["timestamp"], y=elec["kwh"],
                           name="Electricity (kWh)", line=dict(color="#aec7e8"),
                           fill="tozeroy", fillcolor="rgba(174,199,232,0.3)", showlegend=False),
                row=2, col=1, secondary_y=False,
            )
        fig.add_trace(
            go.Scatter(x=elec["timestamp"], y=elec["emissions_factor_kg_per_kwh"],
                       name="Carbon Intensity (kg CO\u2082e/kWh)",
                       line=dict(color="green"), mode="lines", showlegend=False),
            row=2, col=1, secondary_y=True,
        )
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
    fig.update_layout(height=400, hovermode="x unified", margin=dict(t=10), font=dict(color="black"))
    return fig


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
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    legend2=dict(orientation="h", yanchor="bottom", y=0.47, xanchor="right", x=1),
)

st.plotly_chart(fig, use_container_width=True)

# --- Typical daily and weekly profiles ---
col_daily, col_weekly = st.columns(2)

with col_daily:
    st.markdown("**Day-level average**")
    fig_day = make_summary_fig(daily_profile(electric_df, resolution), pd.DataFrame(), resolution)
    fig_day.update_xaxes(tickformat="%H:%M")
    st.plotly_chart(fig_day, use_container_width=True)

with col_weekly:
    st.markdown("**Week-level average**")
    gas_wp = gas_weekly_profile(gas_df) if resolution == "Daily" else pd.DataFrame()
    fig_week = make_summary_fig(weekly_profile(electric_df, resolution), gas_wp, resolution)
    fig_week.update_xaxes(tickformat="%a", dtick=86400000)
    st.plotly_chart(fig_week, use_container_width=True)

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
    st.plotly_chart(fig_donut, use_container_width=True)

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
    st.plotly_chart(fig_top_days, use_container_width=True)

# --- Load Shifting Analysis ---
st.divider()
st.subheader("Load Shifting Analysis")


@st.cache_data
def _run_load_shift_optimization(demand, intensity, budget_fraction, max_shift_hours):
    return optimize_demand(demand, intensity, budget_fraction=budget_fraction, max_shift_hours=max_shift_hours)


if not electric_df.empty:
    col_ls1, col_ls2 = st.columns(2)
    with col_ls1:
        budget_percent = st.number_input(
            "Percent of hours that can be shifted",
            min_value=1,
            max_value=25,
            value=4,
            step=1,
            help="Integer between 1 and 25",
            width=300,
        )
        max_shift = st.number_input(
            "Maximum hours by which load can be shifted",
            min_value=1,
            max_value=8,
            value=3,
            step=1,
            help="Integer between 1 and 8",
            width=300,
        )

    hourly = aggregate_electric(electric_df, "Hourly")
    demand = hourly["kwh"].values
    intensity = hourly["emissions_factor_kg_per_kwh"].values

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
else:
    st.info("Upload electric usage data to see load shifting analysis.")
