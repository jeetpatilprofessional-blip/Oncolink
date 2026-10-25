from typing import Any

from app.models.history import CaseHistoryPayload, Frequency

# Red-flag codes
RED_FLAG_HEAVY_BLEEDING = "heavy_bleeding"
RED_FLAG_DIFFICULTY_BREATHING = "difficulty_breathing"
RED_FLAG_RAPID_SWELLING = "rapid_swelling"

# Informational risk-factor codes (SPEC 5.1 - Do NOT affect clinical review urgency)
RISK_AGE_30_TO_65 = "risk_age_30_to_65"
RISK_TOBACCO_OR_ARECA_USER = "risk_tobacco_or_areca_user"


def evaluate_red_flags(history: CaseHistoryPayload | dict[str, Any]) -> list[str]:
    """
    Pure rule-based function evaluating the presence of red-flag emergency symptoms.
    Never relies on or waits for AI inference.

    Trigger fields per SPEC 5.2 & 5.5:
    - heavy_bleeding: True -> 'heavy_bleeding'
    - difficulty_breathing: True -> 'difficulty_breathing'
    - rapid_swelling: True -> 'rapid_swelling'
    """
    data = history.model_dump() if isinstance(history, CaseHistoryPayload) else history
    red_flags: list[str] = []

    if data.get("heavy_bleeding"):
        red_flags.append(RED_FLAG_HEAVY_BLEEDING)
    if data.get("difficulty_breathing"):
        red_flags.append(RED_FLAG_DIFFICULTY_BREATHING)
    if data.get("rapid_swelling"):
        red_flags.append(RED_FLAG_RAPID_SWELLING)

    return red_flags


def evaluate_risk_factors(
    history: CaseHistoryPayload | dict[str, Any],
    age: int | None = None,
) -> list[str]:
    """
    Evaluates informational risk factors per SPEC 5.1:
    - Age band 30 to 65
    - Tobacco or areca nut usage (smoked, smokeless, areca nut, betel quid)

    These are strictly informational flags that do NOT alter case review urgency.
    """
    data = history.model_dump() if isinstance(history, CaseHistoryPayload) else history
    risk_factors: list[str] = []

    # 1. Age band flag (30 to 65)
    if age is not None and 30 <= age <= 65:
        risk_factors.append(RISK_AGE_30_TO_65)

    # 2. Tobacco or areca nut exposure
    tobacco_or_areca_active = (
        data.get("tobacco_smoked_frequency") not in (Frequency.NEVER, Frequency.NEVER.value, None)
        or (data.get("tobacco_smoked_years") or 0) > 0
        or data.get("tobacco_smokeless_frequency")
        not in (Frequency.NEVER, Frequency.NEVER.value, None)
        or (data.get("tobacco_smokeless_years") or 0) > 0
        or data.get("areca_nut_frequency") not in (Frequency.NEVER, Frequency.NEVER.value, None)
        or (data.get("areca_nut_years") or 0) > 0
        or data.get("betel_quid_frequency") not in (Frequency.NEVER, Frequency.NEVER.value, None)
        or (data.get("betel_quid_years") or 0) > 0
    )
    if tobacco_or_areca_active:
        risk_factors.append(RISK_TOBACCO_OR_ARECA_USER)

    return risk_factors
