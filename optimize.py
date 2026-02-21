"""
Demand Shifting Optimizer
=========================
Given fixed carbon intensity and electricity demand arrays, find a permutation
of demand values that minimizes total emissions, subject to:
  - At most a fraction f of total demand (kWh) can be moved from its original slot
  - Each moved value can only go to a slot within ±K hours of its origin
  - Each hour participates in at most one swap

Approach: greedy pairwise swaps sorted by emission benefit, skipping swaps that
would exceed the demand budget or involve an already-locked hour.
"""

import numpy as np
from dataclasses import dataclass, field


@dataclass
class SwapRecord:
    """Records a single swap operation."""
    hour_i: int
    hour_j: int
    demand_moved: float  # sum of demand at both hours
    emission_reduction: float  # positive = good (emissions saved)


@dataclass
class OptimizationResult:
    """Full results from the optimization."""
    original_emissions: float
    optimized_emissions: float
    reduction_absolute: float
    reduction_percent: float
    num_swaps: int
    demand_moved: float
    demand_budget: float
    total_demand: float
    permutation: np.ndarray
    optimized_demand: np.ndarray
    swaps: list[SwapRecord] = field(default_factory=list)

    def summary(self) -> str:
        pct_moved = (self.demand_moved / self.total_demand * 100) if self.total_demand > 0 else 0
        lines = [
            f"Original emissions:  {self.original_emissions:>14,.1f} gCO2",
            f"Optimized emissions: {self.optimized_emissions:>14,.1f} gCO2",
            f"Reduction:           {self.reduction_absolute:>14,.1f} gCO2 "
            f"({self.reduction_percent:.2f}%)",
            f"Swaps:               {self.num_swaps}",
            f"Demand moved:        {self.demand_moved:>14,.1f} / "
            f"{self.demand_budget:,.1f} kWh "
            f"({pct_moved:.1f}% of total)",
        ]
        return "\n".join(lines)


def compute_emissions(demand: np.ndarray, carbon_intensity: np.ndarray) -> float:
    """Total emissions = sum of demand_i * carbon_intensity_i."""
    return float(np.dot(demand, carbon_intensity))


def swap_benefit(demand: np.ndarray, carbon_intensity: np.ndarray, i: int, j: int) -> float:
    """
    Emission reduction from swapping demand at hours i and j.
    Positive means the swap reduces emissions.

    Benefit = (d[i] - d[j]) * (c[i] - c[j])
    """
    return float((demand[i] - demand[j]) * (carbon_intensity[i] - carbon_intensity[j]))


def optimize_demand(
    demand: np.ndarray,
    carbon_intensity: np.ndarray,
    budget_fraction: float = 0.05,
    max_shift_hours: int = 3,
    verbose: bool = False,
) -> OptimizationResult:
    """
    Find a low-emission permutation of demand via greedy pairwise swaps.
    Each hour can participate in at most one swap.

    Parameters
    ----------
    demand : array of shape (N,)
        Electricity demand per hour (e.g., kWh).
    carbon_intensity : array of shape (N,)
        Carbon intensity per hour (e.g., gCO2/kWh).
    budget_fraction : float
        Fraction of total demand (kWh) allowed to be moved (0 < f <= 1).
    max_shift_hours : int
        Maximum distance (K) a demand value can move from its original slot.
    verbose : bool
        Print progress info.

    Returns
    -------
    OptimizationResult
    """
    demand = np.asarray(demand, dtype=float)
    carbon_intensity = np.asarray(carbon_intensity, dtype=float)
    N = len(demand)
    assert len(carbon_intensity) == N, "Arrays must have the same length."

    total_demand = float(np.sum(demand))
    demand_budget = budget_fraction * total_demand
    K = max_shift_hours

    # Working copies
    d = demand.copy()
    perm = np.arange(N)
    locked = np.zeros(N, dtype=bool)
    swaps: list[SwapRecord] = []
    demand_moved = 0.0

    original_emissions = compute_emissions(demand, carbon_intensity)

    if verbose:
        print(f"N={N}, Demand budget={demand_budget:,.1f} kWh "
              f"({budget_fraction:.1%} of {total_demand:,.1f}), K=±{K}h")
        print(f"Original emissions: {original_emissions:,.1f}")

    # --- Precompute all candidate swap benefits ---
    candidates = []
    for i in range(N):
        for j in range(i + 1, min(N, i + K + 1)):
            b = swap_benefit(d, carbon_intensity, i, j)
            if b > 0:
                candidates.append((b, i, j))

    candidates.sort(reverse=True)

    if verbose:
        print(f"Candidate beneficial swaps: {len(candidates)}")

    # --- Greedily pick best non-conflicting swaps within demand budget ---
    for benefit, i, j in candidates:
        if locked[i] or locked[j]:
            continue

        swap_demand = d[i] + d[j]
        if demand_moved + swap_demand > demand_budget:
            continue  # skip this swap, but keep looking for smaller ones

        # Apply swap
        d[i], d[j] = d[j], d[i]
        perm[i], perm[j] = perm[j], perm[i]
        locked[i] = True
        locked[j] = True
        demand_moved += swap_demand
        swaps.append(SwapRecord(i, j, swap_demand, benefit))

        if verbose:
            print(f"  Swap hours {i:>3} <-> {j:<3}: "
                  f"save {benefit:>10,.2f} gCO2, "
                  f"moved {swap_demand:>8,.1f} kWh  "
                  f"[{demand_moved:,.1f}/{demand_budget:,.1f}]")

    optimized_emissions = compute_emissions(d, carbon_intensity)
    reduction = original_emissions - optimized_emissions
    reduction_pct = (reduction / original_emissions * 100) if original_emissions > 0 else 0.0

    return OptimizationResult(
        original_emissions=original_emissions,
        optimized_emissions=optimized_emissions,
        reduction_absolute=reduction,
        reduction_percent=reduction_pct,
        num_swaps=len(swaps),
        demand_moved=demand_moved,
        demand_budget=demand_budget,
        total_demand=total_demand,
        permutation=perm,
        optimized_demand=d,
        swaps=swaps,
    )
