import io
import pandas as pd
from typing import Dict, Any

# --- Unit conversion constants ---
KG_TO_LBS = 2.20462
# WattTime value is lbs CO2/MWh; convert to kg CO2/kWh:
#   lbs/MWh ÷ 2.20462 (lbs/kg) ÷ 1000 (kWh/MWh) = kg/kWh
#   which simplifies to lbs/MWh ÷ 2204.62
LBS_PER_MWH_TO_KG_PER_KWH = 2204.62
# EPA natural gas emissions factor: 53.12 kg CO2/MMBtu * 0.1 MMBtu/therm
THERMS_TO_KG_CO2 = 5.312  # kg CO2 per therm

# --- PG&E CSV format constants ---
# PG&E Green Button exports have metadata rows before the data header.
# The actual header row starts with "TYPE,"; rows are tagged by their TYPE value.
CSV_HEADER_MARKER = "TYPE,"
ELECTRIC_TYPE = "Electric usage"
GAS_TYPE = "Natural gas usage"
PACIFIC_TZ = "America/Los_Angeles"
COL_TYPE = "TYPE"
COL_DATE = "DATE"
COL_START_TIME = "START TIME"
COL_KWH = "USAGE (kWh)"
COL_THERMS = "USAGE (therms)"


def _find_header_row(lines: list) -> int:
    """
    Return the index of the PG&E CSV header row (the line starting with 'TYPE,').

    Raises ValueError if the marker is not found.
    """
    for i, line in enumerate(lines):
        if line.startswith(CSV_HEADER_MARKER):
            return i
    raise ValueError("Could not find 'TYPE,' header row in the uploaded CSV.")


def detect_pge_file_type(file_bytes: bytes) -> str:
    """
    Detect whether a PG&E CSV contains electric or gas data.

    Scans for the 'TYPE,' header row, then checks whether the TYPE column
    contains 'Electric usage' or 'Natural gas usage' rows.
    Returns 'electric' or 'gas', raises ValueError if neither is found.
    """
    text = file_bytes.decode("utf-8", errors="replace")
    lines = text.splitlines()
    header_line = _find_header_row(lines)
    csv_body = "\n".join(lines[header_line:])
    df = pd.read_csv(io.StringIO(csv_body))

    types = set(df[COL_TYPE].dropna().unique())
    if ELECTRIC_TYPE in types:
        return "electric"
    if GAS_TYPE in types:
        return "gas"
    raise ValueError(
        "Could not detect file type: no 'Electric usage' or 'Natural gas usage' rows found. "
        "Please upload a PG&E Green Button CSV."
    )


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
    header_line = _find_header_row(lines)

    # Re-parse from the header row onward
    csv_body = "\n".join(lines[header_line:])
    df = pd.read_csv(io.StringIO(csv_body))

    # Keep only electric usage rows
    df = df[df[COL_TYPE] == ELECTRIC_TYPE].copy()
    if df.empty:
        raise ValueError("No 'Electric usage' rows found in the uploaded CSV.")

    # Combine DATE + START TIME into a tz-aware Pacific timestamp, then convert to UTC
    pacific_timestamps = pd.to_datetime(
        df[COL_DATE].astype(str) + " " + df[COL_START_TIME].astype(str)
    )
    # ambiguous=False: on DST fall-back, treat all ambiguous times as standard
    # time (PST). Both occurrences of 1:00–1:59 AM get assigned PST, which is
    # a minor inaccuracy for that one hour but unavoidable without extra metadata.
    pacific_timestamps = pacific_timestamps.dt.tz_localize(
        PACIFIC_TZ, ambiguous=False, nonexistent="shift_forward"
    )
    utc_timestamps = pacific_timestamps.dt.tz_convert("UTC")

    result = pd.DataFrame({
        "timestamp": utc_timestamps,
        "kwh": pd.to_numeric(df[COL_KWH], errors="coerce"),
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


def parse_pge_gas_csv(file_bytes: bytes) -> pd.DataFrame:
    """
    Parse a PG&E natural gas CSV export into a DataFrame of (date, therms).

    Uses the same dynamic header scan as parse_pge_csv. Only the DATE column
    is used — timestamps in gas CSVs are unreliable (e.g. DST rows).
    """
    text = file_bytes.decode("utf-8", errors="replace")

    lines = text.splitlines()
    header_line = _find_header_row(lines)
    csv_body = "\n".join(lines[header_line:])
    df = pd.read_csv(io.StringIO(csv_body))

    df = df[df[COL_TYPE] == GAS_TYPE].copy()
    if df.empty:
        raise ValueError("No 'Natural gas usage' rows found in the uploaded CSV.")

    result = pd.DataFrame({
        "date": pd.to_datetime(df[COL_DATE]).dt.date,
        "therms": pd.to_numeric(df[COL_THERMS], errors="coerce"),
    })

    if result["therms"].isna().any():
        raise ValueError("Some 'USAGE (therms)' values could not be parsed as numbers.")

    return result.reset_index(drop=True)


def calculate_gas_emissions(df: pd.DataFrame) -> pd.DataFrame:
    """Multiply therms by the EPA fixed natural gas emissions factor."""
    df = df.copy()
    df["co2_kg"] = df["therms"] * THERMS_TO_KG_CO2
    df["co2_lbs"] = df["co2_kg"] * KG_TO_LBS
    return df


def build_gas_result(df: pd.DataFrame) -> Dict[str, Any]:
    """Compute aggregate stats and per-day records for natural gas emissions."""
    records = df[["date", "therms", "co2_kg", "co2_lbs"]].to_dict(orient="records")
    return {
        "records_processed": len(df),
        "total_therms": round(df["therms"].sum(), 4),
        "total_co2_kg": round(df["co2_kg"].sum(), 4),
        "total_co2_lbs": round(df["co2_lbs"].sum(), 4),
        "emissions_factor_kg_per_therm": THERMS_TO_KG_CO2,
        "records": records,
    }
