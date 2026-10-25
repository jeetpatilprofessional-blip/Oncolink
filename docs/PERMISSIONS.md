# ONCOLINK Role & Permissions Matrix

This document defines the authoritative permissions, resource ownership rules, access boundaries, and authorization gates for all ONCOLINK roles. Derived directly from `docs/SPEC.md` (sections 3, 5, 7, 8, 12, 13, and 14) and finalized architecture decisions.

---

## 1. Core Principles & Security Invariants

1. **Least Privilege & Role Scoping:** Every authenticated request is authorized based on the user's role loaded directly from the database on every transaction (`deps.get_current_user`). Deactivation or role modification takes effect instantly on the subsequent request.
2. **Order of Authorization Gates (Anti-Probing & Leak Prevention):**
   - **Gate 1 — Role Check:** If the authenticated user possesses the wrong role for an endpoint, the server returns **`403 Forbidden`** immediately before any database query or record lookup.
   - **Gate 2 — Resource Ownership & Anti-Probing (404 over 403):** If the user possesses the right role but is not the owner, creator, or assigned clinician of the requested record, the server returns **`404 Not Found`** (never `403 Forbidden`). This prevents malicious actors from probing or enumerating valid case IDs, patient profile IDs, or referral IDs.
   - **Gate 3 — Verification Check (Ownership Precedes Verification):** Resource ownership is evaluated *before* clinician verification status (`verification_status == "verified"`). An unverified practitioner requesting a record they do not own receives `404 Not Found`, ensuring record existence is never leaked to unverified staff.
3. **Patient Profile Identity Architecture:** Cases belong strictly to a `patient_profile_id`, not directly to user accounts. A self-registered patient receives a `patient_profile` linked to their `user_id` automatically (`profile.user_id == current_user.id`). Field screeners create patient profiles without user accounts or login credentials (`profile.user_id == null`). Linking a screener-created profile to a later self-registered account is recorded as future work.
4. **Mandatory Informed Consent Gate:** A screening case cannot be submitted (`POST /cases/{id}/submit`) unless an active, version-matched informed consent record exists for that profile's person (`consent.patient_profile_id == case.patient_profile_id`). For field screenings, `consent.captured_by` must be set to the screener's user ID (`captured_by == current_user.id`).
5. **Clinical Privacy Boundary:** System Administrators **never** have access to clinical oral photographs, patient questionnaire history, or doctor diagnostic notes, and **never** sign clinical reports or view referral packets. Any administrative attempt to inspect clinical data returns **`403 Forbidden`**.
6. **Verified Human Oversight & Clinical Verification Gate:** AI classifications are advisory triage outputs. Only a verified medical doctor (`verification_status == "verified"`) with an active registration number can access clinical queues, view cases, claim cases, confirm/override AI, sign reports, or issue referrals. Unverified doctors can authenticate but see only a notice that verification is pending.
7. **Two-Factor Enforcement:** Two-Factor Authentication (TOTP) is mandatory for all `doctor` and `admin` accounts before accessing privileged routes. Unenrolled high-privilege users are restricted exclusively to `/2fa/setup` via a 5-minute temporary token carrying scope `2fa_pending`.
8. **Structural ID-Only Audit Logging:** Entries in `audit_log` contain strictly structural metadata: event ID, `event_type`, actor ID, actor role, target record ID, IP address, user agent, and timestamp. Audit entries **never contain free-text clinical content** (such as doctor override reasons, diagnostic notes, or patient history answers). Free-text clinical records live strictly in case collections (`cases`, `reviews`). System administrators inspect only structural audit logs and aggregate analytics. Override reasons in analytics are displayed strictly as aggregated category counts, never free text.
9. **Adult-Only Age Enforcement:** Screening intake is strictly restricted to adults aged 18 and older. This invariant requires an `age` or `date_of_birth` field on `patient_profiles`. Case creation tasks must include automated tests proving rejection of under-18 patient registrations and under-18 screener-created profiles.

---

## 2. Role-by-Role Matrix

### 2.1. Patient (`patient`)

*Adult volunteers (age ≥ 18) and self-screeners who provide informed consent, submit screening data, access reports, track referrals, and manage appointments.*

