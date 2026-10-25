# ONCOLINK Role & Permissions Matrix

This document defines the authoritative permissions, resource ownership rules, access boundaries, and authorization gates for all ONCOLINK roles. Derived directly from `docs/SPEC.md` (sections 3, 7, 8, 12, 13, and 14).

---

## 1. Core Principles & Security Invariants

1. **Least Privilege & Role Scoping:** Every authenticated request is authorized based on the user's role loaded directly from the database on every transaction (`deps.get_current_user`).
2. **Anti-Probing Ownership Rule (404 over 403):** When a user requests a record belonging to another entity or user, the server **must return `404 Not Found`** (never `403 Forbidden`). This prevents malicious actors from probing or enumerating valid case, patient, or referral IDs.
3. **Clinical Privacy Boundary:** System Administrators **never** have access to clinical oral photographs, patient questionnaire history, or doctor diagnostic notes, and **never** sign clinical reports.
4. **Verified Human Oversight:** AI classifications are advisory triage outputs. Only a verified medical doctor with an active registration number can sign off on a case report.
5. **Two-Factor Enforcement:** Two-Factor Authentication (TOTP) is mandatory for all `doctor` and `admin` accounts before accessing privileged routes.
6. **Immutable Audit Logging:** Every access, view of a referral packet, state machine transition, and administrative action is written to the append-only audit trail (`audit_log`).

---

## 2. Role-by-Role Matrix

### 2.1. Patient (`patient`)

*Adult volunteers and self-screeners who provide informed consent, submit screening data, access reports, and track referrals.*

- **Allowed Resources & Actions:**
  - `POST /auth/register`: Self-registration with explicit consent version agreement.
  - `POST /consent`: Sign new/updated informed consent version.
  - `GET /consent/current`: View current consent version and document text.
  - `DELETE /me/data`: Exercise right to be forgotten (withdraw consent and purge data).
  - `POST /cases`: Initiate self-screening case draft.
  - `POST /cases/{id}/images`: Upload oral photographs according to the capture protocol.
  - `GET /cases`: List own past screening cases.
  - `GET /cases/{id}`: View details and status of own screening case.
  - `GET /reports/{id}`: Download signed PDF report for own case.
  - `GET /referrals/{id}`: Track referral status and hospital appointment details.
  - `GET /referrals/{id}/packet`: Download patient-facing referral summary packet.
  - `POST /consults/{id}/video-room`: Join teleconsultation session for own case.
  - `POST /feedback`, `POST /tickets`: Submit service rating or request non-clinical support.

- **Denied Resources & Actions:**
  - **DENIED:** Accessing cases, images, reports, or referrals of any other patient (`404 Not Found`).
  - **DENIED:** Viewing the clinical triage queue (`GET /queue`).
  - **DENIED:** Confirming, overriding, or triggering AI analysis (`POST /cases/{id}/analyze`, `POST /cases/{id}/review`).
  - **DENIED:** Signing cases or reports (`POST /cases/{id}/sign`).
  - **DENIED:** Initiating hospital referrals or managing specialist slots.
  - **DENIED:** Viewing or accessing any administrative endpoint (`/admin/*`).

- **Ownership Rule:**
  - `case.patient_id == current_user.id`
  - `consent.user_id == current_user.id`
  - A patient sees exclusively records tied to their own user account. Attempting to access another patient's record returns `404 Not Found`.

- **Authorization Gates:**
  - Active consent agreement required before submitting cases or uploading photos.

---

### 2.2. Screener (`screener`)

*Community health workers and field screeners who capture histories and oral photographs for multiple patients per session.*

