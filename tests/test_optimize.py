import numpy as np
import pytest

from app.optimize import (
    OptimizationResult,
    SwapRecord,
    compute_emissions,
    optimize_demand,
    swap_benefit,
)


# ---------------------------------------------------------------------------
# compute_emissions
# ---------------------------------------------------------------------------

class TestComputeEmissions:
    def test_basic(self):
        demand = np.array([1.0, 2.0])
        intensity = np.array([10.0, 5.0])
        assert compute_emissions(demand, intensity) == pytest.approx(20.0)

    def test_zero_demand(self):
        demand = np.array([0.0, 0.0, 0.0])
        intensity = np.array([100.0, 200.0, 300.0])
        assert compute_emissions(demand, intensity) == pytest.approx(0.0)

    def test_zero_intensity(self):
        demand = np.array([1.0, 2.0, 3.0])
        intensity = np.array([0.0, 0.0, 0.0])
        assert compute_emissions(demand, intensity) == pytest.approx(0.0)

    def test_single_element(self):
        demand = np.array([3.5])
        intensity = np.array([4.0])
        assert compute_emissions(demand, intensity) == pytest.approx(14.0)

    def test_negative_demand(self):
        # Negative demand (solar export) contributes negatively to emissions
        demand = np.array([2.0, -1.0])
        intensity = np.array([10.0, 10.0])
        assert compute_emissions(demand, intensity) == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# swap_benefit
# ---------------------------------------------------------------------------

class TestSwapBenefit:
    def test_beneficial_swap(self):
        # High demand at low-intensity hour (0), low demand at high-intensity hour (1)
        # Moving high demand to high-intensity hour is bad; swapping means we move
        # the HIGH demand to the LOW intensity → beneficial
        # demand=[1, 2], intensity=[1, 10]: benefit = (1-2)*(1-10) = (-1)*(-9) = 9
        demand = np.array([1.0, 2.0])
        intensity = np.array([1.0, 10.0])
        assert swap_benefit(demand, intensity, 0, 1) == pytest.approx(9.0)

    def test_no_benefit_equal_demand(self):
        demand = np.array([3.0, 3.0])
        intensity = np.array([5.0, 50.0])
        assert swap_benefit(demand, intensity, 0, 1) == pytest.approx(0.0)

    def test_no_benefit_equal_intensity(self):
        demand = np.array([1.0, 5.0])
        intensity = np.array([20.0, 20.0])
        assert swap_benefit(demand, intensity, 0, 1) == pytest.approx(0.0)

    def test_harmful_swap(self):
        # Already has high demand at high intensity: swapping makes it worse
        # demand=[2, 1], intensity=[10, 1]: benefit = (2-1)*(10-1) = 1*9 = 9 → positive
        # So flip it: demand=[2, 1], intensity=[1, 10]: benefit = (2-1)*(1-10) = 1*(-9) = -9
        demand = np.array([2.0, 1.0])
        intensity = np.array([1.0, 10.0])
        assert swap_benefit(demand, intensity, 0, 1) < 0

    def test_symmetry(self):
        demand = np.array([1.0, 2.0, 3.0])
        intensity = np.array([5.0, 15.0, 8.0])
        assert swap_benefit(demand, intensity, 0, 2) == pytest.approx(
            swap_benefit(demand, intensity, 2, 0)
        )

    def test_formula(self):
        demand = np.array([4.0, 1.0])
        intensity = np.array([2.0, 8.0])
        expected = (demand[0] - demand[1]) * (intensity[0] - intensity[1])
        assert swap_benefit(demand, intensity, 0, 1) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# OptimizationResult.summary
# ---------------------------------------------------------------------------

class TestOptimizationResultSummary:
    def _make_result(self, total_demand=100.0, demand_moved=5.0):
        return OptimizationResult(
            original_emissions=1000.0,
            optimized_emissions=950.0,
            reduction_absolute=50.0,
            reduction_percent=5.0,
            num_swaps=2,
            demand_moved=demand_moved,
            demand_budget=10.0,
            total_demand=total_demand,
            permutation=np.array([0, 1]),
            optimized_demand=np.array([1.0, 2.0]),
            swaps=[],
        )

    def test_contains_key_labels(self):
        s = self._make_result().summary()
        assert "Original emissions" in s
        assert "Optimized emissions" in s
        assert "Reduction" in s
        assert "Swaps" in s
        assert "Demand moved" in s

    def test_zero_total_demand_no_division_error(self):
        result = self._make_result(total_demand=0.0, demand_moved=0.0)
        s = result.summary()  # Should not raise ZeroDivisionError
        assert "0.0%" in s


# ---------------------------------------------------------------------------
# optimize_demand
# ---------------------------------------------------------------------------

