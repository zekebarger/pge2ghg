import pandas as pd
import pytest


# Minimal PG&E Green Button CSV with 3 rows: two positive, one negative (solar export)
MINIMAL_PGE_CSV = """\
account_number,,,,,
account_name,Test Account,,,,
TYPE,DATE,START TIME,END TIME,USAGE (kWh),NOTES
Electric usage,2024-01-15,00:00,00:15,0.500,
Electric usage,2024-01-15,00:15,00:30,-0.250,
Electric usage,2024-01-15,00:30,00:45,0.750,
"""


@pytest.fixture
def minimal_pge_csv_bytes():
    return MINIMAL_PGE_CSV.encode("utf-8")


@pytest.fixture
def sample_usage_df():
    """Small usage DataFrame with UTC-aware timestamps; includes a negative kWh row."""
    timestamps = pd.to_datetime([
        "2024-01-15 08:00:00+00:00",
        "2024-01-15 08:15:00+00:00",
        "2024-01-15 08:30:00+00:00",
    ])
    return pd.DataFrame({
        "timestamp": timestamps,
        "kwh": [0.500, -0.250, 0.750],
    })


@pytest.fixture
def minimal_pge_gas_csv_bytes():
    csv = (
        "account_number,,,,,\n"
        "Name,Test Account,,,,,\n"
        "TYPE,DATE,START TIME,END TIME,USAGE (therms),COST,NOTES\n"
        "Natural gas usage,2025-10-14,00:00,23:59,1.04,$2.76,\n"
        "Natural gas usage,2025-10-15,00:00,23:59,0.00,$0.00,\n"
        "Natural gas usage,2025-10-16,00:00,23:59,2.08,$5.52,\n"
    )
    return csv.encode("utf-8")


@pytest.fixture
def sample_intensity_df():
    """Intensity DataFrame aligned to the sample_usage_df timestamps."""
    timestamps = pd.to_datetime([
        "2024-01-15 08:00:00+00:00",
        "2024-01-15 08:05:00+00:00",
        "2024-01-15 08:10:00+00:00",
        "2024-01-15 08:15:00+00:00",
        "2024-01-15 08:20:00+00:00",
        "2024-01-15 08:25:00+00:00",
        "2024-01-15 08:30:00+00:00",
    ])
    return pd.DataFrame({
        "timestamp": timestamps,
        # 220.462 lbs/MWh → 0.0001 kg/kWh exactly (220.462 / 2204.62 = 0.1 / 1000)
        "value_lbs_per_mwh": [220.462] * 7,
    })
