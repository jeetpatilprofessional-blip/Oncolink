import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

# Sensitive keys that must NEVER be logged
SENSITIVE_KEYS = {
    "password",
    "token",
    "access_token",
    "jwt",
    "secret",
    "authorization",
    "name",
    "patient_name",
    "phone",
    "mobile",
    "email",
    "contact",
    "address",
    "dob",
    "age",
    "history",
    "questionnaire",
    "answers",
}

# Regex to detect potential email or phone strings inside message texts
EMAIL_REGEX = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
PHONE_REGEX = re.compile(r"(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")


def sanitize_value(key: str, value: Any) -> Any:
    """Sanitize individual values if the key is sensitive."""
    if key.lower() in SENSITIVE_KEYS:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {k: sanitize_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_value(key, item) for item in value]
    if isinstance(value, str):
        # Scrub inline emails or phone numbers from messages
        clean_str = EMAIL_REGEX.sub("[EMAIL_REDACTED]", value)
        clean_str = PHONE_REGEX.sub("[PHONE_REDACTED]", clean_str)
        return clean_str
    return value


class StructuredJsonFormatter(logging.Formatter):
    """
    Structured JSON log formatter for ONCOLINK.
    Ensures zero PII (Personally Identifiable Information) or PHI is emitted.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": sanitize_value("message", record.getMessage()),
        }

        # Include custom metadata passed via `extra` dict, sanitizing sensitive keys
        for key, val in record.__dict__.items():
            if key not in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "taskName",
            }:
                log_entry[key] = sanitize_value(key, val)

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry)


def setup_logging(log_level: str = "INFO") -> None:
    """Configure root logger with StructuredJsonFormatter."""
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredJsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))


logger = logging.getLogger("oncolink")
