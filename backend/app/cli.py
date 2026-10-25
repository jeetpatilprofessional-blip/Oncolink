import asyncio
import getpass
import os
import sys
from datetime import UTC, datetime

from app.config import get_settings
from app.database import close_db, init_db
from app.models.audit import AuditEventType
from app.models.user import DoctorVerificationStatus, UserRole
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService
from app.services.consent_service import ConsentService
from app.services.patient_service import PatientService


async def seed_demo_users() -> None:
    """
    Seeds one demonstration account per role into the database.

    Safety constraints enforced:
    1. Refuses to run if ENVIRONMENT or ENV is 'production'.
    2. Refuses to run if any required demo credential environment variable is missing.
    3. Refuses to run if any password violates security policies (min length 10, not equal to email).
    4. Refuses to run if passwords are shared across accounts (each role must have a distinct password).
    5. Marks all created accounts with is_demo=True.
    """
    settings = get_settings()

    # 1. Guard against production environment
    env_str = os.getenv("ENV", settings.environment).strip().lower()
    if env_str == "production":
        print("ERROR: Demo user seeding is strictly forbidden in production environments (ENV=production).")
        sys.exit(1)

    # 2. Gather demo user specifications
    demo_specs = [
        {
            "role": UserRole.PATIENT,
            "email": settings.demo_patient_email,
            "password": settings.demo_patient_password,
            "extra": {},
        },
        {
            "role": UserRole.SCREENER,
            "email": settings.demo_screener_email,
            "password": settings.demo_screener_password,
            "extra": {},
        },
        {
            "role": UserRole.DOCTOR,
            "email": settings.demo_doctor_email,
            "password": settings.demo_doctor_password,
            "extra": {
                "registration_number": "DCI-DEMO-2026-042",
                "verification_status": DoctorVerificationStatus.VERIFIED.value,
                "verified_by": "system_seeder",
                "verified_at": datetime.now(UTC),
            },
        },
        {
            "role": UserRole.HOSPITAL_COORDINATOR,
            "email": settings.demo_hospital_coordinator_email,
            "password": settings.demo_hospital_coordinator_password,
            "extra": {},
        },
        {
            "role": UserRole.ADMIN,
            "email": settings.demo_admin_email,
            "password": settings.demo_admin_password,
            "extra": {},
        },
    ]

    # 3. Check for missing credentials
    missing = []
    passwords = []
    for spec in demo_specs:
        role_name = spec["role"].value
        if not spec["email"]:
            missing.append(f"DEMO_{role_name.upper()}_EMAIL")
        if not spec["password"]:
            missing.append(f"DEMO_{role_name.upper()}_PASSWORD")
        else:
            passwords.append(spec["password"])

    if missing:
        print(f"ERROR: Cannot seed demo users. Missing required environment variables:\n  {', '.join(missing)}")
        sys.exit(1)

    # 4. Enforce no shared passwords rule
    if len(set(passwords)) != len(passwords):
        print("ERROR: Shared passwords detected. Every demo account must have a unique, distinct password.")
        sys.exit(1)

    # 5. Initialize database connection
    client = await init_db(settings)
    db = client[settings.mongo_db_name]
    audit_service = AuditService(db)
    auth_service = AuthService(db, settings, audit_service)
    consent_service = ConsentService(db)

    print("Connected to database. Verifying and seeding demo accounts...")

    # 6. Validate password policies and insert/update accounts
    for spec in demo_specs:
        email = spec["email"].strip().lower()
        password = spec["password"]
        role = spec["role"]

        # Validate password strength rule
        try:
            auth_service.validate_password_strength(password, email)
        except ValueError as err:
            print(f"ERROR: Invalid password for {email}: {err}")
            await close_db()
            sys.exit(1)

        password_hash = auth_service.hash_password(password)
        now = datetime.now(UTC)

        user_doc = {
            "email": email,
            "password_hash": password_hash,
            "role": role.value,
            "is_active": True,
            "is_demo": True,
            "created_at": now,
            "failed_login_attempts": 0,
            "locked_until": None,
            "totp_enrolled": False,
            "totp_secret_encrypted": None,
            "totp_recovery_codes_hashes": [],
            **spec["extra"],
        }

        # Upsert by email
        result = await db["users"].update_one(
            {"email": email},
            {"$set": user_doc},
            upsert=True,
        )

        user_id = str(result.upserted_id) if result.upserted_id else None
        if not user_id:
            existing = await db["users"].find_one({"email": email})
            user_id = str(existing["_id"])

        # If patient, ensure patient profile and consent are created
        if role == UserRole.PATIENT:
            patient_service = PatientService(db)
            existing_patient = await patient_service.get_patient_by_user_id(user_id)
            patient_id = None
            if not existing_patient:
                patient_profile = await patient_service.create_patient(
                    created_by=user_id,
                    date_of_birth="1990-01-01",
                    user_id=user_id,
                    language="en",
                    contact=email,
                    is_demo=True,
                )
                patient_id = patient_profile.id
            else:
                patient_id = str(existing_patient["_id"])

            current_consent = consent_service.get_current_consent()
            existing_consent = await consent_service.get_consent_for_user(user_id)
            if not existing_consent:
                await consent_service.record_consent(
                    user_id=user_id,
                    patient_id=patient_id,
                    version=current_consent.version,
                    captured_by="self_demo",
                )

        # Audit entry
        await audit_service.insert(
            event_type=AuditEventType.USER_CREATION,
            actor_id="system_seeder",
            actor_role="system",
            target_user_id=user_id,
            details={"email": email, "role": role.value, "is_demo": True},
        )
        print(f"  [OK] Seeded {role.value} account: {email}")

    await close_db()
    print("Demo user seeding completed successfully.")


