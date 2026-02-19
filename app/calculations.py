import pandas as pd
from typing import Dict, Any

KG_TO_LBS = 2.20462


def load_csv(filepath: str) -> pd.DataFrame:
    """Load and validate the usage CSV."""
    required_columns = {"timestamp", "kwh", "grid_region", "emissions_factor_kg_per_kwh"}
    df = pd.read_csv(filepath, parse_dates=["timestamp"])

    missing = required_columns - set(df.columns)
    if missing:
        raise ValueError(f"CSV is missing required columns: {missing}")

    if df[["kwh", "emissions_factor_kg_per_kwh"]].lt(0).any().any():
        raise ValueError("kWh and emissions factor values must be non-negative.")

    return df


def calculate_emissions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Core calculation: multiply hourly kWh by the marginal emissions factor
    to get kg of CO2-equivalent emitted that hour.

    This approach uses a marginal (time-varying) emissions factor rather than
    a single annual average — which is more accurate for hourly analysis
    because the carbon intensity of the grid changes throughout the day
    as different generation sources (solar, gas peakers, etc.) come online.
    """
    df = df.copy()
    df["co2e_kg"] = df["kwh"] * df["emissions_factor_kg_per_kwh"]
    df["co2e_lbs"] = df["co2e_kg"] * KG_TO_LBS
    return df


def build_summary(df: pd.DataFrame) -> Dict[str, Any]:
    """Compute aggregate stats across all processed rows."""
    return {
        "records_processed": len(df),
        "total_kwh": round(df["kwh"].sum(), 4),
        "total_co2e_kg": round(df["co2e_kg"].sum(), 4),
        "total_co2e_lbs": round(df["co2e_lbs"].sum(), 4),
        "avg_emissions_factor": round(df["emissions_factor_kg_per_kwh"].mean(), 6),
    }
