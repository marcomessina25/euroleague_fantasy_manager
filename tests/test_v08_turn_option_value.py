"""Unit tests for V0.8 Turn 1 -> Turn 2 Option Value formalization (W5)."""

import pytest

from euroleague_fantasy_manager.models import Position
from euroleague_fantasy_manager.optimization.constraints import PlayerProjectionContract
from euroleague_fantasy_manager.optimization.option_value import (
    compute_t2_bench_insurance_value,
    margrabe_exchange_option,
)


@pytest.fixture
def t1_starter() -> PlayerProjectionContract:
    return PlayerProjectionContract(
        player_id=10,
        player_name="T1 Guard",
        position=Position.GUARD,
        price_tenths=110,
        expected_fp=14.0,
        probability_play=1.0,
        expected_minutes=26.0,
        uncertainty=4.0,
        turn_number=1,
    )


@pytest.fixture
def t2_bench() -> PlayerProjectionContract:
    return PlayerProjectionContract(
        player_id=11,
        player_name="T2 Guard Backup",
        position=Position.GUARD,
        price_tenths=90,
        expected_fp=13.0,
        probability_play=1.0,
        expected_minutes=24.0,
        uncertainty=3.8,
        turn_number=2,
    )


def test_margrabe_exchange_option_mathematical_properties():
    # 1. Deep in-the-money exchange option: mu_2 = 25, mu_1 = 10 -> approx 15
    opt_itm = margrabe_exchange_option(mu_1=10.0, sigma_1=2.0, mu_2=25.0, sigma_2=2.0)
    assert opt_itm >= 15.0

    # 2. At-the-money exchange option: mu_1 = 15, mu_2 = 15 -> purely volatility-driven > 0
    opt_atm = margrabe_exchange_option(mu_1=15.0, sigma_1=4.0, mu_2=15.0, sigma_2=4.0)
    assert 2.0 <= opt_atm <= 4.0

    # 3. Out-of-the-money exchange option with zero volatility: returns 0.0
    opt_otm_zero_vol = margrabe_exchange_option(mu_1=25.0, sigma_1=0.01, mu_2=10.0, sigma_2=0.01)
    assert opt_otm_zero_vol == 0.0

    # 4. Correlation effect: positive correlation reduces dispersion of difference
    opt_uncorr = margrabe_exchange_option(mu_1=15.0, sigma_1=4.0, mu_2=15.0, sigma_2=4.0, rho=0.0)
    opt_pos_corr = margrabe_exchange_option(mu_1=15.0, sigma_1=4.0, mu_2=15.0, sigma_2=4.0, rho=0.6)
    assert opt_pos_corr < opt_uncorr


def test_compute_t2_bench_insurance_value_preround(t1_starter, t2_bench):
    # Pre-round evaluation using Margrabe exchange option
    val = compute_t2_bench_insurance_value(t2_player=t2_bench, t1_starter=t1_starter)
    # 50% multiplier applied for bench substitution
    assert 0.8 <= val <= 2.5


def test_compute_t2_bench_insurance_value_realized(t1_starter, t2_bench):
    # Case A: T1 starter flops with 3.0 points. T2 backup expected 13.0.
    # Expected gain = 0.5 * (13.0 - 3.0) = 5.0
    val_flop = compute_t2_bench_insurance_value(
        t2_player=t2_bench,
        t1_starter=t1_starter,
        realized_t1_score=3.0,
    )
    assert val_flop == 5.0

    # Case B: T1 starter scores 24.0 points. Backup is kept on bench.
    val_boom = compute_t2_bench_insurance_value(
        t2_player=t2_bench,
        t1_starter=t1_starter,
        realized_t1_score=24.0,
    )
    assert val_boom == 0.0