- **Allowed Resources & Actions:**
  - `POST /cases`: Create new screening case on behalf of an eligible patient.
  - `POST /cases/{id}/history`: Submit structured history questionnaire (tobacco, alcohol, lesion characteristics, red flags).
  - `POST /cases/{id}/images`: Upload oral photos (close-up and context views) with anatomical site labels.
  - `POST /cases/{id}/submit`: Submit completed case for automated quality check and clinical triage.
  - `POST /cases/{id}/retake`: Capture and upload replacement photos for cases paused in `needs_retake`.
  - `GET /cases`: View list of cases created by this screener.
  - `GET /cases/{id}`: View screening record and status of cases created by this screener.
  - `GET /referrals`: Track follow-up status of referred individuals previously screened by this worker.

- **Denied Resources & Actions:**
  - **DENIED:** Accessing cases, patients, or photos created by other screeners (`404 Not Found`).
  - **DENIED:** Accessing the doctor clinical triage queue (`GET /queue`).
  - **DENIED:** Confirming or overriding AI classifications.
  - **DENIED:** Signing clinical reports (`POST /cases/{id}/sign`).
  - **DENIED:** Direct hospital referral initiation or slot booking (must be ordered by a doctor).
  - **DENIED:** Accessing administrative endpoints (`/admin/*`).

- **Ownership Rule:**
  - `case.created_by == current_user.id`
  - A screener sees exclusively cases they initiated. Requesting a case created by another screener returns `404 Not Found`.

- **Authorization Gates:**
  - Account provisioned by an administrator; active status required.

---

### 2.3. Doctor (`doctor`)

*Licensed medical practitioners and dentists who review the triage queue, confirm or override AI predictions, sign clinical reports, conduct teleconsults, and make hospital referrals.*

- **Allowed Resources & Actions:**
  - `GET /queue`: View triage review queue sorted by clinical urgency (`urgent` < 4h, `soon` < 24h, `routine` < 48h) with red-flag emergency cases pinned to the top.
  - `GET /cases/{id}`: Inspect case viewer (clinical photos, anatomical sites, history, AI class, calibrated confidence, Grad-CAM attention heatmap, image quality scores).
  - `POST /cases/{id}/claim`: Claim an unassigned case from the shared triage queue.
  - `POST /cases/{id}/review`: Confirm or override AI triage prediction with mandatory structured clinical rationale.
  - `POST /cases/{id}/retake`: Request screener retake with specific feedback reason (transitions case to `needs_retake`).
  - `POST /cases/{id}/second-opinion`: Request informal review/second opinion from another verified doctor.
  - `POST /cases/{id}/sign`: Digitally sign clinical report, appending verified doctor's registration number, timestamp, and intended-use statement.
  - `GET /hospitals/search`: Search hospital directory by facility tier, distance, specialty, and next available slot.
  - `POST /slots/{id}/hold`: Place a temporary 10-minute hold on a hospital biopsy/consult slot.
  - `POST /referrals`: Issue hospital referral and attach generated referral packet.
  - `POST /consults/{id}/video-room`: Initiate teleconsultation room (audio/video) with patient.
  - `PUT /doctor/availability`: Configure daily review capacity and on-duty availability.

- **Denied Resources & Actions:**
  - **DENIED:** Accessing cases assigned to other doctors that are not in the shared queue (`404 Not Found`).
  - **DENIED:** Signing reports or creating referrals if `verification_status != "verified"` (`403 Forbidden`).
  - **DENIED:** Modifying hospital master schedules, slots, or attendance outcomes (owned by Hospital Coordinator).
  - **DENIED:** User administration, doctor verification, or system analytics (`/admin/*`).

- **Ownership Rule:**
  - `case.assigned_doctor_id == current_user.id` OR `case.status == "queued"` (unassigned in shared queue) OR `case.second_opinion_doctor_id == current_user.id`.
  - Accessing a case assigned to a different doctor returns `404 Not Found`.

- **Authorization Gates:**
  - **Gate 1 (2FA):** Mandatory TOTP authentication; unenrolled doctors are routed to `/2fa/setup` and cannot access `/queue` or `/doctor`.
  - **Gate 2 (Verification):** `current_user.verification_status == "verified"`. Doctors with status `pending` or `rejected` can log in but are rejected with `403 Forbidden` on `POST /cases/{id}/sign` and `POST /referrals`.

