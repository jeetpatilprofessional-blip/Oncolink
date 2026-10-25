import itertools

import pytest

from app.models.case import Urgency
from app.models.history import CaseHistoryPayload, Frequency
from app.services.red_flag import (
    RED_FLAG_DIFFICULTY_BREATHING,
    RED_FLAG_HEAVY_BLEEDING,
    RED_FLAG_RAPID_SWELLING,
    RISK_AGE_30_TO_65,
    RISK_TOBACCO_OR_ARECA_USER,
    evaluate_red_flags,
    evaluate_risk_factors,
)
from app.services.urgency import determine_urgency


def make_dummy_history(
    heavy_bleeding: bool = False,
    difficulty_breathing: bool = False,
    rapid_swelling: bool = False,
    tobacco_smoked_frequency: Frequency = Frequency.NEVER,
    tobacco_smoked_years: int = 0,
    tobacco_smokeless_frequency: Frequency = Frequency.NEVER,
    tobacco_smokeless_years: int = 0,
    areca_nut_frequency: Frequency = Frequency.NEVER,
    areca_nut_years: int = 0,
    betel_quid_frequency: Frequency = Frequency.NEVER,
    betel_quid_years: int = 0,
) -> CaseHistoryPayload:
    return CaseHistoryPayload(
        tobacco_smoked_frequency=tobacco_smoked_frequency,
        tobacco_smoked_years=tobacco_smoked_years,
        tobacco_smokeless_frequency=tobacco_smokeless_frequency,
        tobacco_smokeless_years=tobacco_smokeless_years,
        areca_nut_frequency=areca_nut_frequency,
        areca_nut_years=areca_nut_years,
        betel_quid_frequency=betel_quid_frequency,
        betel_quid_years=betel_quid_years,
        alcohol_frequency=Frequency.NEVER,
        lesion_duration_weeks=2,
        lesion_pain=False,
        lesion_non_healing_two_weeks=False,
        lesion_bleeding=False,
        lesion_white_or_red_patch=False,
        lesion_lump=False,
        difficulty_swallowing=False,
        difficulty_opening_mouth=False,
        difficulty_speaking=False,
        unexplained_weight_loss=False,
        family_history_cancer=False,
        heavy_bleeding=heavy_bleeding,
        difficulty_breathing=difficulty_breathing,
        rapid_swelling=rapid_swelling,
    )


# --- 1. Red-Flag Engine Truth Table Unit Tests (All 2^3 = 8 Combinations) ---

TRUTH_TABLE_COMBINATIONS = list(itertools.product([False, True], repeat=3))


@pytest.mark.parametrize("hb, db, rs", TRUTH_TABLE_COMBINATIONS)
def test_red_flag_engine_truth_table(hb: bool, db: bool, rs: bool):
    """
    Exhaustive truth-table unit test verifying all 8 boolean permutations of:
    - heavy_bleeding (hb)
    - difficulty_breathing (db)
    - rapid_swelling (rs)
    """
    history = make_dummy_history(heavy_bleeding=hb, difficulty_breathing=db, rapid_swelling=rs)
    flags = evaluate_red_flags(history)

    expected: list[str] = []
    if hb:
        expected.append(RED_FLAG_HEAVY_BLEEDING)
    if db:
        expected.append(RED_FLAG_DIFFICULTY_BREATHING)
    if rs:
        expected.append(RED_FLAG_RAPID_SWELLING)

    assert flags == expected
    assert len(flags) == sum([hb, db, rs])


# --- 2. Urgency Rule Tests ---


@pytest.mark.parametrize("hb, db, rs", TRUTH_TABLE_COMBINATIONS)
def test_urgency_rules_exhaustive_truth_table(hb: bool, db: bool, rs: bool):
    """
    Verifies the authoritative urgency rule:
    - Any red flag detected gives Urgency.URGENT (< 4 hours SLA).
    - Otherwise gives Urgency.ROUTINE (< 48 hours SLA).
    """
    history = make_dummy_history(heavy_bleeding=hb, difficulty_breathing=db, rapid_swelling=rs)
    red_flags = evaluate_red_flags(history)
    urgency = determine_urgency(red_flags)

    if hb or db or rs:
        assert urgency == Urgency.URGENT
    else:
        assert urgency == Urgency.ROUTINE


# --- 3. Informational Risk-Factor Flag Tests (SPEC 5.1) ---


def test_risk_factors_age_band_and_tobacco():
    """
    SPEC 5.1 flags:
    - Age band 30 to 65
    - Tobacco or areca nut usage
    Verifies that informational risk flags do not alter case urgency.
    """
    # Baseline: no tobacco, age 25 -> zero risk factors, routine urgency
    h_baseline = make_dummy_history()
    rf_baseline = evaluate_risk_factors(h_baseline, age=25)
    assert rf_baseline == []
    assert determine_urgency(evaluate_red_flags(h_baseline)) == Urgency.ROUTINE

    # Age 45 (between 30 and 65) -> risk_age_30_to_65, still routine urgency
    rf_age = evaluate_risk_factors(h_baseline, age=45)
    assert rf_age == [RISK_AGE_30_TO_65]
    assert determine_urgency(evaluate_red_flags(h_baseline)) == Urgency.ROUTINE

    # Smoked tobacco daily -> risk_tobacco_or_areca_user, still routine urgency
    h_tobacco = make_dummy_history(tobacco_smoked_frequency=Frequency.DAILY, tobacco_smoked_years=5)
    rf_tobacco = evaluate_risk_factors(h_tobacco, age=25)
    assert rf_tobacco == [RISK_TOBACCO_OR_ARECA_USER]
    assert determine_urgency(evaluate_red_flags(h_tobacco)) == Urgency.ROUTINE

    # Areca nut user + Age 50 -> both flags, still routine urgency
    h_areca = make_dummy_history(areca_nut_frequency=Frequency.OCCASIONAL)
    rf_both = evaluate_risk_factors(h_areca, age=50)
    assert set(rf_both) == {RISK_AGE_30_TO_65, RISK_TOBACCO_OR_ARECA_USER}
    assert determine_urgency(evaluate_red_flags(h_areca)) == Urgency.ROUTINE

    # Betel quid user -> risk_tobacco_or_areca_user
    h_quid = make_dummy_history(betel_quid_frequency=Frequency.DAILY, betel_quid_years=10)
    rf_quid = evaluate_risk_factors(h_quid, age=20)
    assert rf_quid == [RISK_TOBACCO_OR_ARECA_USER]

    # Smokeless tobacco user -> risk_tobacco_or_areca_user
    h_smokeless = make_dummy_history(
        tobacco_smokeless_frequency=Frequency.DAILY, tobacco_smokeless_years=2
    )
    rf_smokeless = evaluate_risk_factors(h_smokeless, age=70)
    assert rf_smokeless == [RISK_TOBACCO_OR_ARECA_USER]
