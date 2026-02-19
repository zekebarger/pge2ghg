import datetime

import pandas as pd
import pytest

from app.calculations import (
    parse_pge_gas_csv,
    calculate_gas_emissions,
    build_gas_result,
    THERMS_TO_KG_CO2,
    KG_TO_LBS,
)


# ---------------------------------------------------------------------------
# parse_pge_gas_csv
# ---------------------------------------------------------------------------

class TestParsePgeGasCsv:
    def test_valid_csv_returns_date_and_therms(self, minimal_pge_gas_csv_bytes):
        df = parse_pge_gas_csv(minimal_pge_gas_csv_bytes)

        assert list(df.columns) == ["date", "therms"]
        assert len(df) == 3

        assert df["therms"].iloc[0] == pytest.approx(1.04)
        assert df["therms"].iloc[1] == pytest.approx(0.00)
        assert df["therms"].iloc[2] == pytest.approx(2.08)

    def test_date_column_is_date_not_datetime(self, minimal_pge_gas_csv_bytes):
        df = parse_pge_gas_csv(minimal_pge_gas_csv_bytes)
        assert isinstance(df["date"].iloc[0], datetime.date)
        assert not isinstance(df["date"].iloc[0], datetime.datetime)

    def test_missing_type_header_raises(self):
        bad_csv = b"account,,,\nname,Test,,\nno header here\n"
        with pytest.raises(ValueError, match="TYPE,"):
            parse_pge_gas_csv(bad_csv)

    def test_no_gas_usage_rows_raises(self):
        csv = (
            b"account_number,,,,,\n"
            b"TYPE,DATE,START TIME,END TIME,USAGE (therms),COST,NOTES\n"
            b"Electric usage,2025-10-14,00:00,23:59,1.04,$2.76,\n"
        )
        with pytest.raises(ValueError, match="Natural gas usage"):
            parse_pge_gas_csv(csv)


# ---------------------------------------------------------------------------
# calculate_gas_emissions
# ---------------------------------------------------------------------------

class TestCalculateGasEmissions:
    def test_known_therms_produce_correct_co2(self):
        df = pd.DataFrame({"date": [datetime.date(2025, 10, 14)], "therms": [1.0]})
        result = calculate_gas_emissions(df)

        assert result["co2_kg"].iloc[0] == pytest.approx(5.312)
        assert result["co2_lbs"].iloc[0] == pytest.approx(5.312 * KG_TO_LBS)

    def test_zero_therms_produce_zero_co2(self):
        df = pd.DataFrame({"date": [datetime.date(2025, 10, 15)], "therms": [0.0]})
        result = calculate_gas_emissions(df)

        assert result["co2_kg"].iloc[0] == pytest.approx(0.0)
        assert result["co2_lbs"].iloc[0] == pytest.approx(0.0)

    def test_does_not_mutate_input(self):
        df = pd.DataFrame({"date": [datetime.date(2025, 10, 14)], "therms": [1.04]})
        original_columns = list(df.columns)
        calculate_gas_emissions(df)
        assert list(df.columns) == original_columns


# ---------------------------------------------------------------------------
# build_gas_result
# ---------------------------------------------------------------------------

class TestBuildGasResult:
    def _make_result_df(self):
        df = pd.DataFrame({
            "date": [datetime.date(2025, 10, 14), datetime.date(2025, 10, 15), datetime.date(2025, 10, 16)],
            "therms": [1.04, 0.00, 2.08],
        })
        return calculate_gas_emissions(df)

    def test_totals_aggregate_correctly(self):
        df = self._make_result_df()
        result = build_gas_result(df)

        assert result["records_processed"] == 3
        assert result["total_therms"] == pytest.approx(round(df["therms"].sum(), 4))
        assert result["total_co2_kg"] == pytest.approx(round(df["co2_kg"].sum(), 4))
        assert result["total_co2_lbs"] == pytest.approx(round(df["co2_lbs"].sum(), 4))

    def test_each_record_has_expected_keys(self):
        df = self._make_result_df()
        result = build_gas_result(df)

        assert len(result["records"]) == 3
        for rec in result["records"]:
            assert set(rec.keys()) == {"date", "therms", "co2_kg", "co2_lbs"}
