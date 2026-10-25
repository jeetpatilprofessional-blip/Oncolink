# ONCOLINK Role & Permissions Matrix

This document defines the authoritative permissions, resource ownership rules, access boundaries, and authorization gates for all ONCOLINK roles. Derived directly from `docs/SPEC.md` (sections 3, 5, 7, 8, 12, 13, and 14) and finalized architecture decisions.

---

## 1. Core Principles & Security Invariants

1. **Least Privilege & Role Scoping:** Every authenticated request is authorized based on the user's role loaded directly from the database on every transaction (`deps.get_current_user`). Account deactivation or role modification takes effect instantly on the subsequent request.
2. **Order of Authorization Gates (Anti-Probing & Uniform Verification):**
   - **Gate 1 — Role Check:** If an authenticated user possesses the wrong role for an endpoint, the server returns **`403 Forbidden`** immediately before any database query or record lookup.
   - **Gate 2 — Clinical Verification Gate:** A doctor who is not verified (`verification_status != "verified"`) is rejected with **`403 Forbidden`** before any record lookup, uniformly for every clinical endpoint. Because the check executes before record query, resource existence is never leaked. Unverified doctors can log in to view their account status, but are blocked from all clinical queues, cases, claims, reviews, and referrals. **Unverified doctors must never be auto-assigned cases.**
   - **Gate 3 — Resource Ownership & Anti-Probing (404 over 403):** When a user possessing the correct role requests an existing record they do not own, create, or have assigned, the server returns **`404 Not Found`** (never `403 Forbidden`). This prevents malicious actors from probing or enumerating valid case IDs, patient IDs, slot IDs, or referral IDs.
3. **Patient Identity Architecture (`patients` Collection):** Cases belong strictly to a `patient_id` referencing the `patients` collection (SPEC section 13), not directly to user accounts. A self-registered patient receives a record in `patients` linked to their `user_id` automatically (`patient.user_id == current_user.id`). Field screeners create records in `patients` without user accounts or login credentials (`patient.user_id == null`). Linking a screener-created patient record to a later self-registered account is recorded as future work.
4. **Mandatory Informed Consent Gate:** A screening case cannot be submitted (`POST /cases/{id}/submit`) unless an active, version-matched informed consent record exists for that person's `patient_id` (`consent.patient_id == case.patient_id`). For in-person field screenings, `consent.captured_by` must record the screener's user ID (`captured_by == current_user.id`).
5. **Clinical Privacy Boundary:** System Administrators **never** have access to clinical oral photographs, patient questionnaire history, or doctor diagnostic notes, and **never** sign clinical reports or view referral packets. Any administrative attempt to inspect clinical data returns **`403 Forbidden`**.
6. **Two-Factor Enforcement:** Two-Factor Authentication (TOTP) is mandatory for all `doctor` and `admin` accounts before accessing privileged routes. Unenrolled high-privilege users are restricted exclusively to `/2fa/setup` via a 5-minute temporary token carrying scope `2fa_pending`.
7. **Transition Reasons & Structural Audit Logging:**
   - Every state transition payload accepts a standardized `reason_code` (enum) and an optional `reason_text` (free-text string).
   - **Audit Invariant:** The `reason_text` is stored strictly in the case's own status transition history (`case.status_history`), visible only to assigned clinicians. It is **never copied into `audit_log`**, which receives exclusively the `reason_code`.
   - `audit_log` entries contain strictly structural metadata: event ID, `event_type`, actor ID, actor role, target record ID, IP address, user agent, `reason_code`, and timestamp.
   - System administrators inspect only structural audit logs and aggregate analytics. Doctor override reasons in analytics are displayed strictly as aggregated category counts, never free text.
8. **Consult Session ID Definition:** In ONCOLINK, teleconsultation sessions are strictly bound to a case. The **consult ID is the `case_id`** (`POST /consults/{case_id}/video-room` and `POST /consults/{case_id}/masked-call`). Every case has at most one teleconsultation room. In-person hospital visits are designated as **`appointments`** (`appointment_id`).
9. **Adult-Only Age Enforcement:** Screening intake is strictly restricted to adults aged 18 and older. This invariant requires an `age` or `date_of_birth` field on the `patients` collection. Case creation tasks must include automated tests proving rejection of under-18 patient registrations and under-18 screener intakes.

---

## 2. Role-by-Role Matrix

### 2.1. Patient (`patient`)

*Adult volunteers (age ≥ 18) and self-screeners who provide informed consent, submit screening data, access reports, track referrals, and manage appointments.*

