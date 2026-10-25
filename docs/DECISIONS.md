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

* **Decision:** AI prediction classes and Biopsy outcome categories are implemented as separate, dedicated enums.
* **Rationale:** AI triage assists a doctor prior to clinical examination (classes: `normal_or_benign`, `potentially_malignant`, `suspicious_for_cancer`, `uncertain`), whereas histopathological biopsy establishes definitive tissue diagnosis (categories: `benign`, `potentially_malignant`, `malignant`, `inconclusive`). Keeping these enums distinct prevents confusing screening hypotheses with histopathological truth.

## Decision 4: Dual-Stage Quality Feedback

* **Decision:** Pre-capture quality feedback (blur, lighting, framing guide) runs client-side on the device before the shutter is pressed, and the backend server runs its own automated quality check during the `quality_check` lifecycle state as the authoritative gate.
* **Rationale:** Immediate client-side feedback prevents screeners from taking poor photos and wasting bandwidth. The backend quality gate provides an objective, verifiable check on the uploaded full-resolution image before queuing for AI analysis.

## Decision 5: Real Database Only; Seeded Demo Data via Scripts

* **Decision:** Runtime application code connects only to a real database (MongoDB replica set) and real storage (MinIO). Runtime code contains zero mock database or mock data fallbacks. If any connection is unreachable, the system fails loudly.
* **Rationale:** Mock fallbacks mask configuration errors and risk leaking fake clinical outputs into real workflows. Demonstrations and end-to-end tests use real MongoDB collections populated by explicit seeding scripts, with all seeded records clearly labeled as demonstration data (`is_demo: true`).
