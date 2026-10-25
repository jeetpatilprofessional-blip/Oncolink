# ONCOLINK: Architecture & Domain Decisions

This document records authoritative technical and architectural decisions for the ONCOLINK codebase. Where specifications or guides might have ambiguity or historical variations, this document acts as the definitive tie-breaker.

## Decision 1: Oral Cavity Site Map Regions (7 Sites)

* **Decision:** The oral cavity has seven selectable sites:
  1. `left_cheek` (Left Cheek / Buccal Mucosa)
  2. `right_cheek` (Right Cheek / Buccal Mucosa)
  3. `tongue_top` (Tongue, Dorsum / Top)
  4. `tongue_sides` (Tongue, Lateral Borders / Sides)
  5. `floor_of_mouth` (Floor of Mouth)
  6. `hard_palate` (Hard Palate)
  7. `lips_and_gums` (Lips, Labial Mucosa & Gingiva)
* **Rationale:** While SPEC Section 5.3 grouped them as "tongue (top and sides)", DESIGN Section 6 and clinical examination protocols require differentiating the dorsum from the high-risk lateral borders. This file is the tie-breaker establishing seven distinct regions in data models, SVG diagrams, and capture flows.

## Decision 2: Urgency Tiers vs. AI Certainty

* **Decision:** Case urgency (`urgent`, `soon`, `routine`) is strictly separated from AI classification certainty (`uncertain`).
* **Rationale:** They are separate fields and separate enums in code. Urgency dictates clinical SLAs (e.g. 4 hours vs 24 hours vs 48 hours) and queue priority. Certainty is an AI/statistical property (confidence thresholding). Although the UI may display the uncertain marker shape (hollow square) to assist clinical triage, the data model preserves them as independent attributes.

## Decision 3: AI Prediction Classes vs. Biopsy Outcome Categories

* **Decision:** AI prediction classes and Biopsy outcome categories are implemented as separate, dedicated concepts.
  - **Version 1 AI Triage Classes (Docs Only):** `benign_appearing` and `suspicious_for_malignancy`, plus the `uncertain` output (below calibrated confidence threshold).
  - The class `potentially_malignant` (oral potentially malignant disorders / OPMD, such as leukoplakia, erythroplakia) is deferred as future work pending access to datasets with differentiated OPMD annotations (such as the SMART dataset).
  - Normal-mouth photos (healthy mucosa without visible lesions) are out of distribution; the model runs strictly on cases presenting a lesion close-up.
  - Kaggle 'non-cancer' and Mendeley 'benign' are assumed equivalent for version 1 training, and this equivalence is unverified.
  - **Biopsy Outcome Categories:** `benign`, `potentially_malignant`, `malignant`, `inconclusive`.
* **Rationale:** AI triage assists a doctor prior to clinical examination, whereas histopathological biopsy establishes definitive tissue diagnosis. Keeping these categories distinct prevents confusing screening hypotheses with histopathological truth. Restricting version 1 classes to `benign_appearing` and `suspicious_for_malignancy` prevents hallucinating OPMD subdivisions that the current binary training sets do not support.

## Decision 4: Dual-Stage Quality Feedback

* **Decision:** Pre-capture quality feedback (blur, lighting, framing guide) runs client-side on the device before the shutter is pressed, and the backend server runs its own automated quality check during the `quality_check` lifecycle state as the authoritative gate.
* **Rationale:** Immediate client-side feedback prevents screeners from taking poor photos and wasting bandwidth. The backend quality gate provides an objective, verifiable check on the uploaded full-resolution image before queuing for AI analysis.

## Decision 5: Real Database Only; Seeded Demo Data via Scripts

* **Decision:** Runtime application code connects only to a real database (MongoDB replica set) and real storage. Runtime code contains zero mock database or mock data fallbacks. If any connection is unreachable, the system fails loudly.
* **Rationale:** Mock fallbacks mask configuration errors and risk leaking fake clinical outputs into real workflows. Demonstrations and end-to-end tests use real MongoDB collections populated by explicit seeding scripts, with all seeded records clearly labeled as demonstration data (`is_demo: true`).

## Decision 6: Image Storage in MongoDB GridFS with StorageService Abstraction

