import io
import pandas as pd
from typing import Dict, Any

KG_TO_LBS = 2.20462
# WattTime value is lbs CO2/MWh; convert to kg CO2/kWh:
#   lbs/MWh ÷ 2.20462 (lbs/kg) ÷ 1000 (kWh/MWh) = kg/kWh
#   which simplifies to lbs/MWh ÷ 2204.62
LBS_PER_MWH_TO_KG_PER_KWH = 2204.62


def parse_pge_csv(file_bytes: bytes) -> pd.DataFrame:
    """
    Parse a PG&E Green Button CSV export into a DataFrame of (timestamp, kwh).

    PG&E's format has several metadata rows before the actual column headers,
    so we scan for the header row dynamically rather than skipping a fixed number.
    Timestamps are in Pacific time (America/Los_Angeles) and returned as UTC.
    """
    text = file_bytes.decode("utf-8", errors="replace")

    # Find the line index of the real header row (starts with "TYPE,")
    lines = text.splitlines()
    header_line = None
    for i, line in enumerate(lines):
        if line.startswith("TYPE,"):
            header_line = i
            break

    if header_line is None:
        raise ValueError("Could not find 'TYPE,' header row in the uploaded CSV.")

    # Re-parse from the header row onward
    csv_body = "\n".join(lines[header_line:])
    df = pd.read_csv(io.StringIO(csv_body))

    # Keep only electric usage rows
    df = df[df["TYPE"] == "Electric usage"].copy()
    if df.empty:
        raise ValueError("No 'Electric usage' rows found in the uploaded CSV.")

    # Combine DATE + START TIME into a tz-aware Pacific timestamp, then convert to UTC
    pacific_timestamps = pd.to_datetime(
        df["DATE"].astype(str) + " " + df["START TIME"].astype(str)
    )
    # ambiguous=False: on DST fall-back, treat all ambiguous times as standard
    # time (PST). Both occurrences of 1:00–1:59 AM get assigned PST, which is
    # a minor inaccuracy for that one hour but unavoidable without extra metadata.
    pacific_timestamps = pacific_timestamps.dt.tz_localize(
        "America/Los_Angeles", ambiguous=False, nonexistent="shift_forward"
    )
    utc_timestamps = pacific_timestamps.dt.tz_convert("UTC")

    result = pd.DataFrame({
        "timestamp": utc_timestamps,
        "kwh": pd.to_numeric(df["USAGE (kWh)"], errors="coerce"),
    })

    if result["kwh"].isna().any():
        raise ValueError("Some 'USAGE (kWh)' values could not be parsed as numbers.")

    return result.reset_index(drop=True)


def join_usage_with_intensity(df_usage: pd.DataFrame, df_intensity: pd.DataFrame) -> pd.DataFrame:
    """
    Merge PG&E 15-min usage intervals with WattTime 5-min intensity points.

    Uses a backward asof merge so each usage interval is matched to the most
    recent intensity reading at or before it. Since 15 is a multiple of 5,
    the match is exact for aligned timestamps.

    Returns a DataFrame with columns: timestamp, kwh, emissions_factor_kg_per_kwh.
    Raises ValueError if any usage rows end up without intensity data.
    """
    usage = df_usage.sort_values("timestamp").copy()
    intensity = df_intensity.sort_values("timestamp").copy()

    merged = pd.merge_asof(
        usage,
        intensity[["timestamp", "value_lbs_per_mwh"]],
        on="timestamp",
        direction="backward",
    )

    if merged["value_lbs_per_mwh"].isna().any():
        raise ValueError(
            "Some usage intervals could not be matched to intensity data. "
            "Ensure the WattTime cache covers the full date range of the uploaded file."
        )

    merged["emissions_factor_kg_per_kwh"] = merged["value_lbs_per_mwh"] / LBS_PER_MWH_TO_KG_PER_KWH
    return merged.drop(columns=["value_lbs_per_mwh"])


def calculate_emissions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Core calculation: multiply 15-min kWh by the marginal emissions factor
    to get kg of CO2-equivalent emitted for that interval.

    Uses a marginal (time-varying) emissions factor rather than a single annual
    average — more accurate because grid carbon intensity changes throughout the
    day as different generation sources come online.
    """
    df = df.copy()
    df["co2e_kg"] = df["kwh"] * df["emissions_factor_kg_per_kwh"]
    df["co2e_lbs"] = df["co2e_kg"] * KG_TO_LBS
    return df


def build_result(df: pd.DataFrame) -> Dict[str, Any]:
    """Compute aggregate stats and per-interval records across all processed rows."""
    records = df[["timestamp", "kwh", "emissions_factor_kg_per_kwh", "co2e_kg", "co2e_lbs"]].to_dict(orient="records")
    return {
        "records_processed": len(df),
        "total_kwh": round(df["kwh"].sum(), 4),
        "total_co2e_kg": round(df["co2e_kg"].sum(), 4),
        "total_co2e_lbs": round(df["co2e_lbs"].sum(), 4),
        "avg_emissions_factor": round(df["emissions_factor_kg_per_kwh"].mean(), 6),
        "records": records,
    }