---

### 2.4. Hospital Coordinator (`hospital_coordinator`)

*Hospital facility personnel who manage department rosters, specialist schedules, slot capacity, incoming referrals, clinic attendance, and biopsy outcomes.*

- **Allowed Resources & Actions:**
  - `GET /hospitals/{id}`: View profile and department details of coordinator's assigned hospital.
  - `PUT /hospitals/{id}`: Update department contact info and clinic hours.
  - `POST /hospitals/{id}/specialists`: Manage specialist directory for coordinator's hospital.
  - `POST /hospitals/{id}/schedules`: Configure weekly specialist schedules, blocked dates, and daily capacity.
  - `GET /hospitals/{id}/slots`: Inspect generated appointment slots.
  - `GET /referrals`: View incoming referral inbox for coordinator's hospital sorted by clinical urgency.
  - `GET /referrals/{id}`: View referral details and status.
  - `GET /referrals/{id}/packet`: View read-only clinical referral packet (photos, AI model version, history, doctor review notes). Every packet access is logged in `audit_log`.
  - `PATCH /referrals/{id}/status`: Accept referral, reschedule, or decline with mandatory clinical decline reason (enables doctor re-referral).
  - `POST /appointments/{id}/attendance`: Record patient attendance (`attended` or `no_show`).
  - `POST /appointments/{id}/outcome`: Record biopsy confirmation outcome and histopathology staging.

- **Denied Resources & Actions:**
  - **DENIED:** Viewing referrals, slots, or packets addressed to any other hospital (`404 Not Found`).
  - **DENIED:** Accessing cases or patients who have not been referred to coordinator's hospital.
  - **DENIED:** Viewing the doctor clinical review queue (`GET /queue`).
  - **DENIED:** Confirming/overriding AI classifications or signing screening reports.
  - **DENIED:** User account administration or facility credential verification.

- **Ownership Rule:**
  - `referral.hospital_id == current_user.hospital_id`
  - Accessing any referral, schedule, or case packet belonging to another hospital facility returns `404 Not Found`.

- **Authorization Gates:**
  - Account provisioned by an administrator; linked to a verified hospital ID.

---

### 2.5. Administrator (`admin`)

*System operators and compliance officers responsible for accounts, credential verification, analytics, and operational integrity.*

- **Allowed Resources & Actions:**
  - `GET /admin/users`: List all registered accounts with role, verification status, active flag, and demo badge.
  - `POST /admin/users`: Provision staff accounts (`screener`, `doctor`, `hospital_coordinator`, `admin`).
  - `POST /admin/doctors/{id}/verify`: Verify or reject doctor medical registration credentials.
  - `POST /admin/hospitals/{id}/verify`: Verify partner hospital facility credentials.
  - `POST /admin/users/{id}/deactivate`: Deactivate accounts (takes effect immediately on next request).
  - `GET /admin/analytics`: View aggregate screening counts, SLA turnaround times, and model override metrics.
  - `GET /admin/audit-logs`: Inspect immutable system audit trail.
  - `POST /admin/reset-demo`: Reset demonstration test data (disabled in production).

- **Denied Resources & Actions:**
  - **STRICT PROHIBITION — CLINICAL PRIVACY BLIND:**
    - Administrator **NEVER** views patient clinical oral photographs (`/cases/{id}/images`).
    - Administrator **NEVER** views patient history questionnaire answers.
    - Administrator **NEVER** overrides AI classifications or signs clinical reports.
    - Administrator **NEVER** issues medical referrals or alters biopsy outcomes.
    - Any attempt by an admin to access clinical inspection endpoints returns **`403 Forbidden`**.
  - **Self-Deactivation Guard:** Administrator cannot deactivate their own account (`errors.cannot_deactivate_self`).