* **Decision:** Clinical images are stored directly in MongoDB GridFS via a standardized `StorageService` interface (`save`, `open`, `delete`, `exists`), replacing external object storage (MinIO). Images are strictly private and served only through authenticated backend endpoints.
* **Rationale:**
  1. **Registry & Dependency Integrity:** MinIO removed community edition images from Docker Hub, leaving only unverified third-party forks. Storing images in MongoDB GridFS eliminates external unverified dependencies.
  2. **Atomic Consistency & Simplicity:** Keeping clinical images within the MongoDB replica set enables unified backups, disaster recovery, and consistent data lifecycle management alongside case records and audit logs.
  3. **Privacy & Security by Design:** Clinical mouth photographs must never be exposed via public S3 bucket URLs or pre-signed links. Serving images strictly through authenticated backend endpoints enforces role-based access control and comprehensive audit logging on every image view.
  4. **Modularity:** Encapsulating operations behind the `StorageService` interface ensures that if an institutional deployment requires enterprise S3 or Azure Blob Storage in the future, it can be swapped without touching API or domain logic.

## Decision 7: Role Provisioning and Clinical Verification Gateways

* **Decision:** The system strictly partitions account registration: participants self-register with role `patient`, whereas clinical and operational staff (`screener`, `doctor`, `hospital_coordinator`, `admin`) are provisioned exclusively by administrators. Medical doctors require a two-stage credentialing lifecycle: registration number recording followed by administrative status verification (`pending` -> `verified` or `rejected`).
* **Rationale:** Unverified actors must never have the authority to sign diagnostic consults or issue referral orders. The `require_verified_doctor` gateway enforces that unverified doctors are blocked from clinical sign-off routes.

## Decision 8: Session Security, Refresh Token Rotation, and Family-Wide Reuse Invalidation

* **Decision:** Access tokens are short-lived (15 minutes). Refresh tokens are opaque, stored in the database strictly as SHA-256 hashes, delivered in an `httpOnly`, `SameSite=Strict` cookie, and rotated on every request. Each refresh token belongs to a cryptographic `family_id`. If an already rotated token is replayed, the backend immediately revokes the entire family and triggers a security audit event (`refresh_reuse`).
* **Rationale:** Mobile devices in field screening camps and community health clinics operate over untrusted networks. Immediate rotation minimizes the window of token theft, while family-wide revocation immediately neutralizes intercepted tokens and forces re-authentication.

## Decision 9: Two-Factor Authentication (TOTP) and Encryption at Rest

* **Decision:** TOTP two-factor authentication is mandatory for doctors and administrators. Base32 TOTP secrets are encrypted at rest using AES-CBC/Fernet with a 32-byte key from the environment. Enrolment generates eight single-use recovery codes stored exclusively as SHA-256 hashes. Login is strictly two-step: password verification issues an ephemeral 5-minute intermediate token (`temp_token`), which must be exchanged with a valid TOTP code or recovery code.
* **Rationale:** Doctors sign legally binding clinical referral sheets and consult notes; administrators manage accounts and access logs. Requiring TOTP protects patient data from credential stuffing. Storing secrets encrypted at rest and recovery codes as hashes ensures that even a database dump does not compromise second factors.

## Decision 10: Append-Only Audit Trail Architecture

* **Decision:** The `AuditService` is backed by an append-only `audit_log` MongoDB collection and strictly exposes insert and read methods, purposefully exposing zero update, modify, or delete methods. The service enforces recursive credential scrubbing before writing.
* **Rationale:** Regulatory compliance and clinical traceability require an immutable audit trail of views, transitions, credential changes, and security events. Preventing mutation at the service interface level guarantees that audit records cannot be altered or purged by application bugs.

## Decision 11: Versioned Participant Informed Consent

* **Decision:** Patient self-registration requires explicit acceptance of the current active versioned consent text. The backend verifies the submitted version against the current file-backed text, records an immutable consent record in `consents` with the canonical text SHA-256 hash, and exposes `GET /consent/current` publicly.
* **Rationale:** In an academic research prototype involving human oral photography, participant autonomy and compliance with ethical standards require that consent is fully verifiable, version-tracked, and retrievable in plain language without ambiguity.


## Decision 12: In-Memory Access Tokens & Zero Web Storage Persistence

