# ONCOLINK: Final Project Specification

*College portfolio research prototype. Version 2, consolidated after comparison with real-world oral cancer screening programs. Not a medical device.*

## 1. Purpose and intended use

ONCOLINK moves a person with a suspicious mouth lesion from 'something looks wrong' to 'a specialist has examined it'. A screener or patient captures photos and history, an AI model triages them, a doctor reviews and signs, and the case is referred to the right level of hospital and tracked until a biopsy outcome is recorded.

**Intended use statement (show in the app, every report, and the README):** ONCOLINK is a research and education prototype. It is not a medical device, does not diagnose cancer, and must not be used for clinical decisions. Only a biopsy can confirm oral cancer. All data comes from public datasets and consenting volunteers.

## 2. What changed from the earlier plan

| Change | Reason |
|---|---|
| New **Screener** role (health worker or camp volunteer) | Real programs use trained screeners, and patient selfies give weaker images |
| **Multi-site capture protocol** instead of one photo | Field studies capture standardized views of the mouth |
| **Tiered hospitals** (community centre, district hospital, cancer centre) | The real referral ladder; district hospitals do first-line confirmation and biopsy |
| **Lost-to-follow-up** tracking and missed-referral alerts | Screening only works if positives are followed up |
| Label classes now include **potentially malignant** lesions | Screening targets premalignant disorders, not only cancer |
| **Honest evaluation**: locked model, internal vs outside-image results | Field accuracy is lower than curated-dataset accuracy |
| **Intended-use statement and regulatory mapping** | India's medical device software guidance and ICMR AI ethics principles |
| **Structured tobacco/areca history**, age and risk eligibility flag | Programs target high-risk adults, roughly 30 to 65 |
| **Case lifecycle state machine**, red-flag path, retake, doctor SLAs | Completes the exception paths |
| Dropped: payments, ABDM integration, offline mode, federated learning, extra languages | Low value for a portfolio until the core is real; listed under future work |

## 3. Roles

| Role | Responsibilities |
|---|---|
| **Patient** | Gives consent, optionally self-screens, receives reports, joins consults, tracks referral, can delete data |
| **Screener** | Screens many people per session using the capture protocol, enters history, submits cases, follows up on referred people |
| **Doctor** | Reviews queue, confirms or overrides AI, requests retakes, signs reports, consults by video or phone, refers to hospitals |
| **Hospital coordinator** | Manages specialists and slots, accepts or declines referrals, records attendance and outcomes |
| **Admin** | Verifies doctors and hospitals, manages users, views analytics, resets demo data |

## 4. Case lifecycle (state machine)

The backend enforces these transitions. Illegal jumps are rejected, and every transition is written to the audit log with actor, time, and reason.

```
draft -> submitted -> quality_check
quality_check -> needs_retake -> submitted      (photo rejected or doctor asked for retake)
quality_check -> queued -> ai_analyzed -> under_review
under_review -> uncertain_needs_inperson        (AI or doctor cannot assess)
under_review -> signed
signed -> closed_monitor                        (benign, re-screen reminder set)
signed -> referred -> referral_pending -> confirmed -> attended -> outcome_recorded -> closed
referral_pending -> declined_by_hospital -> referred   (re-refer to another hospital)
confirmed -> no_show -> outreach -> lost_to_followup
any state -> cancelled | consent_withdrawn
red_flag (emergency) is entered from submitted and jumps to the top of the queue
```

**Rules**
- Only a verified doctor can move a case to `signed`.
- Only a hospital coordinator can set `attended` and `outcome_recorded`.
- Red-flag detection is rule-based on the questionnaire, never left to the AI alone.

## 5. Screening module

**5.1 Eligibility and consent.** Adults only, with a guardian field for minors in the future-work list. Flag the 30 to 65 age band and tobacco or areca users as high risk. Store a consent record: version, language, timestamp, and who captured it.

