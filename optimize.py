"""
Demand Shifting Optimizer
=========================
Given fixed carbon intensity and electricity demand arrays, find a permutation
of demand values that minimizes total emissions, subject to:
  - At most B = round(f * N) demand values are moved from their original slot
  - Each moved value can only go to a slot within ±K hours of its origin

Approach: greedy pairwise swaps, with optional 3-cycle improvement pass.
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SwapRecord:
    """Records a single swap operation."""
    hour_i: int
    hour_j: int
    emission_reduction: float  # positive = good (emissions saved)


@dataclass
class OptimizationResult:
    """Full results from the optimization."""
    original_emissions: float
    optimized_emissions: float
    reduction_absolute: float
    reduction_percent: float
    num_hours_moved: int
    budget_total: int
    permutation: np.ndarray  # permutation[i] = original index of demand now at hour i
    optimized_demand: np.ndarray
    swaps: list[SwapRecord] = field(default_factory=list)


def compute_emissions(demand: np.ndarray, carbon_intensity: np.ndarray) -> float:
    """Total emissions = sum of demand_i * carbon_intensity_i."""
    return float(np.dot(demand, carbon_intensity))


def swap_benefit(
        demand: np.ndarray,
        carbon_intensity: np.ndarray,
        i: int,
        j: int,
) -> float:
    """
    Emission reduction from swapping demand at hours i and j.
    Positive means the swap reduces emissions.

    Before swap: d[i]*c[i] + d[j]*c[j]
    After swap:  d[j]*c[i] + d[i]*c[j]
    Benefit = before - after = (d[i] - d[j]) * (c[i] - c[j])
    """
    return float((demand[i] - demand[j]) * (carbon_intensity[i] - carbon_intensity[j]))


def _count_displaced(permutation: np.ndarray) -> int:
    """Count how many indices are not in their original position."""
    return int(np.sum(permutation != np.arange(len(permutation))))


def _origin_distance(permutation: np.ndarray, idx: int) -> int:
    """How far the value currently at `idx` is from its original position."""
    return abs(permutation[idx] - idx)


def optimize_demand(
        demand: np.ndarray,
        carbon_intensity: np.ndarray,
        budget_fraction: float = 0.05,
        max_shift_hours: int = 3,
        do_3cycle_pass: bool = False,
        verbose: bool = False,
) -> OptimizationResult:
    """
    Find a low-emission permutation of demand via greedy pairwise swaps.

    Parameters
    ----------
    demand : array of shape (N,)
        Electricity demand per hour (e.g., kWh).
    carbon_intensity : array of shape (N,)
        Carbon intensity per hour (e.g., gCO2/kWh).
    budget_fraction : float
        Fraction of hours allowed to be displaced (0 < f <= 1).
    max_shift_hours : int
        Maximum distance (K) a demand value can move from its original slot.
    do_3cycle_pass : bool
        If True, run an additional pass looking for beneficial 3-cycles.
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

    B = round(budget_fraction * N)
    K = max_shift_hours

    # Working copies
    d = demand.copy()
    perm = np.arange(N)  # perm[i] = original index of demand value now at position i
    swaps: list[SwapRecord] = []

    original_emissions = compute_emissions(demand, carbon_intensity)

    if verbose:
        print(f"N={N}, Budget B={B} slots ({budget_fraction:.1%}), K={K} hours")
        print(f"Original emissions: {original_emissions:,.1f}")

    # --- Greedy pairwise swap phase ---
    while True:
        displaced = _count_displaced(perm)
        budget_remaining = B - displaced

        best_benefit = 0.0
        best_pair: Optional[tuple[int, int]] = None

        for i in range(N):
            # Only look at j > i to avoid duplicate pairs
            j_min = max(i + 1, 0)
            j_max = min(N, i + K + 1)

            for j in range(j_min, j_max):
                # Check proximity constraint: after swap, the value originally
                # at perm[i] would sit at position j, and vice versa.
                # Distance from origin for each value after the swap:
                origin_i = perm[i]  # original home of value currently at i
                origin_j = perm[j]  # original home of value currently at j

                if abs(origin_i - j) > K or abs(origin_j - i) > K:
                    continue  # violates proximity constraint

                # Check budget: how does this swap change the displaced count?
                currently_home_i = (perm[i] == i)
                currently_home_j = (perm[j] == j)
                would_be_home_i = (origin_j == i)  # after swap, perm[i] = origin_j
                would_be_home_j = (origin_i == j)  # after swap, perm[j] = origin_i

                delta_displaced = (
                        (0 if would_be_home_i else 1) - (0 if currently_home_i else 1)
                        + (0 if would_be_home_j else 1) - (0 if currently_home_j else 1)
                )

                if displaced + delta_displaced > B:
                    continue  # would exceed budget

                benefit = swap_benefit(d, carbon_intensity, i, j)
                if benefit > best_benefit:
                    best_benefit = benefit
                    best_pair = (i, j)

        if best_pair is None:
            if verbose:
                print("No more beneficial swaps found.")
            break

        i, j = best_pair
        # Apply the swap
        d[i], d[j] = d[j], d[i]
        perm[i], perm[j] = perm[j], perm[i]
        swaps.append(SwapRecord(i, j, best_benefit))

        if verbose:
            new_displaced = _count_displaced(perm)
            print(
                f"  Swap hours {i} <-> {j}: "
                f"save {best_benefit:,.2f} gCO2, "
                f"displaced={new_displaced}/{B}"
            )

    # --- Optional 3-cycle improvement pass ---
    if do_3cycle_pass:
        _run_3cycle_pass(d, carbon_intensity, perm, swaps, B, K, verbose)

    optimized_emissions = compute_emissions(d, carbon_intensity)
    reduction = original_emissions - optimized_emissions
    reduction_pct = (reduction / original_emissions * 100) if original_emissions > 0 else 0.0

    return OptimizationResult(
        original_emissions=original_emissions,
        optimized_emissions=optimized_emissions,
        reduction_absolute=reduction,
        reduction_percent=reduction_pct,
        num_hours_moved=int(_count_displaced(perm)),
        budget_total=B,
        permutation=perm,
        optimized_demand=d,
        swaps=swaps,
    )


