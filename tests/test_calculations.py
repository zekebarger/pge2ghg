import pandas as pd
import pytest

from app.calculations import (
    parse_pge_csv,
    join_usage_with_intensity,
    calculate_emissions,
    build_result,
    LBS_PER_MWH_TO_KG_PER_KWH,
    KG_TO_LBS,
)


# ---------------------------------------------------------------------------
# parse_pge_csv
# ---------------------------------------------------------------------------

class TestParsePgeCsv:
    def test_valid_csv_returns_utc_timestamps_and_kwh(self, minimal_pge_csv_bytes):
        df = parse_pge_csv(minimal_pge_csv_bytes)

        assert list(df.columns) == ["timestamp", "kwh"]
        assert len(df) == 3

        # Timestamps must be UTC-aware
        assert df["timestamp"].dt.tz is not None
        assert str(df["timestamp"].dt.tz) == "UTC"

        # 2024-01-15 00:00 PST (UTC-8) → 2024-01-15 08:00 UTC
        assert df["timestamp"].iloc[0] == pd.Timestamp("2024-01-15 08:00:00", tz="UTC")

        assert df["kwh"].iloc[0] == pytest.approx(0.500)
        assert df["kwh"].iloc[1] == pytest.approx(-0.250)
        assert df["kwh"].iloc[2] == pytest.approx(0.750)

    def test_missing_type_header_raises(self):
        bad_csv = b"account,,,\nname,Test,,\nno header here\n"
        with pytest.raises(ValueError, match="TYPE,"):
            parse_pge_csv(bad_csv)

    def test_no_electric_usage_rows_raises(self):
        csv = (
            b"account_number,,,\n"
            b"TYPE,DATE,START TIME,END TIME,USAGE (kWh),NOTES\n"
            b"Gas usage,2024-01-15,00:00,00:15,10.0,\n"
        )
        with pytest.raises(ValueError, match="Electric usage"):
            parse_pge_csv(csv)

    def test_negative_kwh_passes_through(self, minimal_pge_csv_bytes):
        df = parse_pge_csv(minimal_pge_csv_bytes)
        assert (df["kwh"] < 0).any(), "Expected at least one negative kWh row"


# ---------------------------------------------------------------------------
# join_usage_with_intensity
# ---------------------------------------------------------------------------

class TestJoinUsageWithIntensity:
    def test_aligned_timestamps_get_correct_intensity(self, sample_usage_df, sample_intensity_df):
        merged = join_usage_with_intensity(sample_usage_df, sample_intensity_df)

        assert "emissions_factor_kg_per_kwh" in merged.columns
        assert len(merged) == len(sample_usage_df)

        expected_factor = 220.462 / LBS_PER_MWH_TO_KG_PER_KWH
        for val in merged["emissions_factor_kg_per_kwh"]:
            assert val == pytest.approx(expected_factor)

    def test_no_preceding_intensity_raises(self, sample_usage_df):
        # Intensity starts after the first usage row → that row has no match
        late_intensity = pd.DataFrame({
            "timestamp": pd.to_datetime(["2024-01-15 09:00:00+00:00"]),
            "value_lbs_per_mwh": [220.462],
        })
        with pytest.raises(ValueError, match="matched"):
            join_usage_with_intensity(sample_usage_df, late_intensity)


# ---------------------------------------------------------------------------
# calculate_emissions
# ---------------------------------------------------------------------------

class TestCalculateEmissions:
    def _make_df(self, kwh_values):
        factor = 220.462 / LBS_PER_MWH_TO_KG_PER_KWH  # 0.0001 kg/kWh
        return pd.DataFrame({
            "kwh": kwh_values,
            "emissions_factor_kg_per_kwh": [factor] * len(kwh_values),
        })

    def test_positive_kwh_produces_correct_co2e(self):
        df = self._make_df([1.0])
        result = calculate_emissions(df)

        expected_kg = 1.0 * (220.462 / LBS_PER_MWH_TO_KG_PER_KWH)
        assert result["co2e_kg"].iloc[0] == pytest.approx(expected_kg)
        assert result["co2e_lbs"].iloc[0] == pytest.approx(expected_kg * KG_TO_LBS)

    def test_negative_kwh_produces_negative_co2e(self):
        df = self._make_df([-0.250])
        result = calculate_emissions(df)

        assert result["co2e_kg"].iloc[0] < 0
        assert result["co2e_lbs"].iloc[0] < 0

        expected_kg = -0.250 * (220.462 / LBS_PER_MWH_TO_KG_PER_KWH)
        assert result["co2e_kg"].iloc[0] == pytest.approx(expected_kg)


# ---------------------------------------------------------------------------
# build_result
# ---------------------------------------------------------------------------

class TestBuildResult:
    def test_aggregates_and_records(self, sample_usage_df, sample_intensity_df):
        merged = join_usage_with_intensity(sample_usage_df, sample_intensity_df)
        with_emissions = calculate_emissions(merged)
        result = build_result(with_emissions)

        assert result["records_processed"] == 3
        assert len(result["records"]) == 3

        assert result["total_kwh"] == pytest.approx(round(with_emissions["kwh"].sum(), 4))
        assert result["total_co2e_kg"] == pytest.approx(round(with_emissions["co2e_kg"].sum(), 4))
        assert result["total_co2e_lbs"] == pytest.approx(round(with_emissions["co2e_lbs"].sum(), 4))

        for rec in result["records"]:
            assert set(rec.keys()) >= {"timestamp", "kwh", "emissions_factor_kg_per_kwh", "co2e_kg", "co2e_lbs"}
