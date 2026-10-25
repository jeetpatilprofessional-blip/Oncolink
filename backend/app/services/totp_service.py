import hashlib
import secrets

import pyotp
from cryptography.fernet import Fernet


class TOTPService:
    """
    Manages Time-Based One-Time Password (TOTP) generation, verification,
    encryption-at-rest, and recovery codes for two-factor authentication.
    """

    def __init__(self, encryption_key: str):
        # Fernet requires a 32 url-safe base64-encoded key
        self._fernet = Fernet(encryption_key.encode("utf-8"))

    def encrypt_secret(self, secret: str) -> str:
        """Encrypts raw base32 TOTP secret for secure persistence in database."""
        return self._fernet.encrypt(secret.encode("utf-8")).decode("utf-8")

    def decrypt_secret(self, encrypted_secret: str) -> str:
        """Decrypts encrypted base32 TOTP secret."""
        return self._fernet.decrypt(encrypted_secret.encode("utf-8")).decode("utf-8")

    def generate_secret(self) -> str:
        """Generates a random base32 TOTP secret."""
        return pyotp.random_base32()

    def get_provisioning_uri(self, secret: str, email: str) -> str:
        """Returns the otpauth:// URI used by authenticator apps (Google Authenticator, etc.)."""
        totp = pyotp.TOTP(secret)
        return totp.provisioning_uri(name=email, issuer_name="OncoLink")

    def verify_code(self, encrypted_secret: str, code: str) -> bool:
        """Verifies a 6-digit TOTP code against the decrypted secret with a 1-step window."""
        if not code or not encrypted_secret:
            return False
        try:
            raw_secret = self.decrypt_secret(encrypted_secret)
            totp = pyotp.TOTP(raw_secret)
            return bool(totp.verify(code.strip(), valid_window=1))
        except Exception:
            return False

    def verify_raw_code(self, raw_secret: str, code: str) -> bool:
        """Verifies a 6-digit TOTP code against an unencrypted secret during initial setup."""
        if not code or not raw_secret:
            return False
        try:
            totp = pyotp.TOTP(raw_secret)
            return bool(totp.verify(code.strip(), valid_window=1))
        except Exception:
            return False

    def generate_recovery_codes(self, count: int = 8) -> tuple[list[str], list[str]]:
        """
        Generates N recovery codes formatted as 'XXXX-XXXX'.
        Returns a tuple: (plain_recovery_codes, hashed_recovery_codes).
        Only plain codes are shown to the user once; only hashed codes are stored in the database.
        """
        plain_codes = []
        hashed_codes = []
        for _ in range(count):
            part1 = secrets.token_hex(2).upper()
            part2 = secrets.token_hex(2).upper()
            code = f"{part1}-{part2}"
            plain_codes.append(code)
            hashed_codes.append(self.hash_recovery_code(code))
        return plain_codes, hashed_codes

    @staticmethod
    def hash_recovery_code(code: str) -> str:
        """Canonical SHA-256 hash of normalized recovery code."""
        normalized = code.strip().upper().replace(" ", "")
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def verify_and_consume_recovery_code(
        self, candidate_code: str, stored_hashes: list[str]
    ) -> tuple[bool, list[str]]:
        """
        Checks if candidate_code matches any stored recovery code hash.
        If matched, consumes it (removes it from the list) and returns (True, updated_hashes).
        Otherwise returns (False, stored_hashes).
        """
        candidate_hash = self.hash_recovery_code(candidate_code)
        if candidate_hash in stored_hashes:
            remaining = [h for h in stored_hashes if h != candidate_hash]
            return True, remaining
        return False, stored_hashes