* **Decision:** The JWT access token resides strictly in JavaScript application memory (`frontend/src/api/client.ts`), never written to `localStorage`, `sessionStorage`, or any JavaScript-readable cookie. Session persistence and renewal are handled via an `httpOnly`, `SameSite=Strict` refresh cookie using a single-flight mutex (`performSingleFlightRefresh`). When an API request encounters a 401, concurrent requests await the in-flight refresh promise and retry once upon success. If refresh fails, in-memory state is cleared and the user is redirected to `/login`.
* **Rationale:** Web storage (`localStorage`/`sessionStorage`) is vulnerable to cross-site scripting (XSS) extraction. Keeping access tokens exclusively in memory while delegating persistence to `httpOnly` SameSite=Strict cookies ensures sensitive clinical credentials cannot be read by malicious scripts. Single-flight queuing prevents race conditions and redundant refresh operations under parallel requests.

## Decision 13: Local Client-Side QR Code Generation for Two-Factor Enrollment

* **Decision:** TOTP setup QR codes are generated directly in the browser as pure SVG markup using the client-side `qrcode` library. Secrets, email addresses, and `otpauth://` URIs are never sent to external chart services or third-party image generation APIs.
* **Rationale:** Using third-party image generation services (e.g., Google Chart API) leaks cryptographic 2FA seeds and user identities over external networks. Generating SVGs client-side maintains complete data sovereignty and ensures high security in hospital networks.

## Decision 14: Case Foundation, State Machine Transaction Isolation, and Privacy Boundaries

* **Decision:**
  1. **Participant Identity Architecture:** Cases reference `patient_id` from the dedicated `patients` collection, completely decoupling clinical records from authenticated login credentials. Self-registered patients receive an automatically provisioned `patients` record linked to their `user_id`. Field screeners create unauthenticated `patients` records with `user_id = null`. A unique sparse index on `user_id` with `partialFilterExpression={"user_id": {"$type": "string"}}` prevents duplicate accounts while permitting unlimited unauthenticated field profiles.
  2. **Adult-Only Intake:** Patient self-registration and screener intake strictly enforce adult age (`age >= 18`) via date of birth validation (`AdultDateOfBirth`), blocking minors at the API boundary per SPEC section 5.1.
  3. **State Machine Invariant & Transaction Isolation:** All case state changes are executed exclusively through the authoritative state machine service (`app.services.state_machine.transition`). No other component in the codebase may write or update a case status. Transitions execute within a single atomic MongoDB multi-document transaction with optimistic concurrency control via an incrementing integer `version` counter. A stale write immediately aborts with `409 Conflict`.
  4. **Privacy Partitioning in Audit Logs vs Case History:** The `transition()` function appends a `status_history` entry to the case document containing transition metadata and clinical notes (`reason_text`). Simultaneously, an immutable audit event is written to `audit_log` with structural IDs and authoritative `reason_code` values ONLY. Free-text clinical notes (`reason_text`) are strictly prohibited from entering `audit_log`, ensuring administrative audit queries never expose sensitive clinical rationale or diagnostic narratives.
  5. **Urgency Decoupling:** Review urgency (`urgent`, `soon`, `routine`) is decoupled from AI model prediction certainty. Review turnaround SLAs are driven by urgency, while calibrated confidence remains an orthogonal diagnostic metric.
  6. **Role-Scoped Projections & Pool Access:** Case viewing (`GET /cases/{id}`) returns role-tailored projections:
     - Patients and screeners receive status-only views (`CaseStatusResponse`).
     - Verified doctors viewing unassigned pool cases (`queued`, `ai_analyzed`) receive metadata-only views (`CasePoolMetadataResponse` with reference, age band, urgency, wait time, sites; no photos, no questionnaire answers).
     - Assigned and second-opinion doctors receive full clinical details (`CaseDetailResponse`).
     - Administrators and hospital coordinators receive `403 Forbidden` (clinical isolation boundary).
     - Wrong ownership or non-assigned doctors probing claimed cases receive `404 Not Found` (anti-probing invariant).
  7. **Claim/Release Invariants & AI Step Fallback Guarantees (Guidance for AI Task):**
     - Case claiming (`POST /cases/{id}/claim`) is allowed **strictly and exclusively from `ai_analyzed`** when no clinician is assigned (`assigned_doctor_id == null`). Claiming from any other state (including `queued`) returns `409 Conflict`.
     - Voluntary release (`POST /cases/{id}/release`) transitions `under_review -> ai_analyzed`, unassigning the doctor and returning the case to the claimable pool while preserving the existing AI inference output.
     - **Requirement for the AI task:** The AI pipeline step (`queued -> ai_analyzed`) must always advance the case to `ai_analyzed`, even when model inference fails, times out, or errors out. In failure scenarios, an `ai_status` of `'unavailable'` (or `'completed'` on success) must be stored on the case document. This guarantees cases are never stranded in `queued` and clinicians can always claim and triage them manually.

