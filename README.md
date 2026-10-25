# ONCOLINK

*College portfolio research prototype. Version 2, consolidated after comparison with real-world oral cancer screening programs. Not a medical device.*

> **Intended Use Statement:** ONCOLINK is a research and education prototype. It is not a medical device, does not diagnose cancer, and must not be used for clinical decisions. Only a biopsy can confirm oral cancer. All data comes from public datasets and consenting volunteers.

---

## Prerequisites

- **Windows 10/11** with PowerShell
- **Docker Desktop** (WSL2 engine enabled and running)
- **Node.js LTS** (v22 or newer) and `npm`
- **Python 3.11** or newer
- **Git**

---

## First-Time Setup

1. Open PowerShell and navigate to the project directory:
   ```powershell
   Set-Location "C:\OncoLink"
   ```

2. Run the automated setup script:
   ```powershell
   .\scripts\setup.ps1
   ```
   This will:
   - Verify all prerequisites.
   - Generate `.env` from `.env.example` if not already present.
   - Install frontend packages.
   - Build and launch the containerized stack (MongoDB Replica Set with auth & GridFS, FastAPI Backend, Vite Frontend).
   - Wait for `/health` to report `healthy`.

---

## Security & Environment Configuration

All cryptographic secrets, database credentials, and session keys are loaded exclusively from environment variables in `.env` (never committed).

### Generating Cryptographic Secrets

Generate strong random secrets before deployment using the following commands:

- **JWT Secret Key (`JWT_SECRET`):**
  ```powershell
  python -c "import secrets; print(secrets.token_hex(32))"
  ```
- **TOTP Encryption Key (`TOTP_ENCRYPTION_KEY`):**
  ```powershell
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```

### Authentication & Role Architecture

- **Five Roles:** `patient`, `screener`, `doctor`, `hospital_coordinator`, `admin`.
- **Registration:** Patients self-register with explicit acceptance of the current active informed consent version (`POST /auth/register`). Staff roles (`screener`, `doctor`, `hospital_coordinator`, `admin`) are provisioned exclusively by administrators (`POST /admin/users`).
- **Passwords:** Hashed with Argon2id. Minimum length of 10 characters, strictly prohibited from matching the email address.
- **In-Memory Access Tokens:** The frontend holds access JWTs exclusively in JavaScript memory (`frontend/src/api/client.ts`), never persisting them to `localStorage`, `sessionStorage`, or readable cookies.
- **Sessions & Rotation:** Short-lived 15-minute access JWTs. Opaque refresh tokens stored only as SHA-256 hashes, rotated on every refresh, delivered via `httpOnly`, `SameSite=Strict` cookies.
- **Single-Flight Refresh Mutex:** When a 401 response occurs, concurrent frontend requests wait for a single in-flight refresh request (`POST /auth/refresh`) and retry once with the new access token.
- **Reuse Detection:** Replaying an already rotated refresh token triggers automatic revocation of the entire token family and logs a `refresh_reuse` security audit event.
- **Account Lockout:** 5 consecutive failed login attempts trigger an automatic 15-minute lockout against the target account. Unknown emails and invalid passwords return an identical generic error.
- **Two-Factor Authentication (TOTP):** Mandatory for `doctor` and `admin` roles. TOTP secrets are encrypted at rest with Fernet. Enrolment issues 8 single-use recovery codes stored as SHA-256 hashes. QR codes are generated client-side via `qrcode` SVG without external API calls.
- **Doctor Verification Guard:** Clinical sign-off endpoints enforce `require_verified_doctor`, rejecting doctors whose status is `pending` or `rejected`.
- **Immutable Audit Trail:** All auth lifecycle events (`login_success`, `login_failure`, `lockout`, `logout`, `refresh_reuse`, `totp_enrollment`, `user_creation`, `verification_changes`, `deactivation`) append to the `audit_log` collection via `AuditService` (which purposefully exposes zero update or delete methods).

---

## Administrator Account Provisioning

