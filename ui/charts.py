"""
Plotly chart builders and profile-aggregation helpers for the Streamlit front-end.

All functions are pure (no Streamlit calls, no session state). They receive
DataFrames and return either a transformed DataFrame or a go.Figure.
"""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from data_utils import _to_pacific

# Monday Jan 3 2000, timezone-naive reference anchor for profile x-axes
REF_WEEK_START = pd.Timestamp("2000-01-03")


def make_region_map(geojson: dict) -> go.Figure:
    """Build a Plotly Scattermap figure outlining the CAISO_NORTH grid region."""
    lats, lons = [], []
    for polygon in geojson["coordinates"]:
        for ring in polygon:
            for lon, lat in ring:
                lons.append(lon)
                lats.append(lat)
            lons.append(None)
            lats.append(None)

    fig = go.Figure(go.Scattermap(
        lat=lats, lon=lons,
        mode="lines",
        line=dict(color="steelblue", width=2),
        hoverinfo="none",
    ))
    fig.update_layout(
        map=dict(style="open-street-map", zoom=4.5,
                 center=dict(lat=37.5, lon=-120.5)),
        margin=dict(l=0, r=0, t=0, b=0),
        height=280,
        showlegend=False,
    )
    return fig


def daily_profile(df: pd.DataFrame, res: str) -> pd.DataFrame:
    """Average electric values by time-of-day slot across all days in the data."""
    if df.empty:
        return df
    df = _to_pacific(df.copy())
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
    df = _to_pacific(df.copy())
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
    """
    Build a two-row Plotly figure showing CO₂e emissions (row 1) and
    electricity usage + carbon intensity (row 2).

    Gas CO₂ is stacked onto electric CO₂e in row 1 when daily resolution is
    active. Row 2 shows kWh as bars and emissions factor as a secondary y-axis line.
    """
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
