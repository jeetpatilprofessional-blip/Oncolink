# ONCOLINK

*College portfolio research prototype. Version 2, consolidated after comparison with real-world oral cancer screening programs. Not a medical device.*

> **Intended Use Statement:** ONCOLINK is a research and education prototype. It is not a medical device, does not diagnose cancer, and must not be used for clinical decisions. Only a biopsy can confirm oral cancer. All data comes from public datasets and consenting volunteers.

---

## Limitations & Clinical Caveats

1. **Quality Gate Measures Photographic Properties Only:** The automated quality gate evaluates sharpness, brightness, shadow/highlight fractions, and minimum pixel dimensions only. It **cannot confirm that a mouth or lesion is present** (for example, a high-contrast synthetic checkerboard test image passes all checks).
2. **Untuned Heuristic Thresholds:** Quality gate thresholds are prototype heuristics and have not yet been clinically tuned or calibrated against diverse real-world mobile camera sensors and field lighting conditions.
3. **English-Only Informed Consent:** The informed consent text is currently provided in English only. It must be professionally translated into regional languages and formally reviewed by an institutional ethics committee (IRB/IEC) before any field screening use.
4. **Dataset Splitting Limitations:** Public oral photography datasets lack patient identifiers. While exact and near-duplicates are grouped into single splits via perceptual hashing, performance metrics may still be optimistic if multiple photos of a single patient exist under different angles.

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

### Case Foundation & State Machine Architecture

- **Collections:**
  - `patients`: Decouples participant profiles from login credentials (`user_id` nullable, `created_by`, `date_of_birth`, `language`, `contact`, `erased`, `is_demo`). Unique sparse index on `user_id` with `partialFilterExpression={"user_id": {"$type": "string"}}` prevents duplicate user accounts while supporting unlimited screener community camp profiles.
  - `cases`: Screening entities (`patient_id`, `created_by`, `status`, `urgency`, `assigned_doctor_id`, `second_opinion_doctor_id`, `reference`, `status_history`, `version`, `timestamps`, `is_demo`).