To create a real (non-demo) production administrator account, run the command **without `-T`** to allow interactive terminal input for the hidden password prompt:
```powershell
docker compose exec backend python -m app.cli create-admin admin@hospital.org
```
*(The command allocates an interactive TTY, prompts for a hidden password, enforces password complexity rules, rejects duplicate emails, marks the account as non-demo `is_demo: false`, mandates TOTP setup on first sign-in, and writes an immutable audit record. Never include `-T` as it disables the interactive password prompt).*

---

## Accessing the Application

> [!IMPORTANT]
> The web application **must** be opened at **`http://127.0.0.1:5173`** (never `localhost:5173`).
> `127.0.0.1` and `localhost` are treated as separate origins by browsers; accessing via `localhost` breaks the `SameSite=Strict` refresh token cookie and triggers CORS rejection from the backend.

---

## Demonstration User Seeding

To seed one demonstration account for each role:
```powershell
docker compose exec backend python -m app.cli seed-demo-users
```

**Seeder Safety Rules:**
1. Refuses to run if `ENVIRONMENT=production` or `ENV=production`.
2. Refuses to run if any required demo credential is missing from `.env`.
3. Refuses to run if any password violates password strength rules ($\ge 10$ characters, not equal to email).
4. Refuses to run if passwords are shared across accounts (each role must have a distinct password).
5. All seeded accounts are flagged with `is_demo: true`.

---

## Running the Application

### Start the Full Stack (Docker)
All published ports are strictly bound to `127.0.0.1` for local isolation.
```powershell
docker compose up -d
```

### Access Points
- **Frontend App:** http://127.0.0.1:5173
  - `/login`: 2-step clinical authentication (password then TOTP or recovery code)
  - `/register`: Patient self-registration with versioned research consent agreement
  - `/2fa/setup`: Authenticator app enrollment with local SVG QR code, secret key, and 8 recovery codes
  - `/admin`: User directory, staff provisioning, doctor credential verification, and account deactivation
  - `/patient`: Patient screening records portal
  - `/screener`: Community health worker screening queue
  - `/doctor`: Clinical review workspace
  - `/coordinator`: Hospital referral management
  - `/forbidden`: Role access boundary warning
  - `/dev/components`: Living Design System Component Gallery
- **Minimal Health Check (Public):** http://127.0.0.1:8000/health
- **Diagnostic Details (Admin Only):** http://127.0.0.1:8000/health/details
- **Current Informed Consent (Public):** http://127.0.0.1:8000/consent/current
- **FastAPI OpenAPI Docs:** http://127.0.0.1:8000/docs
- **Image Storage:** Internal MongoDB GridFS (served only via authenticated backend endpoints)

### Stop the Stack
```powershell
docker compose down
```

### Reset Local Volumes & Databases
To wipe local development MongoDB replica set data, keyfiles, and GridFS images:
```powershell
.\scripts\reset-docker.ps1
```

---

## Testing & Quality Assurance

All commands can be executed using `npm` from PowerShell:

### Run All Tests
```powershell
npm run test
```

### Run Backend Tests Only
```powershell
npm run test:backend
```
*(Executes 33 test cases in pytest covering role cross-matrix enforcement, `GET /auth/me`, CORS headers, unauthenticated rejection, argon2 hashing, refresh rotation & reuse detection, account lockout, TOTP enrollment/login, recovery codes, consent verification, and AuditService immutability).*

### Run Frontend Tests Only
```powershell
npm run test:frontend
```
*(Executes 34 vitest test cases covering login 2-step flow, patient consent requirement, in-memory token security, single-flight refresh under parallel 401s, 2FA setup recovery codes confirmation, role route redirects, and axe-core zero-violation audits across all screens).*

---

## Linting & Type Checking

### Run All Linters
```powershell
npm run lint
```

### Backend Linting (Ruff)
```powershell
npm run lint:backend
```

### Frontend Linting & Typecheck (ESLint & TypeScript)
```powershell
npm run lint:frontend
```
