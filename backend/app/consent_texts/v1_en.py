"""
ONCOLINK Research & Education Prototype - Informed Consent (Version 1, English)

IMPORTANT NOTICE FOR THE PRINCIPAL INVESTIGATOR / CLINICAL LEAD:
You must review and verify this text prior to clinical pilot screening or public participant enrolment.
"""

import hashlib

CONSENT_VERSION = "v1"
CONSENT_LANGUAGE = "en"

CONSENT_TEXT = """ONCOLINK RESEARCH & EDUCATION PROTOTYPE: INFORMED CONSENT (v1)

1. Purpose and Intended Use
ONCOLINK is an experimental research and educational software prototype developed for academic study into oral lesion screening workflows and artificial intelligence assistance. ONCOLINK is NOT a medical device, does NOT diagnose cancer or any other condition, and MUST NOT be used for independent clinical decision-making. Definitive diagnosis of oral lesions requires a formal physical examination and a tissue biopsy performed by a qualified healthcare professional.

2. Voluntary Participation
Your participation in this screening project is entirely voluntary. This research prototype is intended only for use with consenting adult volunteers and openly available research datasets. You may choose not to participate, or you may withdraw your consent and request deletion of your information at any time without penalty or loss of healthcare benefits.

3. What Information We Store
If you consent and register as a patient or participant, ONCOLINK stores:
- Your account information (email address and securely hashed login credentials).
- Basic demographic information and risk history (such as age range and self-reported tobacco or alcohol exposure).
- Clinical oral cavity photographs captured during screening sessions.
- System-generated image triage annotations and clinician consultation notes.

4. Who Has Access to Your Data
Your screening information is protected by strict access controls and is accessible solely by:
- Trained healthcare screeners and coordinators assigned to your screening session.
- Verified medical and dental professionals reviewing your case.
- Designated referral hospital coordinators managing appointment slots.
- Technical research administrators responsible for system maintenance and security audit oversight.
Your personal health data is never sold, never made publicly accessible, and never transmitted over unencrypted communication channels.

5. Data Retention, Withdrawal, and Deletion
You have the right to withdraw your consent at any time. Upon withdrawal, you can request full erasure of your account and associated screening photographs through the application settings or by contacting the study coordinator. Upon receiving a verified deletion request, all personal identifiers, consultation logs, and stored photographs will be permanently deleted from the active research database and image storage.

By accepting this agreement, you confirm that you are at least 18 years of age, have read and understood this disclosure, and freely consent to participate in this screening research prototype.
"""


def get_consent_text_hash() -> str:
    """Calculates the canonical SHA-256 hash of the consent text."""
    return hashlib.sha256(CONSENT_TEXT.strip().encode("utf-8")).hexdigest()
