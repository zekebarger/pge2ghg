"""
Data transforms and API helpers for the Streamlit front-end.

All functions here are pure data operations or thin wrappers around the
/process_auto API. Streamlit session-state is touched only by
_merge_api_response and _load_example_files.
"""

import os
import pathlib

import pandas as pd
import streamlit as st

API_URL = os.environ.get("API_URL", "http://localhost:8000")
API_TIMEOUT = 120  # seconds; WattTime fetches can be slow for long date ranges

ELECTRIC_COLS = ["timestamp", "kwh", "emissions_factor_kg_per_kwh", "co2e_kg"]
GAS_COLS = ["date", "therms", "co2_kg"]
TOP_N_DAYS = 7


def _to_pacific(df: pd.DataFrame) -> pd.DataFrame:
    """Set the timestamp column as the index and convert from UTC to Pacific time."""
    df = df.set_index("timestamp")
    df.index = df.index.tz_convert("America/Los_Angeles")
    return df


def aggregate_electric(df: pd.DataFrame, res: str) -> pd.DataFrame:
    """Resample electric usage to the requested resolution ('15 min', 'Hourly', 'Daily')."""
    if df.empty:
        return df
    # Convert UTC timestamps to Pacific time so that x-axis labels and bucket
    # boundaries align with local time rather than UTC.
    df = _to_pacific(df)
    if res == "15 min":
        return df.reset_index()
    rules = {"Hourly": "1h", "Daily": "1D", "Weekly": "W"}
    agg = df.resample(rules[res]).agg({"kwh": "sum", "co2e_kg": "sum", "emissions_factor_kg_per_kwh": "mean"})
    return agg.reset_index()


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


def _load_example_files() -> None:
    """Load bundled March 2024 example CSVs and merge them into session state."""
    with st.spinner(f"Loading example files..."):
        _data_dir = pathlib.Path(__file__).parent / "data"

        for file in [("example_electric.csv", True), ("example_gas.csv", False)]:
            df = pd.read_csv(_data_dir / file[0])
            if file[1]:
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                st.session_state.electric_df = df.sort_values("timestamp").reset_index(drop=True)
            else:
                df["date"] = pd.to_datetime(df["date"])
                st.session_state.gas_df = df.sort_values("date").reset_index(drop=True)
            st.session_state.processed_files.add(file[0])