- **Adult-Only Policy:** `POST /auth/register` and `POST /patients` validate date of birth (`AdultDateOfBirth`), strictly rejecting any individual under 18 years of age ($age \ge 18$).
- **Case Reference Codes:** Random, non-sequential 8-character codes grouped 4-4 (e.g. `K9W2-P7M4`) with collision retry and unique indexing.
- **Authoritative State Machine:** Status changes execute exclusively via `app.services.state_machine.transition()` within a single atomic MongoDB multi-document transaction with optimistic concurrency control (`version` counter; concurrent stale writes return `409 Conflict`).
- **Claim & Release Lifecycle:** Claiming is permitted strictly from `ai_analyzed` when unassigned (`assigned_doctor_id == null`). Voluntary doctor release transitions `under_review -> ai_analyzed` (unassigning the doctor while retaining the AI inference output). The AI triage step (`queued -> ai_analyzed`) is guaranteed to always reach `ai_analyzed`, recording `ai_status: "completed" | "unavailable"`.
- **Zero-Edge Admin Invariant:** The administrative role has exactly zero allowed edges in the state machine transition table. Patient data erasure via right-to-be-forgotten is executed under actor role `system` or `patient`, never `admin`.
- **Privacy Partitioning:** Status transitions append clinical notes (`reason_text`) strictly to `case.status_history`, while writing structural IDs and authoritative `reason_code` values ONLY to `audit_log`. Free-text clinical notes never leak into administrative audit logs.
- **Endpoints:**
  - `POST /patients`: Screener creates unauthenticated camp screening profile ($age \ge 18$).
  - `POST /cases`: Patient drafts self-screening case or screener drafts case for a screener-created patient.
  - `GET /cases`: Role-scoped list (patient sees own cases; screener sees own created cases; others receive 403).
  - `GET /cases/{id}`: Role-scoped viewer (patient/screener receive status view; verified doctor on pool case in `ai_analyzed` receives metadata-only view; assigned/2nd-opinion doctor receives full clinical view; admin/coordinator receive 403; wrong ownership returns 404). Includes role-scoped `images` metadata array.
  - `POST /cases/{id}/cancel`: Cancel case prior to signing (`draft`, `submitted`, `quality_check`, `needs_retake`, `queued`, `ai_analyzed`, `under_review`, `uncertain_needs_inperson`); post-signing states return `409 Conflict`.
  - `GET /cases/{id}/timeline`: Status timeline for assigned or second-opinion doctor (others 403 or 404).
  - `POST /consent`: Extended to record informed consent with `patient_id` (self-signed or screener in-person).
  - `POST /cases/{id}/history`: Submit structured oral health and risk history questionnaire (strictly validated enums, booleans, small integers; zero free text; `extra="forbid"`).
  - `POST /cases/{id}/images`: Upload oral photographs (multipart; verified by magic bytes JPEG/PNG/WebP, 10 MB cap, Pillow decompression bomb protection, EXIF/GPS stripped via re-encoding, GridFS storage, 12-image cap, automatic superseding).
  - `GET /cases/{id}/images/{image_id}`: Stream authenticated clinical photograph binary (`Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, immutable audit log entry with IDs only).
  - `POST /cases/{id}/submit`: Authoritative submission pipeline gated by 422 preconditions (active consent, saved history, photographic protocol coverage: >=1 closeup and >=2 context views). Executes atomic chained transitions (`submitted -> quality_check -> [red_flag | needs_retake | queued]`) in ONE single transaction with one audit entry per transition edge.

### Screening Triage & Quality Architecture

#### Urgency Rule Table
| Symptom Condition | Assigned Urgency | Review SLA Target | Description |
|---|---|---|---|
| Any red-flag symptom present | `urgent` | < 4 hours | Emergency fast-track triage; placed at top of clinical queue |
| No red-flag symptoms present | `routine` | < 48 hours | Standard clinical review queue |

*Note: This is a prototype research heuristic and rule-based triage rule, NOT clinical guidance. Case review urgency may be updated subsequently by calibrated AI inference or by an authorized reviewing clinician.*

#### Image Quality Gate Threshold Table
| Metric Name | Constant Identifier | Threshold Value | Reason Code | Description / Clinical Rationale |
|---|---|---|---|---|
| Minimum Width | `MIN_WIDTH` | 480 px | `too_small` | Minimum horizontal resolution for clear mucosal inspection |
| Minimum Height | `MIN_HEIGHT` | 480 px | `too_small` | Minimum vertical resolution for clinical examination |
| Laplacian Variance | `BLUR_LAPLACIAN_VAR_MIN` | 100.0 | `too_blurry` | Variance of Laplacian on 512x512 grayscale copy; rejects out-of-focus captures |
| Minimum Brightness | `BRIGHTNESS_MEAN_MIN` | 40.0 | `too_dark` | Lower limit on average pixel luminance (0–255 scale) |
| Max Crushed Shadows | `SHADOW_FRACTION_MAX` | 0.45 | `too_dark` | Max fraction of pixels with luminance <= 20 (underexposure) |
| Maximum Brightness | `BRIGHTNESS_MEAN_MAX` | 215.0 | `too_bright` | Upper limit on average pixel luminance (overexposure) |
| Max Blown Highlights | `HIGHLIGHT_FRACTION_MAX` | 0.40 | `too_bright` | Max fraction of pixels with luminance >= 240 (flash glare / specular saturation) |
| Minimum Detail / StdDev | `DETAIL_STD_DEV_MIN` | 12.0 | `low_detail` | Minimum standard deviation of grayscale intensities; rejects blank / uniform surfaces |

*Note: All thresholds are initial heuristics that must be tuned on real phone photos collected during field screening camps.*

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
*(Executes 213 test cases in pytest covering role cross-matrix enforcement across granular endpoint-persona cells, database-backed execution of all allowed state machine edges, red-flag truth tables, urgency heuristics, image magic bytes verification, EXIF stripping, GridFS image replacement, quality gate heuristics, and audit privacy partitioning).*

### Run Frontend Tests Only
```powershell
npm run test:frontend
```
*(Executes 52 vitest test cases covering OralSiteMap state rendering and keyboard navigation, red-flag emergency banner triggers, submit preconditions checklist matching 422 errors, screener under-18 intake rejection without API calls, file input capture fallback, login/2FA authentication flows, and axe-core zero-violation audits across all application screens).*

### End-to-End Smoke Test
Run the automated screening intake and submission flow against the live backend stack:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\smoke-screening.ps1
```
*(Logs in as demo screener, registers a new participant profile, records in-person informed consent, creates a draft case, saves structured questionnaire history, generates synthetic checkered JPEG test images, uploads 1 lesion closeup and 2 context views, verifies authoritative quality evaluation, executes atomic submission, and purges all test records from MongoDB upon completion).*

### Visual Regression & Screen Capture
Capture all application screens at 360px and 1280px viewports with real authenticated sessions:
```powershell
node .\scripts\capture_screening_screenshots.js
```
All screenshots are output directly to `docs/screenshots/`.

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