- **Ownership Rule:**
  - Global administrative scope over system infrastructure, accounts, and audit events.
  - Zero access to patient health information (PHI) or diagnostic images.

- **Authorization Gates:**
  - **Gate 1 (2FA):** Mandatory TOTP authentication; unenrolled admins are restricted to `/2fa/setup`.

---

## 3. Permissions Matrix Summary

| Resource / Endpoint | Patient | Screener | Doctor | Coordinator | Admin |
|---|:---:|:---:|:---:|:---:|:---:|
| `POST /auth/register` (Patient self-registration) | Allowed | Denied | Denied | Denied | Denied |
| `POST /admin/users` (Provision staff users) | Denied | Denied | Denied | Denied | Allowed |
| `POST /admin/doctors/{id}/verify` (Doctor verification) | Denied | Denied | Denied | Denied | Allowed |
| `POST /cases` (Create screening case) | Own only | Own only | Denied | Denied | Denied |
| `POST /cases/{id}/images` (Upload clinical photos) | Own only | Own only | Denied | Denied | Denied |
| `GET /queue` (Clinical review queue) | Denied | Denied | Allowed | Denied | Denied |
| `GET /cases/{id}` (Clinical viewer) | Own only | Own only | Assigned/Queue | Denied | **Denied (403)** |
| `POST /cases/{id}/review` (Confirm/override AI) | Denied | Denied | Assigned only | Denied | Denied |
| `POST /cases/{id}/sign` (Sign clinical report) | Denied | Denied | Verified only | Denied | Denied |
| `GET /reports/{id}` (Download signed PDF) | Own only | Denied | Assigned only | Denied | Denied |
| `POST /referrals` (Refer to hospital) | Denied | Denied | Verified only | Denied | Denied |
| `GET /referrals` (Hospital inbox) | Denied | Follow-up | Denied | Hospital only | Denied |
| `GET /referrals/{id}/packet` (Referral packet) | Own only | Denied | Assigned only | Hospital only | **Denied (403)** |
| `PATCH /referrals/{id}/status` (Accept/decline) | Denied | Denied | Denied | Hospital only | Denied |
| `POST /appointments/{id}/outcome` (Biopsy outcome)| Denied | Denied | Denied | Hospital only | Denied |
| `GET /admin/audit-logs` (Audit compliance log) | Denied | Denied | Denied | Denied | Allowed |
| `GET /admin/analytics` (Aggregated statistics) | Denied | Denied | Denied | Denied | Allowed |

---

## 4. Final Architecture & Permissions Decisions

The following architectural and workflow decisions are finalized for the ONCOLINK platform:

1. **Doctor Case Release & Reassignment:**
   - **Decision:** Yes, an assigned doctor may voluntarily release a claimed case back to the `queued` state. A mandatory reason must be provided, which is recorded in the immutable audit log (`audit_log`).
   - **SLA Invariant:** Automatic SLA re-assignment timers (SPEC section 7: 4-hour urgent timeout) remain active concurrently.

2. **Screener Visibility & Community Camps:**
   - **Decision:** No shared visibility within screening camps. Each screener sees only cases they individually created (`case.created_by == current_user.id`).
   - **Roadmap:** Camp-level shared queues are recorded as future work.

3. **Minors and Guardianship:**
   - **Decision:** Out of scope for this prototype. Self-registration is restricted to adults aged 18 and older; registration for users under 18 is blocked and documented as a platform limitation.

4. **Hospital Coordinator Facility Boundary:**
   - **Decision:** Strictly single-facility. One hospital coordinator belongs to exactly one hospital (`user.hospital_id`). Multi-hospital assignment is prohibited.

5. **Case History and Audit Trail Visibility:**
   - **Decision:** Role-segregated visibility. Reviewing doctors see their case's clinical status timeline (`GET /cases/{id}/timeline`). Only administrators see the raw audit log (`GET /admin/audit-logs`), and administrators never see clinical oral photographs or diagnostic content.