## Decision 15: Screening Intake Architecture, Photographic Sanitization, and Submission Pipeline

* **Decision:**
  1. **Strictly Structured History:** The questionnaire (`POST /cases/{id}/history`) permits zero free-text fields and rejects unknown attributes (`extra="forbid"`). Answers are persisted in the dedicated `case_history` collection.
  2. **Rule-Based Emergency Triage & Urgency:** Red-flag detection (`evaluate_red_flags`) is a deterministic pure function operating strictly on history inputs, completely independent of AI inference. The urgency engine (`determine_urgency`) establishes initial review priority: any red flag assigns `Urgency.URGENT` (< 4h SLA); otherwise `Urgency.ROUTINE` (< 48h SLA). Informational risk flags (age 30–65, tobacco/areca nut exposure) are tracked orthogonally without impacting urgency.
  3. **Multi-Stage Photographic Sanitization:** Clinical uploads (`POST /cases/{id}/images`) undergo rigorous defense-in-depth:
     - Format validation by file magic bytes only (JPEG, PNG, WebP), rejecting extension-based spoofing.
     - Payload cap of 10 MB and Pillow decompression bomb mitigation (25 megapixel ceiling).
     - Deterministic decode and re-encode with Pillow, dropping all EXIF metadata (GPS coordinates, device serial numbers) and any trailing appended byte payloads.
     - Storage in MongoDB GridFS with randomized identifiers and SHA-256 integrity hashes.
     - Case quota of 12 images; duplicate uploads for the same `(site, view_type)` automatically supersede the prior capture and purge old GridFS chunks.
  4. **Dual-Use Quality Gate:** The quality evaluation engine (`evaluate_image_quality`) operates advisory at upload and authoritative at submission. It inspects blur (Laplacian variance on standardized 512x512 grayscale copies), exposure (mean luminance and fractions of crushed shadows/blown highlights), minimum resolution (480x480), and texture detail. Failures return translation keys (e.g. `too_blurry`, `too_dark`, `too_bright`, `too_small`, `low_detail`) for client-side localization.
  5. **Atomic Chained Submission Pipeline:** `POST /cases/{id}/submit` verifies preconditions (active consent, saved history, photographic protocol coverage: >=1 closeup and >=2 context views), returning 422 with a specific `missing_items` array on failure. The submission executes atomically via `transition_chain` in ONE single MongoDB transaction (`submitted -> quality_check -> [red_flag | needs_retake | queued]`), recording one status history entry and one structural audit entry per transition edge.

## Decision 16: Screening Frontend Architecture: Accessible Site Mapping, Advisory Video Telemetry, and Screener Intake

