import re
from typing import Annotated

from email_validator import EmailNotValidError, validate_email
from pydantic import AfterValidator

from app.config import get_settings


def validate_oncolink_email(v: str) -> str:
    """
    Validates and normalizes email addresses across all ONCOLINK models.

    Security & Compliance Rules:
    1. RFC compliance: Uses standard email-validator library.
    2. Demo domain relaxation: Allows '.local' domains (e.g. demo.*@oncolink.local)
       ONLY when environment is development or test AND allow_demo_local_emails is True.
    3. Production guard: In production, '.local' addresses are strictly rejected as
       special-use/reserved domain names.
    4. Never globally mutates email_validator.SPECIAL_USE_DOMAIN_NAMES.
    """
    if not isinstance(v, str):
        raise ValueError("Email address must be a string")
    v = v.strip()
    if not v:
        raise ValueError("Email address cannot be empty")

    settings = get_settings()
    env = (settings.environment or "").lower()
    is_dev_or_test = env in ("development", "dev", "test", "testing")
    allow_demo = getattr(settings, "allow_demo_local_emails", True)

    # Scoped relaxation: only in dev/test with allow_demo enabled
    if is_dev_or_test and allow_demo:
        local_part, sep, domain = v.rpartition("@")
        if sep and (domain.lower() == "local" or domain.lower().endswith(".local")):
            try:
                res = validate_email(f"{local_part}@example.org", check_deliverability=False)
            except EmailNotValidError as e:
                raise ValueError(str(e)) from e

            labels = domain.split(".")
            if not all(
                label and re.match(r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$", label)
                for label in labels
            ):
                raise ValueError("Invalid domain name in email address")

            return f"{res.local_part}@{domain.lower()}"

    # Strict production validation: reserved domains like .local are rejected
    try:
        validated = validate_email(v, check_deliverability=False)
        return validated.normalized
    except EmailNotValidError as e:
        raise ValueError(str(e)) from e


OncoLinkEmail = Annotated[str, AfterValidator(validate_oncolink_email)]
