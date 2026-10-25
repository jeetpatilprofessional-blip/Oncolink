"""
ONCOLINK Urgency Assignment Module
==================================

Authoritative Urgency Rules:
----------------------------
| Symptom Condition | Assigned Urgency | Review SLA | Notes |
|---|---|---|---|
| Any red-flag symptom present | Urgency.URGENT | < 4 hours | Emergency fast-track triage |
| No red-flag symptoms present | Urgency.ROUTINE | < 48 hours | Standard clinical review queue |

Clinical Prototype Disclaimer:
------------------------------
This is a prototype research heuristic and rule-based triage rule, NOT clinical
guidance. Case review urgency may be updated or adjusted subsequently by calibrated
AI inference or by an authorized reviewing medical doctor during clinical consultation.
"""

from app.models.case import Urgency


def determine_urgency(red_flags: list[str]) -> Urgency:
    """
    Assigns initial clinical triage urgency based exclusively on red-flag symptoms.

    Rule:
    - Any red flag gives Urgency.URGENT.
    - Otherwise gives Urgency.ROUTINE.
    """
    if red_flags:
        return Urgency.URGENT
    return Urgency.ROUTINE