* **Decision:**
  1. **Accessible `OralSiteMap` Signature Component:** The 7 anatomical oral cavity regions are rendered as an accessible SVG with 3 discrete visual states: `not_captured` (outline only), `captured` (low-opacity tint + checkmark icon), and `rejected` (45-degree hatched pattern + cross icon), strictly pairing color with shape and text per DESIGN.md section 6. Supports full keyboard navigation (arrow keys cycle through regions, Enter/Space selects), touch operation, readability down to 320px viewport, and an accessible semantic HTML `<ol>` list alternative for screen readers (`aria-label`, `aria-pressed`, `aria-current`). Region names are externalized in `locales/en.json` and marked for clinical review.
  2. **Advisory Capture Pipeline & Shutter Invariant:** Image capture utilizes `navigator.mediaDevices.getUserMedia` with automatic fallback to `<input type="file" capture="environment">` when media devices or permissions are unavailable. A live telemetry loop evaluates frames via an offscreen canvas (Laplacian variance for blur estimation, mean pixel luminance for lighting), displaying real-time text + shape status markers. **Non-blocking shutter invariant:** advisory feedback never disables or delays the shutter button; the server quality gate remains authoritative. Client-side canvas compression downscales images to a maximum of 1600px on the longest dimension before upload. Skeleton placeholders are used during upload/evaluation (no spinning loaders).
  3. **Questionnaire & Immediate Red-Flag Notice:** All SPEC 5.2 fields are rendered using design system `Field` and semantic select/radio components, with the three emergency red-flag questions positioned first in plain language. Checking any red flag immediately renders the high-contrast emergency `Banner` ("Seek in-person medical care now") to guide participants to immediate emergency medical care without waiting for submission or doctor review.
  4. **Field Screener Intake & In-Person Consent:** Community screeners can register unauthenticated participants (`user_id = null`) through a dedicated two-step intake flow. Step 1 validates date of birth client-side, blocking participants under 18 with a localized error message without making any network calls. Step 2 presents the research consent agreement and records `captured_by = screener.id` via `POST /consent` before initializing the case draft. A session ledger table displays all cases screened during the session with live status markers.
  5. **Review Preconditions & Retake Flow:** The review screen renders a dynamic preconditions checklist matching the backend's 422 `missing_items` list (`active_consent`, `case_history`, `lesion_closeup_image`, `context_images`). Post-submission, emergency alerts are displayed for red-flag cases, and any photos failing the authoritative quality gate are listed with their localized reason codes and a direct "Retake photo" action returning to the capture flow.
  6. **Design System & Accessibility Standards:** All user-facing text is localized in `locales/en.json`. Monospace font families are prohibited for labels and data values (reserved only for technical diagnostics). Triage colors are reserved exclusively for clinical urgency. All interactive elements respect `prefers-reduced-motion` (the only animation is the subtle 150ms site map region fill transition). Automated axe-core checks confirm zero accessibility violations across all screens.

## Decision 17: Dataset Splitting Limitations & Duplicate Leakage Control

* **Decision:**
  1. **Absence of Patient Identifiers:** Rigorous programmatic search across raw files and directory hierarchies of both training datasets (`mendeley_karnataka` and `kaggle_oral_cancer`) confirms that zero patient or case identifiers exist in the source data.
  2. **Removal of Patient-Isolated Splits Assumption:** The previous assumption of strict patient-level / patient-isolated splitting is retracted as impossible with the current datasets.
  3. **Near-Duplicate Group Grouping Invariant:** Exact and near-duplicate image groups (identified by perceptual hashing / pHash) must always be assigned together to a single partition (train, validation, or test). Under no circumstances may duplicate or near-duplicate variants of an image be split across training and evaluation splits.
  4. **Optimistic Evaluation Caveat:** Because different lesion photos from the same patient may exist in the raw datasets without matching perceptual hashes, cross-validation and test set performance metrics may still be optimistic despite duplicate grouping. All reported metrics must explicitly note this limitation.

## Decision 18: Quality Gate Calibration & Consent Limitations

* **Decision:**
  1. **Anatomical Non-Verification Limitation:** The automated photographic quality gate measures sharpness (Laplacian variance), exposure (mean luminance and highlight/shadow pixel fractions), resolution (minimum width/height), and texture entropy only. It cannot confirm that an oral cavity, mouth, or lesion is actually present in the capture (for example, a high-contrast synthetic checkerboard test pattern passes all quality checks).
  2. **Heuristic Calibration Caveat:** The current quality gate thresholds (`BLUR_LAPLACIAN_VAR_MIN = 100.0`, `BRIGHTNESS_MEAN_MIN = 40.0`, `BRIGHTNESS_MEAN_MAX = 220.0`, `DETAIL_STD_DEV_MIN = 20.0`, etc.) are untuned engineering heuristics designed for prototype integrity. They require rigorous empirical calibration against real-world clinical smartphone photography across varied lighting and device camera sensors before operational deployment.
  3. **English-Only Consent Constraint:** Informed consent text (`backend/app/consent_texts/v1.txt`) is currently authored exclusively in English. Prior to any live field screening deployment, the consent disclosure must be professionally translated into local regional languages (e.g. Hindi, Marathi, Kannada) and vetted by institutional ethics review boards (IRB/IEC).