def _run_3cycle_pass(
        d: np.ndarray,
        carbon_intensity: np.ndarray,
        perm: np.ndarray,
        swaps: list[SwapRecord],
        B: int,
        K: int,
        verbose: bool,
) -> None:
    """
    Look for beneficial 3-cycles: rotate demand among (i, j, k) so that
    d[i]->j, d[j]->k, d[k]->i. This catches improvements that pairwise
    swaps miss.

    O(N * K^2) - don't use this :)
    """
    N = len(d)
    improved = True

    while improved:
        improved = False
        displaced = _count_displaced(perm)

        best_benefit = 0.0
        best_triple = None

        for i in range(N):
            for j in range(max(0, i - K), min(N, i + K + 1)):
                if j == i:
                    continue
                for k in range(max(0, j - K), min(N, j + K + 1)):
                    if k == i or k == j:
                        continue
                    # Also need i and k within K of each other for the cycle
                    if abs(i - k) > K:
                        continue

                    # Origins of values currently at i, j, k
                    oi, oj, ok = perm[i], perm[j], perm[k]

                    # After rotation i->j, j->k, k->i:
                    # position i gets value from k (origin ok)
                    # position j gets value from i (origin oi)
                    # position k gets value from j (origin oj)
                    if abs(ok - i) > K or abs(oi - j) > K or abs(oj - k) > K:
                        continue

                    # Budget check
                    before_home = (oi == i) + (oj == j) + (ok == k)
                    after_home = (ok == i) + (oi == j) + (oj == k)
                    delta = (3 - after_home) - (3 - before_home)
                    if displaced + delta > B:
                        continue

                    # Benefit: before - after emissions for these 3 positions
                    before = d[i] * carbon_intensity[i] + d[j] * carbon_intensity[j] + d[k] * carbon_intensity[k]
                    # After: d[k]->i, d[i]->j, d[j]->k
                    after = d[k] * carbon_intensity[i] + d[i] * carbon_intensity[j] + d[j] * carbon_intensity[k]
                    benefit = before - after

                    if benefit > best_benefit:
                        best_benefit = benefit
                        best_triple = (i, j, k)

        if best_triple is not None and best_benefit > 1e-10:
            i, j, k = best_triple
            # Rotate: i <- k, j <- i, k <- j
            d[i], d[j], d[k] = d[k], d[i], d[j]
            perm[i], perm[j], perm[k] = perm[k], perm[i], perm[j]
            improved = True

            if verbose:
                print(
                    f"  3-cycle ({i}, {j}, {k}): "
                    f"save {best_benefit:,.2f} gCO2"
                )


# ---- Demo / Example Usage ----

if __name__ == "__main__":
    np.random.seed(42)
    N = 720  # ~one month of hours

    # Simulate carbon intensity with a daily pattern + noise
    hours = np.arange(N)
    daily_pattern = 50 * np.sin(2 * np.pi * (hours % 24) / 24 - np.pi / 3) + 200
    carbon_intensity = daily_pattern + np.random.normal(0, 15, N)
    carbon_intensity = np.clip(carbon_intensity, 50, 400)

    # Simulate demand with a different daily pattern + noise
    demand_pattern = 100 * np.sin(2 * np.pi * (hours % 24) / 24 + np.pi / 6) + 500
    demand = demand_pattern + np.random.normal(0, 30, N)
    demand = np.clip(demand, 100, 1000)

    print("=" * 60)
    print("Demand Shifting Optimization Demo")
    print("=" * 60)

    for f, K in [(.05, 4)]: #(0.05, 3), (0.10, 6), (0.20, 12)]:
        print(f"\n--- f={f:.0%} budget, K=±{K} hours ---")
        result = optimize_demand(
            demand,
            carbon_intensity,
            budget_fraction=f,
            max_shift_hours=K,
            do_3cycle_pass=False,
            verbose=True,
        )
        print(f"  Result: {result.reduction_absolute:,.0f} gCO2 saved "
              f"({result.reduction_percent:.2f}% reduction)")
        print(f"  Hours moved: {result.num_hours_moved} / {result.budget_total}")
        if result.swaps:
            top = sorted(result.swaps, key=lambda s: s.emission_reduction, reverse=True)[:3]
            print(f"  Top 3 swaps:")
            for s in top:
                print(f"    hours {s.hour_i} <-> {s.hour_j}: {s.emission_reduction:,.1f} gCO2")