- **Allowed Resources & Actions:**
  - `POST /auth/register`: Self-registration with consent version agreement; automatically provisions linked `patients` record.
  - `POST /consent`: Sign new/updated informed consent version for own profile (`consent.patient_id == current_user.patient_id`).
  - `GET /consent/current`: View current consent version and document text.
  - `DELETE /me/data`: Exercise right to be forgotten for self-registered patient (purges oral photographs, questionnaire history, and personal details; marks active referrals as `consent_withdrawn`; notifies partner hospital).
  - `POST /cases`: Initiate self-screening case draft under own `patient_id`.
  - `POST /cases/{id}/images`: Upload oral photographs in `draft` or `needs_retake` state.
  - `POST /cases/{id}/history`: Submit patient questionnaire history in `draft` or `needs_retake` state.
  - `POST /cases/{id}/submit`: Submit completed case for automated quality check and clinical triage (gated by consent; allowed in `draft` or `needs_retake`).
  - `GET /cases`: List past screening cases belonging to own `patient_id`.
  - `GET /cases/{id}`: View status tracking of own screening case. (Pre-signing: status only; post-signing: doctor's signed report).
  - `GET /cases/{id}/images/{image_id}`: View own uploaded oral photograph.
  - `POST /cases/{id}/cancel`: Cancel own case at any time **before** it is signed (`draft`, `submitted`, `quality_check`, `needs_retake`, `queued`, `ai_analyzed`, `under_review`, `uncertain_needs_inperson`).
  - `GET /reports/{id}`: Download signed PDF report for own case (available only once case is `signed`).
  - `GET /referrals/{id}`: Track referral status and hospital facility details for own case.
  - `GET /referrals/{id}/packet`: Download patient-facing referral summary packet.
  - `POST /appointments/{id}/confirm`: Confirm scheduled hospital appointment for own referral (`scheduled` -> `confirmed`).
  - `POST /appointments/{id}/cancel`: Cancel own scheduled hospital appointment (`scheduled` or `confirmed` -> `cancelled`).
  - `POST /appointments/{id}/reschedule-request`: Submit a request to reschedule own hospital appointment.
  - `POST /consults/{case_id}/video-room`: Join teleconsultation session for own case.
  - `POST /feedback`, `POST /tickets`: Submit service rating or request non-clinical support.

- **Denied Resources & Actions:**
  - **DENIED:** Accessing cases, patient profiles, images, reports, or referrals belonging to another patient (`404 Not Found`).
  - **DENIED:** Calling `POST /consent` for another person's `patient_id` (`404 Not Found`).
  - **DENIED:** Viewing clinical review queue (`GET /queue`) or clinician inspection tools (`403 Forbidden`).
  - **DENIED:** Viewing raw AI class, calibrated confidence scores, or Grad-CAM heatmaps (`GET /cases/{id}/heatmap` returns `403 Forbidden`).
  - **DENIED:** Confirming, overriding, or triggering AI analysis (`POST /cases/{id}/review`).
  - **DENIED:** Signing cases or reports (`POST /cases/{id}/sign`).
  - **DENIED:** Cancelling a case after it has been signed (`409 Conflict`).
  - **DENIED:** Initiating hospital referrals, holding specialist slots, or booking appointments.
  - **DENIED:** Accessing any administrative endpoint (`/admin/*`).

- **Ownership Rule:**
  - Evaluated through the `patients` collection: `case.patient_id == current_user.patient_id`.
  - Attempting to access another patient's record returns **`404 Not Found`**.

---

### 2.2. Screener (`screener`)

*Community health workers and field screeners who capture histories, consent, and oral photographs for multiple patients in camps and clinics.*

- **Allowed Resources & Actions:**
  - `POST /cases`: Create new screening case and create or select unauthenticated record in `patients`.
  - `POST /consent`: Record in-person paper/tablet informed consent for patient (`captured_by = current_user.id`).
  - `POST /patients/{id}/erasure-request`: Submit in-person data erasure request for a patient profile created by this screener.
  - `POST /cases/{id}/history`: Submit structured history questionnaire in `draft` or `needs_retake` state.
  - `POST /cases/{id}/images`: Upload oral photographs in `draft` or `needs_retake` state.
  - `GET /cases/{id}/images/{image_id}`: View oral photograph for case created by this screener.
  - `POST /cases/{id}/submit`: Submit completed case for automated quality check and clinical triage (gated by consent; allowed in `draft` or `needs_retake`).
  - `POST /cases/{id}/retake`: Capture and upload replacement photos for cases paused in `needs_retake`.
  - `POST /cases/{id}/cancel`: Cancel a case created by this screener **before** it is signed (allowed in states before `signed`).
  - `GET /cases`: View list of screening cases created by this screener (`created_by == current_user.id`).
  - `GET /cases/{id}`: View status of cases created by this screener, plus the doctor's next-step line once signed.
  - `GET /referrals`: Track referral status (`referral_pending`, `confirmed`, `attended`, `declined`) for individuals screened by this worker.

- **Denied Resources & Actions:**
  - **DENIED:** Accessing cases, profiles, or photos created by other screeners (`404 Not Found`).
  - **DENIED:** Requesting erasure for a patient record created by another screener (`404 Not Found`).
  - **DENIED:** Viewing clinical review queue (`GET /queue`) (`403 Forbidden`).
  - **DENIED:** Viewing raw AI class, calibrated confidence scores, or Grad-CAM heatmaps (`GET /cases/{id}/heatmap` returns `403 Forbidden`).
  - **DENIED:** Viewing or downloading hospital clinical referral packets (`GET /referrals/{id}/packet`) (`403 Forbidden`).
  - **DENIED:** Confirming or overriding AI classifications (`POST /cases/{id}/review`).
  - **DENIED:** Signing clinical reports (`POST /cases/{id}/sign`).
  - **DENIED:** Cancelling a case after it has been signed (`409 Conflict`).
  - **DENIED:** Initiating hospital referrals, holding slots, or booking appointments.
  - **DENIED:** Accessing administrative endpoints (`/admin/*`).

- **Ownership Rule:**
  - `case.created_by == current_user.id` and `patient.created_by == current_user.id`.
  - Requesting a case or patient created by another screener returns **`404 Not Found`**.

---

### 2.3. Doctor (`doctor`)

*Licensed medical practitioners and dentists who review the triage queue, confirm or override AI predictions, sign clinical reports, conduct teleconsults, book hospital slots, and manage referrals.*

- **Allowed Resources & Actions (Verified Doctors Only):**
  - `GET /queue`: View triage review queue sorted by urgency. Includes assigned cases and unassigned pool.
  - `GET /cases/{id}`: Full clinical case viewer for assigned cases (photographs, anatomical sites, history, AI class, calibrated confidence, quality scores).
  - `GET /cases/{id}/images/{image_id}`: Inspect original clinical photographs for assigned or second-opinion cases.
  - `GET /cases/{id}/heatmap`: Inspect Grad-CAM attention heatmap for assigned or second-opinion cases.
  - `POST /cases/{id}/claim`: Claim an unassigned case from the unassigned pool (assigns case to `current_user.id`; allowed only when `assigned_doctor_id == null` in `queued` or `ai_analyzed`).
  - `POST /cases/{id}/release`: Voluntarily release an assigned case back to `queued` with mandatory `reason_code` and optional `reason_text` (allowed only in `under_review`).
  - `POST /cases/{id}/review`: Confirm or override AI triage prediction with structured clinical rationale (allowed only in `under_review`).
  - `POST /cases/{id}/retake`: Request screener retake with feedback reason (allowed only in `under_review`; transitions to `needs_retake`).
  - `POST /cases/{id}/second-opinion`: Request second opinion, or submit second-opinion comment (allowed only in `under_review`).
  - `POST /cases/{id}/sign`: Digitally sign clinical report (allowed only in `under_review` after review completed; primary assigned doctor only).
  - `GET /cases/{id}/timeline`: View case state transition timeline and clinical notes.
  - `GET /reports/{id}`: Download signed PDF report for assigned case.
  - `GET /hospitals/search`: Search hospital directory by facility tier, distance, specialty, and next available slot.
  - `POST /slots/{id}/hold`: Place a temporary 10-minute hold on a hospital biopsy/consult slot. Must reference an assigned case (`case.assigned_doctor_id == current_user.id`; 404 otherwise). **A doctor may hold at most 3 slots at once** (attempting a 4th returns `409 Conflict`).
  - `POST /appointments`: Book a confirmed hospital appointment from a held slot. Caller must be the assigned doctor of the referenced case (`case.assigned_doctor_id == current_user.id`; 404 otherwise) and hold the slot.
  - `POST /referrals`: Issue hospital referral and attach generated clinical referral packet (allowed only in `signed`).
  - `GET /referrals`: View list of referrals originating from cases assigned to this doctor (`referral.referring_doctor_id == current_user.id`).
  - `GET /referrals/{id}`: View referral details and appointment status for own referred case.
  - `GET /referrals/{id}/packet`: View clinical referral packet for own referred case.
  - `POST /consults/{case_id}/video-room`: Initiate teleconsultation room with patient for assigned case.
  - `PUT /doctor/availability`: Configure daily review capacity and on-duty availability for automatic assignment engine.

- **Denied Resources & Actions:**
  - **DENIED (UNVERIFIED):** Every clinical endpoint returns **`403 Forbidden`** before record lookup if `verification_status != "verified"`. Unverified doctors are never auto-assigned cases.
  - **DENIED (NON-ASSIGNED):** Accessing clinical cases assigned to other doctors returns **`404 Not Found`**.
  - **DENIED (SECOND OPINION SIGNING):** Second-opinion doctors have comment-only access; `POST /cases/{id}/sign` returns **`403 Forbidden`**.
  - **DENIED (CLAIMING ASSIGNED):** Claiming a case that is already assigned to another doctor returns **`409 Conflict`**.
  - **DENIED (CASE CANCELLATION):** Cancelling screening cases (`POST /cases/{id}/cancel` returns **`403 Forbidden`**; doctors cannot cancel cases).
  - **DENIED (COORDINATOR ACTIONS):** Managing hospital master schedules or recording biopsy outcomes (owned by Hospital Coordinator).
  - **DENIED (ADMINISTRATION):** Inspecting raw audit logs (`GET /admin/audit-logs`) or admin analytics (`/admin/*`).

- **Ownership & Case Allocation Rules:**
  - **Default Workflow:** Per SPEC section 7, **automatic case assignment by availability and capacity is the default**.
  - **Assigned Visibility:** Primary assignee sees full clinical data (`assigned_doctor_id == current_user.id`).
  - **Second Opinion Visibility:** Doctor sees full clinical data and submit comments (`second_opinion_doctor_id == current_user.id`), but cannot sign (`403 Forbidden`).
  - **Unassigned Pool Visibility:** In `GET /queue`, doctors see **metadata only** (reference ID, age, urgency, waiting time, anatomical sites). **No photographs and no medical history** are disclosed until claimed (`POST /cases/{id}/claim`).

---

### 2.4. Hospital Coordinator (`hospital_coordinator`)

*Hospital facility personnel who manage department rosters, specialist schedules, slot capacity, incoming referrals, clinic attendance, and biopsy outcomes for their assigned hospital.*

- **Allowed Resources & Actions:**
  - `GET /hospitals/{id}`: View profile and department details of coordinator's assigned hospital (`id == current_user.hospital_id`).
  - `PUT /hospitals/{id}`: Update department contact info and clinic hours for assigned hospital.
  - `POST /hospitals/{id}/specialists`: Manage specialist directory for assigned hospital.
  - `POST /hospitals/{id}/schedules`: Configure weekly specialist schedules, blocked dates, and daily slot capacity.
  - `GET /hospitals/{id}/slots`: Inspect generated appointment slots for assigned hospital.
  - `GET /referrals`: View incoming referral inbox for coordinator's hospital sorted by clinical urgency.
  - `GET /referrals/{id}`: View referral details and status for coordinator's hospital.
  - `GET /referrals/{id}/packet`: View read-only clinical referral packet (oral photos, AI model version, history, doctor review notes). Every packet access is logged in `audit_log`. Coordinators see clinical images strictly inside this packet.
  - `PATCH /referrals/{id}/status`: Accept referral, reschedule, or decline with mandatory clinical decline reason (allowed in `referral_pending`).
  - `POST /appointments/{id}/attendance`: Record patient attendance (`attended` or `no_show`; allowed in `confirmed`).
  - `POST /appointments/{id}/outcome`: Record biopsy confirmation outcome and histopathology staging (allowed in `attended`).

- **Denied Resources & Actions:**
  - **DENIED:** Accessing referrals, slots, schedules, or packets belonging to any other hospital (`404 Not Found`).
  - **DENIED:** Direct image or heatmap inspection endpoints (`GET /cases/{id}/images/{image_id}`, `GET /cases/{id}/heatmap` return `403 Forbidden`). Images are accessible strictly inside the compiled referral packet.
  - **DENIED:** Cancelling screening cases (`POST /cases/{id}/cancel` returns `403 Forbidden`).
  - **DENIED:** Viewing the doctor clinical review queue (`GET /queue`) (`403 Forbidden`).
  - **DENIED:** Confirming/overriding AI classifications or signing screening reports.
  - **DENIED:** User administration, hospital creation, or system analytics (`/admin/*`).

- **Ownership Rule:**
  - Strictly single-facility: `referral.hospital_id == current_user.hospital_id`. Requesting records of another hospital returns **`404 Not Found`**.

---

### 2.5. Administrator (`admin`)

*System operators and compliance officers responsible for accounts, credential verification, facility onboarding, analytics, and operational integrity.*

- **Allowed Resources & Actions:**
  - `GET /admin/users`: List all registered accounts with role, verification status, active flag, and demo badge.
  - `POST /admin/users`: Provision staff accounts (`screener`, `doctor`, `hospital_coordinator`, `admin`).
  - `POST /admin/doctors/{id}/verify`: Verify or reject doctor medical registration credentials.
  - `POST /admin/hospitals`: Create partner hospital facility records in the master directory.
  - `PATCH /admin/users/{id}/hospital`: Link a hospital coordinator user to exactly one hospital facility (`user.hospital_id`).
  - `POST /admin/hospitals/{id}/verify`: Verify partner hospital facility credentials.
  - `POST /admin/users/{id}/deactivate`: Deactivate accounts. Staff accounts are deactivated, **never purged**.
  - `POST /admin/patients/{id}/erase`: Execute data erasure for an unauthenticated patient record upon screener erasure request. Admin sees only IDs and counts, never clinical content. Audited by ID only.
  - `GET /admin/analytics`: View aggregate screening counts, SLA turnaround times, and model override category counts.
  - `GET /admin/audit-logs`: Inspect immutable structural system audit trail (`audit_log`).
  - `POST /admin/reset-demo`: Reset demonstration test data (disabled in production).

- **Denied Resources & Actions:**
  - **STRICT PROHIBITION — CLINICAL PRIVACY BLIND:**
    - Administrator **NEVER** views patient clinical oral photographs (`/cases/{id}/images`, `/cases/{id}/images/{image_id}`).
    - Administrator **NEVER** views heatmaps (`/cases/{id}/heatmap`).
    - Administrator **NEVER** views patient questionnaire history answers.
    - Administrator **NEVER** views clinical referral packets (`/referrals/{id}/packet`).
    - Administrator **NEVER** overrides AI classifications or signs clinical reports.
    - Administrator **NEVER** issues medical referrals, books hospital slots, or alters biopsy outcomes.
    - Administrator **NEVER** cancels clinical cases.
    - Any attempt by an admin to access clinical inspection endpoints returns **`403 Forbidden`**.
  - **Self-Deactivation Guard:** Administrator cannot deactivate their own account (`errors.cannot_deactivate_self`).

---

## 3. Permissions Matrix Summary

| Resource / Endpoint | Patient | Screener | Doctor (Verified) | Doctor (Unverified) | Coordinator | Admin |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| `POST /auth/register` (Patient self-registration) | 403 | 403 | 403 | 403 | 403 | 403 |
| `POST /admin/users` (Provision staff users) | 403 | 403 | 403 | 403 | 403 | Allowed |
| `POST /admin/doctors/{id}/verify` (Doctor verification) | 403 | 403 | 403 | 403 | 403 | Allowed |
| `POST /admin/hospitals` (Create hospital) | 403 | 403 | 403 | 403 | 403 | Allowed |
| `PATCH /admin/users/{id}/hospital` (Link coordinator) | 403 | 403 | 403 | 403 | 403 | Allowed |
| `DELETE /me/data` (Right to be forgotten) | Own Profile | 403 | 403 | 403 | 403 | 403 |
| `POST /patients/{id}/erasure-request` (Screener request)| 403 | Own Creator | 403 | 403 | 403 | 403 |
| `POST /admin/patients/{id}/erase` (Execute erasure)| 403 | 403 | 403 | 403 | 403 | Allowed |
| `POST /cases` (Create screening case) | Own Profile | Allowed | 403 | 403 | 403 | 403 |
| `POST /cases/{id}/images` (Upload photos) | Own Profile | Own Case | 403 | 403 | 403 | 403 |
| `GET /cases/{id}/images/{image_id}` (Original photo) | Own Profile | Own Case | Assigned/2nd-Op | **403** | **403** | **403** |
| `GET /cases/{id}/heatmap` (Grad-CAM heatmap) | **403** | **403** | Assigned/2nd-Op | **403** | **403** | **403** |
| `POST /cases/{id}/history` (Submit history) | Own Profile | Own Case | 403 | 403 | 403 | 403 |
| `POST /cases/{id}/submit` (Submit for triage) | Own Profile | Own Case (Consent Gated) | 403 | 403 | 403 | 403 |
| `POST /cases/{id}/cancel` (Cancel before signing) | Own Profile | Own Case | 403 | 403 | 403 | 403 |
| `GET /queue` (Clinical review queue) | 403 | 403 | Allowed (Pool/Assign) | **403** | 403 | 403 |
| `GET /cases/{id}` (Clinical viewer / status) | Status Only (Own) | Status/Next-step (Own) | Assigned/2nd-Op | **403** | 403 | **403** |
| `POST /cases/{id}/claim` (Claim unassigned case)| 403 | 403 | Pool only | **403** | 403 | 403 |
| `POST /cases/{id}/release` (Release to queue) | 403 | 403 | Assigned only | **403** | 403 | 403 |
| `POST /cases/{id}/review` (Confirm/override AI) | 403 | 403 | Assigned only | **403** | 403 | 403 |
| `POST /cases/{id}/retake` (Request retake) | 403 | 403 | Assigned only | **403** | 403 | 403 |
| `POST /cases/{id}/second-opinion` (2nd opinion) | 403 | 403 | Allowed (Comment only)| **403** | 403 | 403 |
| `POST /cases/{id}/sign` (Sign clinical report) | 403 | 403 | Assigned only | **403** | 403 | 403 |
| `GET /cases/{id}/timeline` (Status timeline) | 403 | 403 | Assigned/2nd-Op | **403** | 403 | 403 |
| `GET /reports/{id}` (Download signed PDF) | Own Profile (Signed) | 403 | Assigned/2nd-Op | **403** | 403 | 403 |
| `GET /hospitals/search` (Search directory) | 403 | 403 | Allowed | **403** | 403 | 403 |
| `POST /slots/{id}/hold` (Hold hospital slot) | 403 | 403 | Assigned Case (≤3) | **403** | 403 | 403 |
| `POST /appointments` (Book from held slot) | 403 | 403 | Assigned Case | **403** | 403 | 403 |
| `POST /appointments/{id}/confirm` (Confirm apt) | Own Profile | 403 | 403 | 403 | 403 | 403 |
| `POST /appointments/{id}/cancel` (Cancel apt) | Own Profile | 403 | 403 | 403 | 403 | 403 |
| `POST /appointments/{id}/reschedule-request` | Own Profile | 403 | 403 | 403 | 403 | 403 |
| `POST /referrals` (Refer to hospital) | 403 | 403 | Assigned only | **403** | 403 | 403 |
| `GET /referrals` (Referral inbox / list) | 403 | Own Cohort (Status) | Own Cases only | **403** | Own Hospital only | 403 |
| `GET /referrals/{id}/packet` (Referral packet) | Own Profile | 403 | Own Cases only | **403** | Own Hospital only | **403** |
| `PATCH /referrals/{id}/status` (Accept/decline)| 403 | 403 | 403 | 403 | Own Hospital only | 403 |
| `POST /appointments/{id}/attendance` (Attendance)| 403 | 403 | 403 | 403 | Own Hospital only | 403 |
| `POST /appointments/{id}/outcome` (Biopsy outcome)| 403 | 403 | 403 | 403 | Own Hospital only | 403 |
| `GET /admin/audit-logs` (Audit compliance log) | 403 | 403 | 403 | 403 | 403 | Allowed |
| `GET /admin/analytics` (Aggregated statistics) | 403 | 403 | 403 | 403 | 403 | Allowed |

---

## 4. Final Architecture & Permissions Decisions

The following architectural, clinical, and security decisions are finalized for the ONCOLINK platform:

1. **Doctor Case Release & Reassignment (`Resolved`):**
   - **Decision:** Yes, an assigned doctor may voluntarily release a claimed case back to the `queued` state. A mandatory `reason_code` and optional `reason_text` must be supplied. The `reason_code` is audited; `reason_text` is stored strictly in the case's status history.
   - **SLA Invariant:** Automatic SLA re-assignment timers (SPEC section 7: urgent < 4h, soon < 24h, routine < 48h) remain active concurrently.
2. **Screener Visibility & Community Camps (`Resolved`):**
   - **Decision:** No shared visibility across screeners. Each field screener sees exclusively cases they individually created (`case.created_by == current_user.id`).
   - **Roadmap:** Multi-screener camp-level shared queues and camp identifiers are deferred to future milestones.
3. **Minors, Guardianship & Age Enforcement (`Resolved`):**
   - **Decision:** Out of scope for this prototype per SPEC section 5.1. Self-screening and camp intake are strictly restricted to adults aged 18 and older; registration and profile creation for users under 18 is blocked and documented as a known platform limitation.
   - **Implementation Rule:** Adult-only enforcement requires an `age` or `date_of_birth` field on the `patients` collection, enforced in the case task with unit and integration tests rejecting under-18 registrations and screener intakes.
4. **Hospital Coordinator Facility Boundary (`Resolved`):**
   - **Decision:** Strictly single-facility. One hospital coordinator account belongs to exactly one hospital facility (`user.hospital_id`). Multi-facility coordinator roles are prohibited.
5. **Case History & Clinician Audit Visibility (`Resolved`):**
   - **Decision:** Role-segregated visibility. Reviewing doctors see their case's clinical status timeline (`GET /cases/{id}/timeline`). Only administrators see the raw system audit log (`GET /admin/audit-logs`), and administrators never see clinical oral photographs or diagnostic notes.
6. **Patient Identity Architecture (`patients` Collection) (`Resolved`):**
   - **Decision:** Cases belong to `patient_id` referencing the `patients` collection (SPEC section 13). Self-registered patients receive a record in `patients` linked to `user_id`. Field screener records in `patients` have no login credentials (`user_id == null`). Linking a screener-created record to a later account is recorded as future work.
7. **Screener Clinical Visibility Boundaries (`Resolved`):**
   - **Decision:** Screeners view case status, the doctor's next-step recommendation line from the signed report, and referral status for individuals they screened. Screeners **never** see raw AI details (class, confidence, heatmap) and **never** access clinical referral packets.
8. **Data Deletion & Erasure for Unauthenticated Profiles (`Resolved`):**
   - **Decision:**
     - For self-registered accounts: `DELETE /me/data` purges oral images (GridFS), questionnaire answers, and personal details; marks active referrals as `consent_withdrawn`; notifies hospitals.
     - For unauthenticated screener-created profiles: Screener submits an erasure request via `POST /patients/{id}/erasure-request`. Administrator executes erasure via `POST /admin/patients/{id}/erase`. Admin sees only structural IDs and counts, never clinical content. Audited strictly by ID.
     - Hospital-held copies are listed as a known platform limitation. Staff accounts are deactivated, never purged.
9. **Case Assignment Workflow & Pool Visibility (`Resolved`):**
   - **Decision:** Automatic case assignment by availability and capacity is the default per SPEC section 7. Unverified doctors are never auto-assigned cases. Assigned doctors see full clinical data. Unassigned cases appear in a pool displaying only reference ID, age, urgency, waiting time, and anatomical sites (no photos or history) until claimed by a verified doctor. Claiming applies exclusively to the unassigned pool.

---

## 5. State-Dependent Write Endpoint Rules

For every write endpoint, the table below defines the exact case, appointment, or referral states in which execution is permitted. Calling an endpoint in any other state returns **`409 Conflict`**.

| Endpoint | Allowed States | Effect / Transition | State on Error (`409 Conflict`) |
|---|---|---|---|
| `POST /cases/{id}/images` | `draft`, `needs_retake` | Appends image to case | Any other case state returns 409 |
| `POST /cases/{id}/history` | `draft`, `needs_retake` | Saves questionnaire answers | Any other case state returns 409 |
| `POST /cases/{id}/submit` | `draft`, `needs_retake` | Moves case to `submitted` | Any other case state returns 409 |
| `POST /cases/{id}/cancel` | Prior to `signed` (`draft`, `submitted`, `quality_check`, `needs_retake`, `queued`, `ai_analyzed`, `under_review`, `uncertain_needs_inperson`) | Moves case to `cancelled` | `signed`, `referred`, or any subsequent state returns 409 |
| `POST /cases/{id}/claim` | `queued`, `ai_analyzed` (with `assigned_doctor_id == null`) | Assigns doctor; moves case to `under_review` | Already assigned or non-pool state returns 409 |
| `POST /cases/{id}/release` | `under_review` (assigned to caller) | Unassigns doctor; moves case to `queued` | Any other state returns 409 |
| `POST /cases/{id}/review` | `under_review` | Records confirm/override rationale | Any other state returns 409 |
| `POST /cases/{id}/retake` | `under_review` | Moves case to `needs_retake` | Any other state returns 409 |
| `POST /cases/{id}/second-opinion` | `under_review` | Requests opinion or records comment | Any other state returns 409 |
| `POST /cases/{id}/sign` | `under_review` (after review complete) | Moves case to `signed` | Any other state returns 409 |
| `POST /slots/{id}/hold` | Case in `under_review` or `signed` | Holds slot for 10 min (≤3 held per doctor) | Slot held/booked or >3 holds returns 409 |
| `POST /appointments` | Case in `signed`, `referred`, or `referral_pending` | Books appointment from held slot | Slot not held or case not in referral state returns 409 |
| `POST /referrals` | `signed` | Moves case to `referred` -> `referral_pending` | Unsigned or already referred returns 409 |
| `PATCH /referrals/{id}/status` | Referral in `referral_pending` | Moves referral to `confirmed` or `declined` | Any other referral state returns 409 |
| `POST /appointments/{id}/confirm` | Appointment in `scheduled` | Moves appointment to `confirmed` | Non-scheduled appointment returns 409 |
| `POST /appointments/{id}/cancel` | Appointment in `scheduled` or `confirmed` | Moves appointment to `cancelled` | Already attended/cancelled returns 409 |
| `POST /appointments/{id}/reschedule-request` | Appointment in `scheduled` or `confirmed` | Requests reschedule with coordinator | Already attended/cancelled returns 409 |
| `POST /appointments/{id}/attendance` | Appointment in `confirmed` | Moves appointment to `attended` or `no_show` | Non-confirmed appointment returns 409 |
| `POST /appointments/{id}/outcome` | Case in `attended` | Records biopsy outcome; closes case | Non-attended case returns 409 |

---

## 6. Authorization Test Matrix

This matrix specifies the exact expected HTTP response status code for every platform endpoint across all caller roles and context variants. Every feature task must turn these specifications into automated integration tests.

### Status Code Invariants
- **`200` / `201` / `204`:** Successful authorized execution.
- **`401 Unauthorized`:** Unauthenticated request (missing, invalid, or expired session token).
- **`403 Forbidden`:** Wrong role; unverified doctor attempting clinical access; second-opinion doctor attempting to sign; coordinator attempting direct photo/heatmap access outside referral packet; or patient attempting to view heatmaps/AI details.
- **`404 Not Found`:** Caller possesses the right role, but the record does not exist or the caller is not the owner, creator, assigned clinician, or linked hospital facility (anti-probing invariant).
- **`N/A`:** Not applicable (the endpoint creates a new entity or operates strictly on current user session with no target resource to probe).

| Endpoint & Action | Unauth | Patient (Owner) | Patient (Other) | Screener (Creator) | Screener (Other) | Doctor (Assigned) | Doctor (Second opinion) | Doctor (Other) | Doctor (Unverified) | Coord (Own Hosp) | Coord (Other Hosp) | Admin |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `POST /auth/register` (Patient self-registration) | 201 | 403 | N/A | 403 | N/A | 403 | 403 | N/A | 403 | 403 | N/A | 403 |
| `POST /auth/login` (Step 1 password login) | 200 | 200 | N/A | 200 | N/A | 200 | 200 | N/A | 200 | 200 | N/A | 200 |
| `POST /auth/2fa/login` (Step 2 TOTP verification) | 401 | 401 | N/A | 401 | N/A | 200 | 200 | N/A | 200 | 401 | N/A | 200 |
| `POST /auth/2fa/setup` (Generate TOTP secret) | 401 | 401 | N/A | 401 | N/A | 401 | 401 | N/A | 200 (Temp) | 401 | N/A | 200 (Temp) |
| `POST /auth/2fa/verify-setup` (Confirm TOTP) | 401 | 401 | N/A | 401 | N/A | 401 | 401 | N/A | 200 (Temp) | 401 | N/A | 200 (Temp) |
| `GET /auth/me` (Current user profile & session) | 401 | 200 | N/A | 200 | N/A | 200 | 200 | N/A | 200 | 200 | N/A | 200 |
| `POST /auth/refresh` (Rotate refresh token) | 401 | 200 | N/A | 200 | N/A | 200 | 200 | N/A | 200 | 200 | N/A | 200 |
| `POST /auth/logout` (Revoke refresh session) | 401 | 200 | N/A | 200 | N/A | 200 | 200 | N/A | 200 | 200 | N/A | 200 |
| `GET /consent/current` (Current active consent) | 200 | 200 | N/A | 200 | N/A | 200 | 200 | N/A | 200 | 200 | N/A | 200 |
| `POST /consent` (Record informed consent) | 401 | 201 (Self) | 404 | 201 (In-person)| 404 | 403 | 403 | 403 | 403 | 403 | 403 | 403 |
| `DELETE /me/data` (Right to be forgotten) | 401 | 200 | N/A | 403 | N/A | 403 | 403 | N/A | 403 | 403 | N/A | 403 |
| `POST /patients/{id}/erasure-request` (Screener request)| 401 | 403 | 403 | 200 | 404 | 403 | 403 | 403 | 403 | 403 | 403 | 403 |
| `POST /admin/patients/{id}/erase` (Execute erasure)| 401 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 200 |
| `POST /cases` (Create screening case draft) | 401 | 201 | N/A | 201 | N/A | 403 | 403 | N/A | 403 | 403 | N/A | 403 |
| `POST /cases/{id}/images` (Upload photographs) | 401 | 200 | 404 | 200 | 404 | 403 | 403 | 403 | 403 | 403 | 403 | 403 |
| `GET /cases/{id}/images/{image_id}` (Original photo) | 401 | 200 | 404 | 200 | 404 | 200 | 200 | 404 | **403** | **403** | **403** | **403** |
| `GET /cases/{id}/heatmap` (Grad-CAM heatmap) | 401 | **403** | **403** | **403** | **403** | 200 | 200 | 404 | **403** | **403** | **403** | **403** |
| `POST /cases/{id}/history` (Submit questionnaire) | 401 | 200 | 404 | 200 | 404 | 403 | 403 | 403 | 403 | 403 | 403 | 403 |
| `POST /cases/{id}/submit` (Submit for triage) | 401 | 200 | 404 | 200 | 404 | 403 | 403 | 403 | 403 | 403 | 403 | 403 |
| `POST /cases/{id}/cancel` (Cancel before signing)| 401 | 200 | 404 | 200 | 404 | 403 | 403 | 403 | 403 | 403 | 403 | 403 |
| `GET /cases` (List user-accessible cases) | 401 | 200 (Own) | N/A | 200 (Own) | N/A | 403 | 403 | N/A | 403 | 403 | N/A | 403 |
| `GET /cases/{id}` (Case viewer / status) | 401 | 200 (Status)| 404 | 200 (Status)| 404 | 200 (Full) | 200 (Full) | 404 | **403** | 403 | 403 | 403 |
| `GET /queue` (Clinical review queue) | 401 | 403 | 403 | 403 | 403 | 200 | 200 | 200 | **403** | 403 | 403 | 403 |
| `POST /cases/{id}/claim` (Claim unassigned case)| 401 | 403 | 403 | 403 | 403 | 200 (Pool) | 403 | 404 | **403** | 403 | 403 | 403 |
| `POST /cases/{id}/release` (Release to queue) | 401 | 403 | 403 | 403 | 403 | 200 | 403 | 404 | **403** | 403 | 403 | 403 |
| `POST /cases/{id}/review` (Confirm/override AI) | 401 | 403 | 403 | 403 | 403 | 200 | 403 | 404 | **403** | 403 | 403 | 403 |
| `POST /cases/{id}/retake` (Request photo retake) | 401 | 403 | 403 | 403 | 403 | 200 | 403 | 404 | **403** | 403 | 403 | 403 |
| `POST /cases/{id}/second-opinion` (2nd opinion) | 401 | 403 | 403 | 403 | 403 | 200 | 200 (Comment)| 404 | **403** | 403 | 403 | 403 |
| `POST /cases/{id}/sign` (Digitally sign report) | 401 | 403 | 403 | 403 | 403 | 200 | **403** | 404 | **403** | 403 | 403 | 403 |
| `GET /cases/{id}/timeline` (Status timeline) | 401 | 403 | 403 | 403 | 403 | 200 | 200 | 404 | **403** | 403 | 403 | 403 |
| `GET /reports/{id}` (Download signed PDF report) | 401 | 200 (Signed)| 404 | 403 | 403 | 200 | 200 | 404 | **403** | 403 | 403 | 403 |
| `GET /hospitals/search` (Search directory) | 401 | 403 | 403 | 403 | 403 | 200 | 200 | 200 | **403** | 403 | 403 | 403 |
| `POST /slots/{id}/hold` (Hold hospital slot) | 401 | 403 | 403 | 403 | 403 | 200 (≤3) | 403 | 404 | **403** | 403 | 403 | 403 |
| `POST /appointments` (Book from held slot) | 401 | 403 | 403 | 403 | 403 | 200 | 403 | 404 | **403** | 403 | 403 | 403 |
| `POST /appointments/{id}/confirm` (Confirm apt) | 401 | 200 | 404 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 |
| `POST /appointments/{id}/cancel` (Cancel apt) | 401 | 200 | 404 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 |
| `POST /appointments/{id}/reschedule-request` | 401 | 200 | 404 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 |
| `POST /referrals` (Create hospital referral) | 401 | 403 | 403 | 403 | 403 | 201 | 403 | 404 | **403** | 403 | 403 | 403 |
| `GET /referrals` (Referral inbox / list) | 401 | 403 | 403 | 200 (Cohort) | 404 | 200 (Own) | 403 | 404 | **403** | 200 (Hosp) | 404 | 403 |
| `GET /referrals/{id}` (Referral details) | 401 | 200 | 404 | 200 (Cohort) | 404 | 200 | 403 | 404 | **403** | 200 | 404 | 403 |
| `GET /referrals/{id}/packet` (Clinical packet) | 401 | 200 | 404 | 403 | 403 | 200 | 403 | 404 | **403** | 200 | 404 | **403** |
| `PATCH /referrals/{id}/status` (Accept/decline)| 401 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 200 | 404 | 403 |
| `POST /appointments/{id}/attendance` | 401 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 200 | 404 | 403 |
| `POST /appointments/{id}/outcome` (Biopsy) | 401 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 200 | 404 | 403 |
| `POST /consults/{case_id}/video-room` (Teleconsult) | 401 | 200 | 404 | 403 | 403 | 200 | 200 | 404 | **403** | 403 | 403 | 403 |
| `POST /consults/{case_id}/masked-call` (Phone) | 401 | 200 | 404 | 403 | 403 | 200 | 200 | 404 | **403** | 403 | 403 | 403 |
| `GET /admin/users` (List user accounts) | 401 | 403 | N/A | 403 | N/A | 403 | 403 | N/A | 403 | 403 | N/A | 200 |
| `POST /admin/users` (Provision staff account) | 401 | 403 | N/A | 403 | N/A | 403 | 403 | N/A | 403 | 403 | N/A | 201 |
| `POST /admin/doctors/{id}/verify` (Verify doctor)| 401 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 200 |
| `POST /admin/hospitals` (Create hospital) | 401 | 403 | N/A | 403 | N/A | 403 | 403 | N/A | 403 | 403 | N/A | 201 |
| `PATCH /admin/users/{id}/hospital` (Link coord) | 401 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 200 |
| `POST /admin/users/{id}/deactivate` | 401 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 200 |
| `GET /admin/audit-logs` (System audit trail) | 401 | 403 | N/A | 403 | N/A | 403 | 403 | N/A | 403 | 403 | N/A | 200 |
| `GET /admin/analytics` (Aggregate metrics) | 401 | 403 | N/A | 403 | N/A | 403 | 403 | N/A | 403 | 403 | N/A | 200 |