**5.2 Structured history.**
- Tobacco: smoked, smokeless, areca nut, betel quid; frequency and years of use
- Alcohol: frequency
- Lesion: duration, pain, non-healing for more than two weeks, bleeding, white or red patch, lump
- Function: difficulty swallowing, opening the mouth, or speaking; unexplained weight loss
- Family history of cancer

**5.3 Capture protocol.** Required: one lesion close-up plus at least two context views. Full set: left cheek, right cheek, tongue (top and sides), floor of mouth, hard palate, lips and gums. The screener or patient selects the site for each photo; this becomes the recorded affected region, not a hardcoded guess.

**5.4 Quality gate.** Automatic checks for blur, brightness, and framing (mouth visible, lesion in frame). Failures return a specific retake instruction. Doctors can also request a retake with a reason, which pauses the case.

**5.5 Red-flag path.** Heavy bleeding, difficulty breathing or swallowing, or rapid swelling triggers an immediate 'seek in-person care now' screen, places the case at the top of the queue, and alerts the on-duty doctor.

## 6. AI module

- **Task:** image triage to assist a doctor, not diagnosis.
- **Classes:** normal or benign; potentially malignant (for example leukoplakia, erythroplakia); suspicious for cancer; plus an **uncertain** output. Support only the classes your datasets actually cover and document the rest as unsupported.
- **Model:** EfficientNet-B0 transfer learning as the baseline. Add ViT-B16 only as a measured comparison; do not claim it is better unless the numbers show it.
- **Data:** clinical photographs of the mouth only. Histopathology slide datasets do not match phone-photo input. Split by patient so no patient appears in both training and test sets. Set the test set aside before tuning and do not touch it until the end.
- **Uncertainty:** calibrate confidence (temperature scaling) and return 'uncertain, needs in-person exam' below a chosen threshold.
- **Explainability:** Grad-CAM from the trained model's real layers (attention rollout for ViT). Label heatmaps as 'where the model looked', not 'where the cancer is'.
- **Evaluation:** sensitivity (the priority metric), specificity, PPV, NPV, confusion matrix, ROC and AUC, calibration plot, and per-subgroup results (lighting, phone camera). Report **internal test results and outside-image results separately**, expecting the second to be lower.
- **Model locking:** freeze and hash the model version before final testing. Every AI result stores `model_version`, input hash, and timestamp.
- **Clinician agreement:** have a dentist or doctor review 30 to 50 test cases and report agreement (Cohen's kappa) with the model.
- **Retraining:** manual and offline only, always producing a new version. Never automatic.

## 7. Doctor workspace

- Queue sorted by urgency, then waiting time; red-flag cases pinned to the top
- Case viewer: all photos, history, AI class, confidence, heatmap, quality notes
- Confirm or override the AI with a required reason (feeds the analytics)
- Request retake, request second opinion from a colleague, add consult notes
- Sign-off with the doctor's registration number printed on the report
- Refer to hospital; start video, audio, or phone consult
- Availability and capacity settings; automatic case assignment
- **Time targets:** urgent within 4 hours, soon within 24, routine within 48. Overdue cases reassign automatically and alert the admin.

## 8. Referral and hospital module

**Hospital tiers:** primary or community health centre; district hospital; regional cancer centre. The doctor refers to the nearest tier able to do a biopsy first, and escalates to a cancer centre if the case needs it or the lower tier declines.

**Doctor side:** search by tier, specialty, distance, and next available slot; book, reschedule, or cancel; see referral status at every step.

**Hospital portal:** profile and departments, specialist schedules with blocked dates and daily capacity, referral inbox sorted by urgency, accept, reschedule or decline with a reason, read-only case packet limited to referred patients, attendance and outcome entry.

**Slot engine:** weekly schedules generate slots; selecting a slot places a 10-minute hold; a unique database constraint prevents two bookings for one slot; expired holds release automatically.

**Referral packet:** one-page PDF (photos, AI result with model version, history, doctor notes, urgency) that the patient can also carry. Every packet view is logged.

**Outcome record:** attended or not, biopsy done, result category (benign, potentially malignant, malignant, inconclusive), optional treatment-started flag.

## 9. Follow-up and compliance tracking

- Reminders 24 hours and 2 hours before appointments
- **Missed-referral alert:** urgent cases with no confirmed appointment after 3 days, others after 7
- No-show sequence: reminder, outreach by screener or phone, then `lost_to_followup` after a set number of attempts
- Benign path: advice, a re-screen reminder at a chosen interval, and a **lesion timeline** comparing photos over time
- One-tap patient feedback after a consult or referral
- Biopsy outcomes are compared against the AI's prediction and shown on the evaluation page

## 10. Communication layer

| Channel | Use | Notes |
|---|---|---|
| **WhatsApp (Cloud API)** | Opt-in, reminders, 'report ready' and 'appointment update' nudges | Notification only; no diagnosis, no photos, no words like cancer or oncology; STOP keyword; webhook signature check; fall back to SMS or email on failure |
| **In-app video** | Main consult | Daily or LiveKit free tier; rooms created by backend; short-lived tokens for the booked pair only; no recording by default |
| **In-app audio** | Weak-connection fallback | Same SDK, audio only |
| **Phone call** | Patients without smartphones | Masked click-to-call through an Indian telephony provider; stretch goal, otherwise documented design only |

Every call screen shows an emergency banner and the doctor's registration number. Only metadata (who, when, duration) is logged. The reason for keeping WhatsApp content-free is Meta's messaging policy on health information; have it reviewed before any real launch.

**Notification matrix**

| Event | Notified | Channel | Content rule |
|---|---|---|---|
| Case submitted | Patient | In-app, WhatsApp | 'We received your submission' |
| Retake needed | Patient or screener | In-app, WhatsApp | 'Action needed, open the app' |
| Red flag | On-duty doctor | In-app, SMS | Case ID only |
| Report signed | Patient | In-app, WhatsApp | 'Your report is ready' |
| Referral sent | Hospital | Portal | Full packet inside portal |
| Appointment confirmed or changed | Patient, doctor | In-app, WhatsApp | 'Appointment update' |
| Reminder | Patient | WhatsApp | Date and time only |
| Referral declined | Doctor | In-app | Reason shown in app |
| No-show or missed referral | Doctor, screener | In-app | Case ID |
| SLA breach | Admin | In-app | Case ID and age |

## 11. Admin and analytics

- Verification checklist for doctors (registration number) and hospitals before they can sign or appear in search
- User management and role assignment
- Metrics: screenings per week, quality-fail rate, review turnaround against targets, AI-doctor agreement, override reasons, referral acceptance rate, time to appointment, attendance, lost-to-follow-up rate, AI-versus-biopsy agreement
- **Reset demo** button that restores seeded data

## 12. Trust, privacy, and regulatory mapping

| Principle | How ONCOLINK meets it |
|---|---|
| Clear intended use | Statement on every screen and report; research use only |
| Human oversight | AI never releases a result; a verified doctor signs every report |
| Consent controls | Versioned consent records, withdrawal, and data deletion |
| Traceability to professionals and facilities | Registration numbers on reports; full audit log |
| Performance in representative settings | Outside-image testing, subgroup results, and a stated limitation that real field validation is future work |
| Privacy and data protection | Data minimisation, encryption at rest, role-scoped access, no health content over WhatsApp |
| Security | Hashed passwords, JWT with role guards, TOTP two-factor for doctors and admins, rate limiting, secrets in environment variables |
| Equity | Subgroup testing and a model card documenting dataset limits |

## 13. Data model

| Collection | Purpose |
|---|---|
| `users` | Accounts, role, verification status, registration number |
| `consents` | Version, language, timestamp, captured-by |
| `patients` | Profile, age, contact, language, risk flags |
| `cases` | Status, urgency, assignee, status history |
| `case_history` | Structured questionnaire answers |
| `images` | Site, quality scores, storage reference |
| `ai_results` | Class, confidence, uncertain flag, heatmap, model_version |
| `reviews` | Doctor decision, override reason, notes, signature |
| `reports` | Signed PDF reference, intended-use text |
| `hospitals`, `specialists`, `slots` | Tiers, departments, schedules, holds |
| `referrals`, `appointments`, `outcomes` | Referral status history, attendance, biopsy result |
| `call_sessions`, `message_log` | Metadata only |
| `audit_log` | Append-only record of every view and transition |
| `feedback`, `tickets` | Patient ratings and help requests |

## 14. Main API endpoints

- Auth and consent: `POST /auth/login`, `POST /consent`, `DELETE /me/data`
- Cases: `POST /cases`, `POST /cases/{id}/images`, `GET /queue`, `POST /cases/{id}/retake`, `POST /cases/{id}/review`, `POST /cases/{id}/sign`
- AI: `POST /cases/{id}/analyze`, `GET /models/current`
- Hospitals: `GET /hospitals/search`, `GET /hospitals/{id}/slots`, `POST /slots/{id}/hold`
- Referrals: `POST /referrals`, `PATCH /referrals/{id}/status`, `POST /appointments`, `POST /appointments/{id}/outcome`
- Communication: `POST /webhooks/whatsapp`, `POST /consults/{id}/video-room`, `POST /consults/{id}/masked-call`
- Admin: `POST /admin/verify/{id}`, `GET /admin/analytics`, `POST /admin/reset-demo`

## 15. Tech stack

| Layer | Choice |
|---|---|
| Frontend | React, Vite, Tailwind, React Router with role guards |
| Backend | FastAPI, JWT, background tasks for reminders and SLA checks |
| Database | MongoDB, with a unique index to prevent double booking |
| AI | PyTorch, EfficientNet-B0 baseline, Grad-CAM, evaluation notebook |
| Video and audio | Daily or LiveKit free tier |
| WhatsApp | Meta Cloud API in test mode |
| Phone | Exotel or similar (stretch) |
| Deployment | Docker Compose and a live demo link |

## 16. Changes needed in the existing codebase

These come from the earlier project documentation:

1. **Confidence scores:** remove scores derived from image file bytes and the fixed 87.2 to 97.8 percent range. Use only real model outputs, calibrated.
2. **Affected region:** remove the hardcoded list of regions. Use the site selected at capture, and show the heatmap only as model attention.
3. **Doctor-triggered AI:** run the locked model automatically on submission so the queue can be sorted by urgency, and keep the doctor's confirm-or-override step.
4. **Mock database:** keep `MockMongoCollection` for automated tests only, and fail loudly if the real database is unreachable in the running app.
5. **Demo password:** replace the shared `admin` password with per-role seeded passwords from environment variables, and change them on any deployed demo.
6. **Federated learning modal and offline edge AI pill:** remove, or label clearly as a simulation. Do not present them as working features.
7. **Chatbot:** keep one language and limit it to non-clinical help (how to use the app, what the steps mean). Remove medical advice.
8. **Hospital claims:** replace the '180+ partner hospitals' claim with clearly labeled demo data.
9. **Documentation claims:** remove 'fully operational and verified' wording; list what is tested and what is not.
10. **Routing:** add `/screener` and `/hospital` routes and roles to `ProtectedRoute`.
11. **Reports:** add the intended-use text, model version, doctor registration number, and 'not a diagnosis' line.
12. **Keep:** natural date formatting, role-based navigation, PDF reports, and the 403 page.

## 17. Demo data and reset

Seed several patients, two screeners, three doctors, and hospitals in each tier. Include these scenarios so the demo shows every path: a normal case, a potentially malignant case, an urgent suspicious case, an uncertain case, a failed-quality retake, a red-flag emergency, a hospital decline with re-referral, a no-show that becomes lost to follow-up, and a biopsy outcome that confirms or contradicts the AI. Provide one test account per role and the admin reset button.

## 18. Timeline (9 weeks)

| Weeks | Focus |
|---|---|
| 1-2 | Backend, auth, five roles, database, case state machine, audit log, upload and queue |
| 3-4 | Dataset, training, calibration, Grad-CAM, evaluation notebook |
| 5 | Capture protocol, quality gate, questionnaire, red-flag path, screener role |
| 6 | Doctor workspace: overrides, retakes, SLAs, sign-off, reports |
| 7 | Hospital portal, tiers, slot engine, referrals, appointments, outcomes |
| 8 | WhatsApp, video and audio consult, reminders, follow-up tracking |
| 9 | Analytics, clinician review, docs, demo video, deployment |

**If you fall behind, cut in this order:** phone calls, lesion timeline, second opinion, ViT comparison, then SMS fallback. Never cut the honest evaluation, the doctor sign-off, or the state machine.

## 19. Deliverables

- Live deployed app and GitHub repository with a clear README
- Three-minute demo video of the full flow
- Evaluation notebook that anyone can rerun
- Model card with dataset sources, limits, and subgroup results
- Architecture diagram and short project report
- Intended-use statement and regulatory mapping section

## 20. Limitations and future work

- No real patients; accuracy is measured on public datasets and a small volunteer or clinician-reviewed set, not in the field
- Public clinical-photo datasets are small and not representative of all skin tones, phones, and lighting
- Hospitals are demo data; real use needs partnerships and data-sharing agreements
- Not a regulated medical device; real use would need clinical validation and regulatory approval
- Future: ABDM health ID integration, payments, offline-first screener app, more languages, guardian consent for minors, federated training across real sites, tobacco cessation support

## 21. References to read

- Field validation of deep learning point-of-care device for oral lesions, Scientific Reports 2022: https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9395355/
- National cancer screening framework (NHM Odisha): https://nhmodisha.gov.in/wp-content/uploads/2023/08/Cancer-Screening-Rationale-Framework.pdf
- Kerala oral cancer screening trial: https://faculty.washington.edu/hujoel/EBD-pdfs/Cancer%20mortality%20screening%20trial.pdf
- Mobile AI-assisted oral lesion triage field study, JMIR mHealth 2026: https://mhealth.jmir.org/2026/1/e101721/PDF
- CDSCO medical device software guidance summary: https://nishithdesai.com/research-and-articles/hotline/pharma-healthcare-update/from-code-to-compliance-decoding-indias-medical-device-software-guidance-15623
- India telemedicine practice guidelines: https://vikaspedia.in/health/health-care-innovations/telemedicine-practice-guidelines
- WhatsApp Business messaging policy: https://whatsappbusiness.com/policy/
- DPDP Rules timeline: https://www.bassberry.com/news/indias-data-privacy-rules-what-your-business-needs-to-know/

## 22. UI design direction (new)

Full details go in `docs/DESIGN.md`, created by the design-system prompt. Summary:

- **Concept:** ordinary screens look like a well-made clinical record; the photo viewer looks like a calibrated viewing room.
- **Palette:** paper #F5F7F6, ink #18242C, rule #D5DAD8, viewer grey #4A4C4E (strictly neutral), gentian violet #4B2E83 for primary actions. Triage colours are used only for urgency: urgent #B42318, soon #B7791F, routine #2F7D57, uncertain #52627A. Always pair colour with a shape and a text label.
- **Type:** Atkinson Hyperlegible for the interface, Source Serif 4 for reports and patient explanations, Noto Sans Devanagari as a fallback.
- **Signature element:** an accessible oral cavity site map used for capture progress, site selection, the doctor's viewer labels, and reports.
- **Layouts:** mobile-first guided capture for screeners and patients; a three-pane clinical viewer for doctors; a time-grid appointment book for hospitals; ruled tables for admin; reports as printable clinical letters.
- **Avoid:** emojis, gradients, glass effects, identical rounded card grids, decorative shadows, clipart, stock photos, and fake social proof.
