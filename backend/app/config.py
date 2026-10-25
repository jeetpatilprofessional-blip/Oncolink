from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=("settings_",),
    )

    project_name: str = "OncoLink"
    environment: str = "development"
    log_level: str = "INFO"

    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # MongoDB (Single-node replica set with auth)
    mongo_uri: str = (
        "mongodb://oncolink_app:oncolink_app_dev_password_change_me@mongodb:27017/oncolink"
        "?replicaSet=rs0&authSource=oncolink"
    )
    mongo_db_name: str = "oncolink"
    mongo_test_uri: str = (
        "mongodb://oncolink_app:oncolink_app_dev_password_change_me@mongodb:27017/oncolink_test"
        "?replicaSet=rs0&authSource=oncolink"
    )

    # GridFS Storage (in-database image storage behind StorageService interface)
    gridfs_bucket_name: str = "case_images"

    # Security & Tokens
    jwt_secret: str = "change_this_to_a_secure_random_hex_key_before_production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # TOTP Encryption Key at rest (Fernet key, 32 url-safe base64-encoded bytes)
    totp_encryption_key: str = "mO4YZOqlOWz_0Q2XD5Da5sfoL6n13xlA8PRLnvpI3Q8="

    # Demo User Seed Configuration
    demo_patient_email: str | None = None
    demo_patient_password: str | None = None
    demo_screener_email: str | None = None
    demo_screener_password: str | None = None
    demo_doctor_email: str | None = None
    demo_doctor_password: str | None = None
    demo_hospital_coordinator_email: str | None = None
    demo_hospital_coordinator_password: str | None = None
    demo_admin_email: str | None = None
    demo_admin_password: str | None = None

    # Model Locking
    model_version: str = "1.0.0-locked"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
