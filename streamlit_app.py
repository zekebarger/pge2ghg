import os

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from plotly.subplots import make_subplots

API_URL = os.environ.get("API_URL", "http://localhost:8000")

st.set_page_config(page_title="GHG Emissions Tracker", layout="wide")
st.title("GHG Emissions Tracker")
st.markdown("Upload PG&E CSV files to visualize your CO\u2082e emissions over time.")

# --- Session state ---
if "electric_df" not in st.session_state:
    st.session_state.electric_df = pd.DataFrame(
        columns=["timestamp", "kwh", "emissions_factor_kg_per_kwh", "co2e_kg"]
    )
if "gas_df" not in st.session_state:
    st.session_state.gas_df = pd.DataFrame(columns=["date", "therms", "co2_kg"])
if "processed_electric" not in st.session_state:
    st.session_state.processed_electric = set()
if "processed_gas" not in st.session_state:
    st.session_state.processed_gas = set()

# --- File upload section ---
col1, col2 = st.columns(2)

with col1:
    st.subheader("Electric Usage")
    electric_files = st.file_uploader(
        "Upload PG&E electric CSV(s)",
        type="csv",
        accept_multiple_files=True,
        key="electric_uploader",
    )

with col2:
    st.subheader("Natural Gas Usage")
    gas_files = st.file_uploader(
        "Upload PG&E gas CSV(s)",
        type="csv",
        accept_multiple_files=True,
        key="gas_uploader",
    )

# Process new electric files
for f in electric_files or []:
    file_id = f"{f.name}:{f.size}"
    if file_id not in st.session_state.processed_electric:
        with st.spinner(f"Processing {f.name}..."):
            try:
                resp = requests.post(
                    f"{API_URL}/process",
                    files={"file": (f.name, f.getvalue(), "text/csv")},
                    timeout=120,
                )
                resp.raise_for_status()
                records = resp.json()["records"]
                new_df = pd.DataFrame(records)[
                    ["timestamp", "kwh", "emissions_factor_kg_per_kwh", "co2e_kg"]
                ]
                new_df["timestamp"] = pd.to_datetime(new_df["timestamp"])
                combined = pd.concat(
                    [st.session_state.electric_df, new_df]
                ).drop_duplicates(subset=["timestamp"])
                st.session_state.electric_df = (
                    combined.sort_values("timestamp").reset_index(drop=True)
                )
                st.session_state.processed_electric.add(file_id)
                st.success(f"Loaded {len(records)} records from {f.name}")
            except requests.exceptions.HTTPError as e:
                detail = ""
                try:
                    detail = e.response.json().get("detail", "")
                except Exception:
                    pass
                st.error(f"Error processing {f.name}: {e}" + (f"\n\n{detail}" if detail else ""))
            except Exception as e:
                st.error(f"Error processing {f.name}: {e}")

# Process new gas files
for f in gas_files or []:
    file_id = f"{f.name}:{f.size}"
    if file_id not in st.session_state.processed_gas:
        with st.spinner(f"Processing {f.name}..."):
            try:
                resp = requests.post(
                    f"{API_URL}/process_gas",
                    files={"file": (f.name, f.getvalue(), "text/csv")},
                    timeout=120,
                )
                resp.raise_for_status()
                records = resp.json()["records"]
                new_df = pd.DataFrame(records)[["date", "therms", "co2_kg"]]
                new_df["date"] = pd.to_datetime(new_df["date"])
                combined = pd.concat(
                    [st.session_state.gas_df, new_df]
                ).drop_duplicates(subset=["date"])
                st.session_state.gas_df = (
                    combined.sort_values("date").reset_index(drop=True)
                )
                st.session_state.processed_gas.add(file_id)
                st.success(f"Loaded {len(records)} records from {f.name}")
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
    st.info("Upload one or more PG&E CSV files above to get started.")
    st.stop()

# --- Resolution toggle ---
resolution = st.radio("Time resolution", ["15 min", "Hourly", "Daily"], horizontal=True)

st.subheader(f"kg CO\u2082e emitted, {resolution} resolution")

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
    fig.update_layout(height=400, hovermode="x unified", margin=dict(t=10))
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
                legendrank=4,
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
                legendrank=4,
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
                legendrank=3,
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
            legendrank=2,
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
            legendrank=1,
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

# Enforce legend order by controlling fig.data position
_name_rank = {
    "Electric CO\u2082e (kg)": 1,
    "Gas CO\u2082 (kg)": 0,
    "Electricity (kWh)": 2,
    "Carbon Intensity (kg CO\u2082e/kWh)": 3,
}
fig.data = tuple(sorted(fig.data, key=lambda t: _name_rank.get(t.name, -1), reverse=True))

fig.update_layout(
    height=700,
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
)

st.plotly_chart(fig, use_container_width=True)

# --- Typical daily and weekly profiles ---
st.divider()
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