class TestOptimizeDemand:
    def test_returns_optimization_result(self):
        result = optimize_demand(
            np.array([1.0, 2.0]),
            np.array([1.0, 10.0]),
        )
        assert isinstance(result, OptimizationResult)

    def test_single_obvious_swap(self):
        # demand=[1, 2], intensity=[1, 10]
        # benefit(0,1) = (1-2)*(1-10) = 9 > 0 → swap fires
        # original: 1*1 + 2*10 = 21; after: 2*1 + 1*10 = 12; reduction = 9
        demand = np.array([1.0, 2.0])
        intensity = np.array([1.0, 10.0])
        result = optimize_demand(demand, intensity, budget_fraction=1.0, max_shift_hours=1)

        assert result.num_swaps == 1
        assert result.original_emissions == pytest.approx(21.0)
        assert result.optimized_emissions == pytest.approx(12.0)
        assert result.reduction_absolute == pytest.approx(9.0)

    def test_demand_conservation(self):
        demand = np.array([1.0, 3.0, 2.0, 5.0, 1.5])
        intensity = np.array([10.0, 5.0, 20.0, 3.0, 15.0])
        result = optimize_demand(demand, intensity, budget_fraction=0.5, max_shift_hours=3)

        assert np.sum(result.optimized_demand) == pytest.approx(np.sum(demand))

    def test_permutation_is_valid(self):
        N = 6
        demand = np.array([1.0, 3.0, 2.0, 5.0, 1.5, 4.0])
        intensity = np.array([10.0, 5.0, 20.0, 3.0, 15.0, 8.0])
        result = optimize_demand(demand, intensity, budget_fraction=0.5, max_shift_hours=3)

        assert len(result.permutation) == N
        assert list(np.sort(result.permutation)) == list(range(N))

    def test_optimized_demand_matches_permutation(self):
        demand = np.array([1.0, 3.0, 2.0, 5.0])
        intensity = np.array([10.0, 5.0, 20.0, 3.0])
        result = optimize_demand(demand, intensity, budget_fraction=1.0, max_shift_hours=3)

        for k in range(len(demand)):
            assert result.optimized_demand[k] == pytest.approx(demand[result.permutation[k]])

    def test_emissions_reduced(self):
        demand = np.array([1.0, 2.0, 3.0, 4.0])
        intensity = np.array([1.0, 10.0, 2.0, 9.0])
        result = optimize_demand(demand, intensity, budget_fraction=1.0, max_shift_hours=3)

        assert result.optimized_emissions <= result.original_emissions

    def test_result_math(self):
        demand = np.array([1.0, 2.0, 3.0])
        intensity = np.array([5.0, 10.0, 1.0])
        result = optimize_demand(demand, intensity, budget_fraction=1.0, max_shift_hours=2)

        assert result.reduction_absolute == pytest.approx(
            result.original_emissions - result.optimized_emissions
        )
        if result.original_emissions > 0:
            assert result.reduction_percent == pytest.approx(
                result.reduction_absolute / result.original_emissions * 100
            )

    def test_budget_respected(self):
        demand = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        intensity = np.array([1.0, 10.0, 2.0, 9.0, 3.0])
        result = optimize_demand(demand, intensity, budget_fraction=0.2, max_shift_hours=3)

        assert result.demand_moved <= result.demand_budget + 1e-9

    def test_zero_budget_no_swaps(self):
        demand = np.array([1.0, 2.0, 3.0])
        intensity = np.array([1.0, 10.0, 2.0])
        result = optimize_demand(demand, intensity, budget_fraction=0.0, max_shift_hours=3)

        assert result.num_swaps == 0

    def test_max_shift_constraint(self):
        # With max_shift_hours=1, hours 0 and 3 (distance=3) cannot be candidates
        # Make the only beneficial pairing be (0,3) — which is blocked by K=1
        demand = np.array([1.0, 1.0, 1.0, 2.0])
        intensity = np.array([1.0, 1.0, 1.0, 10.0])
        # Only pair (2,3) is adjacent and has different intensity; (0,3),(1,3) are too far
        result = optimize_demand(demand, intensity, budget_fraction=1.0, max_shift_hours=1)

        # No hour 0 or 1 should be swapped with hour 3
        for swap in result.swaps:
            assert not (swap.hour_i == 0 and swap.hour_j == 3)
            assert not (swap.hour_i == 1 and swap.hour_j == 3)

    def test_each_hour_swaps_at_most_once(self):
        demand = np.array([1.0, 4.0, 2.0, 5.0, 1.5, 3.0])
        intensity = np.array([2.0, 20.0, 3.0, 18.0, 4.0, 15.0])
        result = optimize_demand(demand, intensity, budget_fraction=1.0, max_shift_hours=5)

        involved_hours = []
        for swap in result.swaps:
            involved_hours.extend([swap.hour_i, swap.hour_j])

        assert len(involved_hours) == len(set(involved_hours)), (
            "An hour appeared in more than one swap"
        )

    def test_uniform_intensity_no_swaps(self):
        demand = np.array([1.0, 2.0, 3.0, 4.0])
        intensity = np.array([10.0, 10.0, 10.0, 10.0])
        result = optimize_demand(demand, intensity, budget_fraction=1.0, max_shift_hours=3)

        assert result.num_swaps == 0

    def test_empty_arrays(self):
        result = optimize_demand(
            np.array([]),
            np.array([]),
            budget_fraction=0.5,
            max_shift_hours=3,
        )
        assert result.num_swaps == 0
        assert result.original_emissions == pytest.approx(0.0)
        assert result.optimized_emissions == pytest.approx(0.0)
        assert len(result.swaps) == 0

    def test_single_element(self):
        result = optimize_demand(
            np.array([5.0]),
            np.array([100.0]),
            budget_fraction=1.0,
            max_shift_hours=3,
        )
        assert result.num_swaps == 0
        assert result.original_emissions == pytest.approx(500.0)
        assert result.optimized_emissions == pytest.approx(500.0)

    def test_mismatched_lengths_raises(self):
        with pytest.raises(AssertionError):
            optimize_demand(
                np.array([1.0, 2.0, 3.0]),
                np.array([1.0, 2.0]),
            )

    def test_swap_record_fields(self):
        demand = np.array([1.0, 2.0])
        intensity = np.array([1.0, 10.0])
        result = optimize_demand(demand, intensity, budget_fraction=1.0, max_shift_hours=1)

        assert result.num_swaps == 1
        swap = result.swaps[0]
        assert isinstance(swap, SwapRecord)
        assert swap.hour_i == 0
        assert swap.hour_j == 1
        assert swap.demand_moved == pytest.approx(demand[0] + demand[1])  # 1+2=3
        assert swap.emission_reduction > 0