- **Allowed Resources & Actions:**
  - `POST /auth/register`: Self-registration with explicit consent version agreement; automatically provisions linked `patient_profile`.
  - `POST /consent`: Sign new/updated informed consent version.
  - `GET /consent/current`: View current consent version and document text.
  - `DELETE /me/data`: Exercise right to be forgotten (purges oral photographs, questionnaire history, and personal details; marks active referrals as `consent_withdrawn`; notifies partner hospital).
  - `POST /cases`: Initiate self-screening case draft under own `patient_profile_id`.
  - `POST /cases/{id}/images`: Upload oral photographs according to the capture protocol.
  - `POST /cases/{id}/history`: Submit patient questionnaire history.
  - `POST /cases/{id}/submit`: Submit completed case for automated quality check and clinical triage (gated by active consent).
  - `GET /cases`: List past screening cases belonging to own `patient_profile_id`.
  - `GET /cases/{id}`: View status and status history of own screening case. (Before signing, patient sees only case status; after signing, sees doctor's signed report).
  - `POST /cases/{id}/cancel`: Cancel own case at any time **before** it is signed (transitions case to `cancelled`).
  - `GET /reports/{id}`: Download signed PDF report for own case (available only once case is `signed`).
  - `GET /referrals/{id}`: Track referral status and hospital facility details for own case.
  - `GET /referrals/{id}/packet`: Download patient-facing referral summary packet.
  - `POST /appointments/{id}/confirm`: Confirm scheduled hospital appointment for own referral.
  - `POST /appointments/{id}/cancel`: Cancel own scheduled hospital appointment.
  - `POST /appointments/{id}/reschedule-request`: Submit a request to reschedule own hospital appointment.
  - `POST /consults/{id}/video-room`: Join teleconsultation session for own case.
  - `POST /feedback`, `POST /tickets`: Submit service rating or request non-clinical support.

- **Denied Resources & Actions:**
  - **DENIED:** Accessing cases, profiles, images, reports, or referrals belonging to another patient (`404 Not Found`).
  - **DENIED:** Viewing clinical review queue (`GET /queue`) or clinician inspection tools (`403 Forbidden`).
  - **DENIED:** Viewing raw AI class, calibrated confidence scores, or Grad-CAM heatmaps on any screen or API response (`403 Forbidden`).
  - **DENIED:** Confirming, overriding, or triggering AI analysis (`POST /cases/{id}/review`).
  - **DENIED:** Signing cases or reports (`POST /cases/{id}/sign`).
  - **DENIED:** Cancelling a case after it has already been signed (`400 Bad Request` / `403 Forbidden`).
  - **DENIED:** Initiating hospital referrals, holding specialist slots, or managing hospital capacity.
  - **DENIED:** Accessing any administrative endpoint (`/admin/*`).

- **Ownership Rule:**
  - Ownership is evaluated through the patient profile:
    `case.patient_profile_id == current_user.patient_profile_id`
  - A patient accesses exclusively records tied to their own linked profile. Attempting to access another patient's record returns **`404 Not Found`**.

- **Visibility Rules:**
  - **Pre-Signing:** Before a clinical report is signed (`case.status != "signed"`), patient views **only** high-level status tracking (`submitted`, `under_review`, `needs_retake`).
  - **Post-Signing:** After signing, patient views the verified human doctor's report and recommendations.
  - **AI Blind:** Raw AI classes, model confidence percentages, and attention heatmaps are strictly hidden from patient view at all times.

- **Authorization Gates:**
  - **Gate 1 (Consent):** Active informed consent record for the patient profile required before submitting a case or uploading photos.
  - **Gate 2 (Age):** Patient profile must confirm age ≥ 18; under-18 registration is rejected.

---

### 2.2. Screener (`screener`)

*Community health workers and field screeners who capture histories, consent, and oral photographs for multiple patients in camps and clinics.*

- **Allowed Resources & Actions:**
  - `POST /cases`: Create new screening case and create or select unauthenticated `patient_profile`.
  - `POST /consent`: Record in-person paper/tablet informed consent for patient profile (`captured_by = current_user.id`).
  - `POST /cases/{id}/history`: Submit structured history questionnaire (tobacco, alcohol, lesion characteristics, red flags).
  - `POST /cases/{id}/images`: Upload oral photographs (close-up and context views) with anatomical site labels.
  - `POST /cases/{id}/submit`: Submit completed case for automated quality check and clinical triage (strictly gated by consent).
  - `POST /cases/{id}/retake`: Capture and upload replacement photos for cases paused in `needs_retake`.
  - `POST /cases/{id}/cancel`: Cancel a case created by this screener at any time **before** it is signed (transitions case to `cancelled`).
  - `GET /cases`: View list of screening cases created by this screener (`created_by == current_user.id`).
  - `GET /cases/{id}`: View status of cases created by this screener, plus the doctor's next-step line once signed.
  - `GET /referrals`: Track referral status (`referral_pending`, `confirmed`, `attended`, `declined`) for individuals screened by this worker.

- **Denied Resources & Actions:**
  - **DENIED:** Accessing cases, profiles, or photos created by other screeners (`404 Not Found`).
  - **DENIED:** Viewing clinical review queue (`GET /queue`) (`403 Forbidden`).
  - **DENIED:** Viewing raw AI class, calibrated confidence scores, or Grad-CAM heatmaps (`403 Forbidden`).
  - **DENIED:** Viewing or downloading hospital clinical referral packets (`GET /referrals/{id}/packet`) (`403 Forbidden`).
  - **DENIED:** Confirming or overriding AI classifications (`POST /cases/{id}/review`).
  - **DENIED:** Signing clinical reports (`POST /cases/{id}/sign`).
  - **DENIED:** Cancelling a case after it has been signed (`400 Bad Request` / `403 Forbidden`).
  - **DENIED:** Initiating hospital referrals, holding slots, or booking appointments.
  - **DENIED:** Accessing administrative endpoints (`/admin/*`).

- **Ownership Rule:**
  - `case.created_by == current_user.id`
  - A screener sees exclusively cases they initiated. Requesting a case created by another screener returns **`404 Not Found`**.

- **Visibility Rules:**
  - Screeners view case status (`submitted`, `under_review`, `needs_retake`, `signed`, `referred`).
  - Once signed, screeners see the doctor's single next-step line (to guide community follow-up).
  - Screeners see referral status progression for their screened cohort.
  - Screeners **never** see raw AI prediction metrics, confidence values, heatmaps, or hospital referral packets.

- **Authorization Gates:**
  - **Gate 1 (Consent Gate):** `POST /cases/{id}/submit` strictly requires an active consent record for that profile's person, with `captured_by == current_user.id`.
  - **Gate 2 (Age Gate):** Profile must confirm person is age ≥ 18; under-18 profile creation is rejected.

---

### 2.3. Doctor (`doctor`)

*Licensed medical practitioners and dentists who review the triage queue, confirm or override AI predictions, sign clinical reports, conduct teleconsults, book hospital slots, and manage referrals.*

- **Allowed Resources & Actions (Verified Doctors Only):**
  - `GET /queue`: View triage review queue sorted by urgency (`urgent` < 4h, `soon` < 24h, `routine` < 48h). Includes assigned cases and unassigned pool.
  - `GET /cases/{id}`: Full clinical case viewer for assigned cases: photographs, anatomical sites, history, AI class, calibrated confidence, Grad-CAM attention heatmap, quality scores.
  - `POST /cases/{id}/claim`: Claim an unassigned case from the shared unassigned pool (assigns case to `current_user.id`).
  - `POST /cases/{id}/release`: Voluntarily release an assigned case back to `queued` with mandatory logged clinical reason.
  - `POST /cases/{id}/review`: Confirm or override AI triage prediction with mandatory structured clinical rationale.
  - `POST /cases/{id}/retake`: Request screener retake with specific feedback reason (transitions case to `needs_retake`).
  - `POST /cases/{id}/second-opinion`: Request second opinion from another verified doctor, or submit second-opinion comment on a requested case.
  - `POST /cases/{id}/sign`: Digitally sign clinical report, appending verified doctor's registration number, timestamp, and intended-use statement.
  - `GET /cases/{id}/timeline`: View clinical case state transition timeline and clinical audit history.
  - `GET /reports/{id}`: Download signed PDF report for assigned case.
  - `GET /hospitals/search`: Search hospital directory by facility tier, distance, specialty, and next available slot.
  - `POST /slots/{id}/hold`: Place a temporary 10-minute hold on a hospital biopsy/consult slot.
  - `POST /appointments`: Book a confirmed hospital appointment from a held slot.
  - `POST /referrals`: Issue hospital referral and attach generated clinical referral packet.
  - `GET /referrals`: View list of referrals originating from cases assigned to this doctor (`referral.referring_doctor_id == current_user.id`).
  - `GET /referrals/{id}`: View referral details and appointment status for own referred case.
  - `GET /referrals/{id}/packet`: View clinical referral packet for own referred case.
  - `POST /consults/{id}/video-room`: Initiate teleconsultation room (audio/video) with patient.
  - `PUT /doctor/availability`: Configure daily review capacity and on-duty availability for automatic assignment engine.

- **Denied Resources & Actions:**
  - **DENIED:** Accessing clinical cases assigned to other doctors (`404 Not Found`).
  - **DENIED:** Accessing any clinical endpoint (`GET /queue`, `GET /cases/{id}`, claim, review, sign, refer) if `verification_status != "verified"` (**`403 Forbidden`**).
  - **DENIED:** Signing reports on cases where doctor is only a second-opinion reviewer (`POST /cases/{id}/sign` returns **`403 Forbidden`**; second opinion is comment-only).
  - **DENIED:** Claiming a case that is already assigned to another doctor (`404 Not Found` / `409 Conflict`).
  - **DENIED:** Cancelling screening cases (`POST /cases/{id}/cancel` returns **`403 Forbidden`**; doctors cannot cancel cases).
  - **DENIED:** Viewing hospital referral inboxes or specialist capacity schedules belonging to partner hospitals (owned by Hospital Coordinator).
  - **DENIED:** Viewing or inspecting raw system audit log collection (`GET /admin/audit-logs`) or admin analytics (`/admin/*`).

- **Ownership & Case Allocation Rules:**
  - **Default Workflow:** Per SPEC section 7, **automatic case assignment by availability and capacity is the default**.
  - **Assigned Case Visibility:** Doctor sees full clinical data (photos, history, AI class, confidence, heatmap) if:
    - `case.assigned_doctor_id == current_user.id` (primary assignee), OR
    - `case.second_opinion_doctor_id == current_user.id` (view and comment only; signing is strictly blocked).
  - **Unassigned Pool Visibility:** Cases that cannot be immediately auto-assigned appear in the unassigned pool:
    - Unassigned pool items show **metadata only**: case reference ID, patient age, urgency tier, waiting time, and anatomical lesion sites.
    - **No photographs and no medical history** are disclosed in the unassigned pool until a verified doctor claims the case (`POST /cases/{id}/claim`).
  - **Anti-Probing Rule:** Requesting a case assigned to a different doctor returns **`404 Not Found`**.

- **Authorization Gates:**
  - **Gate 1 (2FA):** Mandatory TOTP authentication. Unenrolled doctors are restricted to `/2fa/setup`.
  - **Gate 2 (Clinical Verification Gate):** `current_user.verification_status == "verified"`.
    - Verification applies to **ALL clinical endpoints**: `GET /queue`, `GET /cases/{id}`, claim, review, retake, sign, refer, hold, book, and teleconsult.
    - Unverified doctors (`pending` or `rejected`) can log in but see exclusively a notice that verification is pending.
    - Gate 2 is evaluated *after* resource ownership (Gate 1), ensuring non-owned records return `404 Not Found` to unverified doctors.

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
  - `GET /referrals/{id}/packet`: View read-only clinical referral packet (oral photos, AI model version, history, doctor review notes). Every packet access is logged in `audit_log`.
  - `PATCH /referrals/{id}/status`: Accept referral, reschedule, or decline with mandatory clinical decline reason (enables doctor re-referral).
  - `POST /appointments/{id}/attendance`: Record patient attendance (`attended` or `no_show`).
  - `POST /appointments/{id}/outcome`: Record biopsy confirmation outcome and histopathology staging.

- **Denied Resources & Actions:**
  - **DENIED:** Accessing referrals, slots, schedules, or packets belonging to any other hospital (`404 Not Found`).
  - **DENIED:** Accessing cases or patients who have not been referred to coordinator's hospital (`404 Not Found`).
  - **DENIED:** Cancelling screening cases (`POST /cases/{id}/cancel` returns **`403 Forbidden`**; coordinators cannot cancel cases).
  - **DENIED:** Viewing the doctor clinical review queue (`GET /queue`) (`403 Forbidden`).
  - **DENIED:** Confirming/overriding AI classifications or signing screening reports.
  - **DENIED:** User administration, hospital creation, or system analytics (`/admin/*`).

- **Ownership Rule:**
  - Strictly single-facility: `referral.hospital_id == current_user.hospital_id` and `hospital.id == current_user.hospital_id`.
  - Accessing any referral, schedule, or case packet belonging to another hospital facility returns **`404 Not Found`**.

- **Authorization Gates:**
  - Account provisioned by an administrator and linked to exactly one active hospital ID (`user.hospital_id`).

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
  - `POST /admin/users/{id}/deactivate`: Deactivate accounts (takes effect immediately on next request). Staff accounts are deactivated, **never purged**.
  - `GET /admin/analytics`: View aggregate screening counts, SLA turnaround times, and model override category counts.
  - `GET /admin/audit-logs`: Inspect immutable structural system audit trail (`audit_log`).
  - `POST /admin/reset-demo`: Reset demonstration test data (disabled in production).

- **Denied Resources & Actions:**
  - **STRICT PROHIBITION — CLINICAL PRIVACY BLIND:**
    - Administrator **NEVER** views patient clinical oral photographs (`/cases/{id}/images`).
    - Administrator **NEVER** views patient questionnaire history answers.
    - Administrator **NEVER** views clinical referral packets (`/referrals/{id}/packet`).
    - Administrator **NEVER** overrides AI classifications or signs clinical reports.
    - Administrator **NEVER** issues medical referrals, books hospital slots, or alters biopsy outcomes.
    - Administrator **NEVER** cancels clinical cases.
    - Any attempt by an admin to access clinical inspection endpoints returns **`403 Forbidden`**.
  - **Self-Deactivation Guard:** Administrator cannot deactivate their own account (`errors.cannot_deactivate_self`).

- **Ownership & Scope Rule:**
  - Global administrative scope over system infrastructure, staff accounts, facility onboarding, and structural audit events.
  - **Zero access** to patient health information (PHI), medical photographs, or free-text diagnostic notes.

- **Authorization Gates:**
  - **Gate 1 (2FA):** Mandatory TOTP authentication; unenrolled admins are restricted strictly to `/2fa/setup`.

---

## 3. Permissions Matrix Summary

| Resource / Endpoint | Patient | Screener | Doctor (Verified) | Doctor (Unverified) | Coordinator | Admin |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| `POST /auth/register` (Patient self-registration) | Allowed | Denied (403) | Denied (403) | Denied (403) | Denied (403) | Denied (403) |
| `POST /admin/users` (Provision staff users) | Denied (403) | Denied (403) | Denied (403) | Denied (403) | Denied (403) | Allowed |
| `POST /admin/doctors/{id}/verify` (Doctor verification) | Denied (403) | Denied (403) | Denied (403) | Denied (403) | Denied (403) | Allowed |
| `POST /admin/hospitals` (Create hospital) | Denied (403) | Denied (403) | Denied (403) | Denied (403) | Denied (403) | Allowed |
| `PATCH /admin/users/{id}/hospital` (Link coordinator) | Denied (403) | Denied (403) | Denied (403) | Denied (403) | Denied (403) | Allowed |
| `DELETE /me/data` (Right to be forgotten) | Own Profile | Denied (403) | Denied (403) | Denied (403) | Denied (403) | Denied (403) |
| `POST /cases` (Create screening case) | Own Profile | Allowed | Denied (403) | Denied (403) | Denied (403) | Denied (403) |
| `POST /cases/{id}/images` (Upload photos) | Own Profile | Own Case | Denied (403) | Denied (403) | Denied (403) | Denied (403) |
| `POST /cases/{id}/history` (Submit history) | Own Profile | Own Case | Denied (403) | Denied (403) | Denied (403) | Denied (403) |
| `POST /cases/{id}/submit` (Submit for triage) | Own Profile | Own Case (Consent Gated) | Denied (403) | Denied (403) | Denied (403) | Denied (403) |
| `POST /cases/{id}/cancel` (Cancel before signing) | Own Profile | Own Case | Denied (403) | Denied (403) | Denied (403) | Denied (403) |
| `GET /queue` (Clinical review queue) | Denied (403) | Denied (403) | Allowed (Pool/Assign) | **Denied (403)** | Denied (403) | Denied (403) |
| `GET /cases/{id}` (Clinical viewer / status) | Status Only (Own) | Status/Next-step (Own) | Assigned only | **Denied (403)** | Denied (403) | **Denied (403)** |
| `POST /cases/{id}/claim` (Claim unassigned case)| Denied (403) | Denied (403) | Pool only | **Denied (403)** | Denied (403) | Denied (403) |
| `POST /cases/{id}/release` (Release to queue) | Denied (403) | Denied (403) | Assigned only | **Denied (403)** | Denied (403) | Denied (403) |
| `POST /cases/{id}/review` (Confirm/override AI) | Denied (403) | Denied (403) | Assigned only | **Denied (403)** | Denied (403) | Denied (403) |
| `POST /cases/{id}/second-opinion` (2nd opinion) | Denied (403) | Denied (403) | Allowed (Comment only)| **Denied (403)** | Denied (403) | Denied (403) |
| `POST /cases/{id}/sign` (Sign clinical report) | Denied (403) | Denied (403) | Assigned only | **Denied (403)** | Denied (403) | Denied (403) |
| `GET /cases/{id}/timeline` (Status timeline) | Denied (403) | Denied (403) | Assigned only | **Denied (403)** | Denied (403) | Denied (403) |
| `GET /reports/{id}` (Download signed PDF) | Own Profile (Signed) | Denied (403) | Assigned only | **Denied (403)** | Denied (403) | Denied (403) |
| `POST /slots/{id}/hold` (Hold hospital slot) | Denied (403) | Denied (403) | Allowed | **Denied (403)** | Denied (403) | Denied (403) |
| `POST /appointments` (Book from held slot) | Denied (403) | Denied (403) | Allowed | **Denied (403)** | Denied (403) | Denied (403) |
| `POST /appointments/{id}/confirm` (Confirm apt) | Own Profile | Denied (403) | Denied (403) | Denied (403) | Denied (403) | Denied (403) |
| `POST /appointments/{id}/cancel` (Cancel apt) | Own Profile | Denied (403) | Denied (403) | Denied (403) | Denied (403) | Denied (403) |
| `POST /appointments/{id}/reschedule-request` | Own Profile | Denied (403) | Denied (403) | Denied (403) | Denied (403) | Denied (403) |
| `POST /referrals` (Refer to hospital) | Denied (403) | Denied (403) | Assigned only | **Denied (403)** | Denied (403) | Denied (403) |
| `GET /referrals` (Referral inbox / list) | Denied (403) | Own Cohort (Status) | Own Cases only | **Denied (403)** | Own Hospital only | Denied (403) |
| `GET /referrals/{id}/packet` (Referral packet) | Own Profile | Denied (403) | Own Cases only | **Denied (403)** | Own Hospital only | **Denied (403)** |
| `PATCH /referrals/{id}/status` (Accept/decline)| Denied (403) | Denied (403) | Denied (403) | Denied (403) | Own Hospital only | Denied (403) |
| `POST /appointments/{id}/attendance` (Attendance)| Denied (403) | Denied (403) | Denied (403) | Denied (403) | Own Hospital only | Denied (403) |
| `POST /appointments/{id}/outcome` (Biopsy outcome)| Denied (403) | Denied (403) | Denied (403) | Denied (403) | Own Hospital only | Denied (403) |
| `GET /admin/audit-logs` (Audit compliance log) | Denied (403) | Denied (403) | Denied (403) | Denied (403) | Denied (403) | Allowed |
| `GET /admin/analytics` (Aggregated statistics) | Denied (403) | Denied (403) | Denied (403) | Denied (403) | Denied (403) | Allowed |

---

## 4. Final Architecture & Permissions Decisions

The following architectural, clinical, and security decisions are finalized for the ONCOLINK platform:

1. **Doctor Case Release & Reassignment (`Resolved`):**
   - **Decision:** Yes, an assigned doctor may voluntarily release a claimed case back to the `queued` state. A mandatory reason must be supplied, which is recorded in the case's transition record and audited.
   - **SLA Invariant:** Automatic SLA re-assignment timers (SPEC section 7: urgent < 4h, soon < 24h, routine < 48h) remain active concurrently.
2. **Screener Visibility & Community Camps (`Resolved`):**
   - **Decision:** No shared visibility across screeners. Each field screener sees exclusively cases they individually created (`case.created_by == current_user.id`).
   - **Roadmap:** Multi-screener camp-level shared queues and camp identifiers are deferred to future milestones.
3. **Minors, Guardianship & Age Enforcement (`Resolved`):**
   - **Decision:** Out of scope for this prototype. Self-screening and camp intake are strictly restricted to adults aged 18 and older; registration and profile creation for users under 18 is blocked and documented as a known platform limitation.
   - **Implementation Rule:** Adult-only enforcement requires an `age` or `date_of_birth` field on `patient_profiles`, enforced in the case task with unit and integration tests rejecting under-18 registrations and under-18 screener intakes.
4. **Hospital Coordinator Facility Boundary (`Resolved`):**
   - **Decision:** Strictly single-facility. One hospital coordinator account belongs to exactly one hospital facility (`user.hospital_id`). Multi-facility coordinator roles are prohibited.
5. **Case History & Clinician Audit Visibility (`Resolved`):**
   - **Decision:** Role-segregated visibility. Reviewing doctors see their case's clinical status timeline (`GET /cases/{id}/timeline`). Only administrators see the raw system audit log (`GET /admin/audit-logs`), and administrators never see clinical oral photographs or diagnostic notes.
6. **Patient Profiles & Unauthenticated Screened Individuals (`Resolved`):**
   - **Decision:** Cases belong to `patient_profile_id`, not user accounts. A self-registered patient automatically receives a profile linked to their `user_id`. Profiles created in the field by screeners have no login credentials (`user_id == null`). Linking a screener-created profile to a later self-registered account is recorded as future work.
7. **Screener Clinical Visibility Boundaries (`Resolved`):**
   - **Decision:** Screeners view case status, the doctor's next-step recommendation line from the signed report, and referral status for individuals they screened. Screeners **never** see raw AI details (class, confidence, heatmap) and **never** access clinical referral packets.
8. **Data Deletion & Right to be Forgotten (`Resolved`):**
   - **Decision:** `DELETE /me/data` purges oral images (GridFS), history questionnaire answers, and personal details from that person's cases; keeps anonymous metrics and ID-only audit entries; marks active referrals as `consent_withdrawn` and notifies recipient hospitals. Hospital-held copies are listed as a known platform limitation. Staff accounts are deactivated, never purged.
9. **Case Assignment Workflow & Pool Visibility (`Resolved`):**
   - **Decision:** Automatic case assignment by availability and capacity is the default per SPEC section 7. Doctors see full clinical data only for cases assigned to them (or assigned for second opinion). Unassigned cases appear in an unassigned pool displaying only reference ID, age, urgency, waiting time, and anatomical sites (no photos or history) until claimed by a verified doctor. Claiming applies exclusively to the unassigned pool.

---

## 5. Authorization Test Matrix

This matrix specifies the exact expected HTTP response status code for every platform endpoint across all caller roles and context variants. Every feature task must turn these specifications into automated integration tests.

### Status Code Invariants
- **`200` / `201` / `204`:** Successful authorized execution.
- **`401 Unauthorized`:** Unauthenticated request (missing, invalid, or expired session token).
- **`403 Forbidden`:** Wrong role; or unverified doctor attempting clinical access; or unauthorized state mutation (e.g. cancelling a signed case). Evaluated *before* database record lookup for wrong roles.
- **`404 Not Found`:** Right role, but record does not exist or caller is not the owner/creator/assignee. Evaluated *before* clinician verification status checks to prevent resource existence probing.

| Endpoint & Action | Unauth | Patient (Owner) | Patient (Other) | Screener (Creator) | Screener (Other) | Doctor (Assigned) | Doctor (Other) | Doctor (Unverified) | Coord (Own Hosp) | Coord (Other Hosp) | Admin |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `POST /auth/register` (Patient self-registration) | 201 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 |
| `POST /auth/login` (Step 1 password login) | 200 | 200 | 200 | 200 | 200 | 200 | 200 | 200 | 200 | 200 | 200 |
| `POST /auth/2fa/login` (Step 2 TOTP verification) | 401 | 401 | 401 | 401 | 401 | 200 | 200 | 200 | 401 | 401 | 200 |
| `POST /auth/2fa/setup` (Generate TOTP secret) | 401 | 401 | 401 | 401 | 401 | 401 | 401 | 200 (Temp) | 401 | 401 | 200 (Temp) |
| `POST /auth/2fa/verify-setup` (Confirm TOTP) | 401 | 401 | 401 | 401 | 401 | 401 | 401 | 200 (Temp) | 401 | 401 | 200 (Temp) |
| `GET /auth/me` (Current user profile & session) | 401 | 200 | 200 | 200 | 200 | 200 | 200 | 200 | 200 | 200 | 200 |
| `POST /auth/refresh` (Rotate refresh token) | 401 | 200 | 200 | 200 | 200 | 200 | 200 | 200 | 200 | 200 | 200 |
| `POST /auth/logout` (Revoke refresh session) | 401 | 200 | 200 | 200 | 200 | 200 | 200 | 200 | 200 | 200 | 200 |
| `GET /consent/current` (Current active consent) | 200 | 200 | 200 | 200 | 200 | 200 | 200 | 200 | 200 | 200 | 200 |
| `POST /consent` (Record informed consent) | 401 | 201 (Self) | 403 | 201 (In-person)| 403 | 403 | 403 | 403 | 403 | 403 | 403 |
| `DELETE /me/data` (Right to be forgotten) | 401 | 200 | 404 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 |
| `POST /cases` (Create screening case draft) | 401 | 201 | 403 | 201 | 403 | 403 | 403 | 403 | 403 | 403 | 403 |
| `POST /cases/{id}/images` (Upload photographs) | 401 | 200 | 404 | 200 | 404 | 403 | 403 | 403 | 403 | 403 | 403 |
| `POST /cases/{id}/history` (Submit questionnaire) | 401 | 200 | 404 | 200 | 404 | 403 | 403 | 403 | 403 | 403 | 403 |
| `POST /cases/{id}/submit` (Submit for triage) | 401 | 200 | 404 | 200 | 404 | 403 | 403 | 403 | 403 | 403 | 403 |
| `POST /cases/{id}/cancel` (Cancel before signing)| 401 | 200 | 404 | 200 | 404 | 403 | 403 | 403 | 403 | 403 | 403 |
| `GET /cases` (List user-accessible cases) | 401 | 200 (Own) | 200 (Own) | 200 (Own) | 200 (Own) | 403 | 403 | 403 | 403 | 403 | 403 |
| `GET /cases/{id}` (Case viewer / status) | 401 | 200 (Status)| 404 | 200 (Status)| 404 | 200 (Full) | 404 | 403 (Own) / 404 | 403 | 403 | 403 |
| `GET /queue` (Clinical review queue) | 401 | 403 | 403 | 403 | 403 | 200 | 200 | 403 | 403 | 403 | 403 |
| `POST /cases/{id}/claim` (Claim unassigned case)| 401 | 403 | 403 | 403 | 403 | 200 (Pool) | 404 | 403 | 403 | 403 | 403 |
| `POST /cases/{id}/release` (Release to queue) | 401 | 403 | 403 | 403 | 403 | 200 | 404 | 403 | 403 | 403 | 403 |
| `POST /cases/{id}/review` (Confirm/override AI) | 401 | 403 | 403 | 403 | 403 | 200 | 404 | 403 | 403 | 403 | 403 |
| `POST /cases/{id}/retake` (Request photo retake) | 401 | 403 | 403 | 403 | 403 | 200 | 404 | 403 | 403 | 403 | 403 |
| `POST /cases/{id}/second-opinion` (2nd opinion) | 401 | 403 | 403 | 403 | 403 | 200 (Comment)| 404 | 403 | 403 | 403 | 403 |
| `POST /cases/{id}/sign` (Digitally sign report) | 401 | 403 | 403 | 403 | 403 | 200 | 404 | 403 | 403 | 403 | 403 |
| `GET /cases/{id}/timeline` (Status timeline) | 401 | 403 | 403 | 403 | 403 | 200 | 404 | 403 | 403 | 403 | 403 |
| `GET /reports/{id}` (Download signed PDF report) | 401 | 200 (Signed)| 404 | 403 | 403 | 200 | 404 | 403 | 403 | 403 | 403 |
| `GET /hospitals/search` (Search directory) | 401 | 403 | 403 | 403 | 403 | 200 | 200 | 403 | 403 | 403 | 403 |
| `POST /slots/{id}/hold` (Hold hospital slot) | 401 | 403 | 403 | 403 | 403 | 200 | 200 | 403 | 403 | 403 | 403 |
| `POST /appointments` (Book from held slot) | 401 | 403 | 403 | 403 | 403 | 200 | 200 | 403 | 403 | 403 | 403 |
| `POST /appointments/{id}/confirm` (Confirm apt) | 401 | 200 | 404 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 |
| `POST /appointments/{id}/cancel` (Cancel apt) | 401 | 200 | 404 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 |
| `POST /appointments/{id}/reschedule-request` | 401 | 200 | 404 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 |
| `POST /referrals` (Create hospital referral) | 401 | 403 | 403 | 403 | 403 | 201 | 404 | 403 | 403 | 403 | 403 |
| `GET /referrals` (Referral inbox / list) | 401 | 403 | 403 | 200 (Cohort) | 200 (Cohort)| 200 (Own) | 200 (Own) | 403 | 200 (Hosp) | 403 | 403 |
| `GET /referrals/{id}` (Referral details) | 401 | 200 | 404 | 200 (Cohort) | 404 | 200 | 404 | 403 | 200 | 404 | 403 |
| `GET /referrals/{id}/packet` (Clinical packet) | 401 | 200 | 404 | 403 | 403 | 200 | 404 | 403 | 200 | 404 | 403 |
| `PATCH /referrals/{id}/status` (Accept/decline)| 401 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 200 | 404 | 403 |
| `POST /appointments/{id}/attendance` | 401 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 200 | 404 | 403 |
| `POST /appointments/{id}/outcome` (Biopsy) | 401 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 200 | 404 | 403 |
| `POST /consults/{id}/video-room` (Teleconsult) | 401 | 200 | 404 | 403 | 403 | 200 | 404 | 403 | 403 | 403 | 403 |
| `GET /admin/users` (List user accounts) | 401 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 200 |
| `POST /admin/users` (Provision staff account) | 401 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 201 |
| `POST /admin/doctors/{id}/verify` (Verify doctor)| 401 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 200 |
| `POST /admin/hospitals` (Create hospital) | 401 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 201 |
| `PATCH /admin/users/{id}/hospital` (Link coord) | 401 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 200 |
| `POST /admin/users/{id}/deactivate` | 401 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 200 |
| `GET /admin/audit-logs` (System audit trail) | 401 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 200 |
| `GET /admin/analytics` (Aggregate metrics) | 401 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 200 |