async def create_admin(email: str, password: str | None = None) -> None:
    """
    Creates a production-ready, real administrator account.
    Enforces password complexity, email uniqueness, sets is_demo=False,
    requires TOTP enrollment on first login, and writes an immutable audit record.
    """
    normalized_email = email.strip().lower()
    if not normalized_email or "@" not in normalized_email:
        print("ERROR: A valid email address is required.")
        sys.exit(1)

    # Read password from hidden prompt if not provided
    if not password:
        password = getpass.getpass(f"Enter password for admin ({normalized_email}): ")

    settings = get_settings()
    client = await init_db(settings)
    db = client[settings.mongo_db_name]
    audit_service = AuditService(db)
    auth_service = AuthService(db, settings, audit_service)

    # Validate password rules
    try:
        auth_service.validate_password_strength(password, normalized_email)
    except ValueError as err:
        print(f"ERROR: {err}")
        await close_db()
        sys.exit(1)

    # Check uniqueness
    existing = await db["users"].find_one({"email": normalized_email})
    if existing:
        print(f"ERROR: An account with email '{normalized_email}' already exists.")
        await close_db()
        sys.exit(1)

    password_hash = auth_service.hash_password(password)
    now = datetime.now(UTC)

    admin_doc = {
        "email": normalized_email,
        "password_hash": password_hash,
        "role": UserRole.ADMIN.value,
        "is_active": True,
        "is_demo": False,
        "created_at": now,
        "failed_login_attempts": 0,
        "locked_until": None,
        "totp_enrolled": False,
        "totp_secret_encrypted": None,
        "totp_recovery_codes_hashes": [],
    }

    result = await db["users"].insert_one(admin_doc)
    user_id = str(result.inserted_id)

    await audit_service.insert(
        event_type=AuditEventType.USER_CREATION,
        actor_id="cli_create_admin",
        actor_role="admin",
        target_user_id=user_id,
        details={
            "email": normalized_email,
            "role": UserRole.ADMIN.value,
            "is_demo": False,
            "method": "cli_create_admin",
        },
    )

    await close_db()
    print(f"Admin account '{normalized_email}' created successfully.")


def main() -> None:
    """CLI dispatcher."""
    if len(sys.argv) < 2:
        print("Usage: python -m app.cli [seed-demo-users | create-admin <email>]")
        sys.exit(1)

    command = sys.argv[1].lower()
    if command == "seed-demo-users":
        asyncio.run(seed_demo_users())
    elif command == "create-admin":
        if len(sys.argv) < 3:
            print("ERROR: create-admin requires an email argument.")
            print("Usage: python -m app.cli create-admin <email> [--password <password>]")
            sys.exit(1)
        email = sys.argv[2]
        password = None
        if len(sys.argv) >= 5 and sys.argv[3] == "--password":
            password = sys.argv[4]
        asyncio.run(create_admin(email, password))
    else:
        print(f"Unknown command: '{command}'. Available commands: seed-demo-users, create-admin")
        sys.exit(1)


if __name__ == "__main__":
    main()
