# ONCOLINK: Design Guide

Version 1. Applies to every screen. If a task conflicts with this file, stop and ask.

## 1. Concept

Ordinary screens look like a well-made clinical record: ruled, precise, calm. The photo viewer looks like a calibrated viewing room: neutral and free of distraction. The design should feel like it came from a clinic, not from a software template.

**The one memorable element is the oral cavity site map** (section 6). Everything around it stays quiet.

## 2. Who uses it, and the main job on each screen

| Role | Device | Main job |
|---|---|---|
| Screener | Mid-range phone, often slow network | Capture clear photos of the right sites and finish a person quickly |
| Patient | Phone | Understand what happens next and what to do |
| Doctor | Laptop, long sessions | Review many cases fast and accurately |
| Hospital coordinator | Desktop | Manage slots and referrals without double booking |
| Admin | Desktop | Verify people, watch the system, and read real numbers |

## 3. Colour

| Token | Hex | Use |
|---|---|---|
| paper | #F5F7F6 | Page background (cool off-white, never cream) |
| ink | #18242C | All text and icons |
| rule | #D5DAD8 | Dividers, table lines, borders |
| viewer | #4A4C4E | Photo viewer surround. Strictly neutral so lesion colour is not tinted |
| gentian | #4B2E83 | Primary actions, selected state, links, focus ring |
| white | #FFFFFF | Form fields and the report sheet only |

**Triage colours, reserved for urgency only:**

| State | Hex | Marker shape |
|---|---|---|
| Urgent | #B42318 | Filled triangle |
| Soon | #B7791F | Filled diamond |
| Routine | #2F7D57 | Filled circle |
| Uncertain | #52627A | Hollow square |

**Rules**
- Colour is never the only signal. Every triage state shows its shape and its word.
- Triage colours are used for markers and left borders only, never for text. Text stays ink so contrast holds.
- Gentian is never used for decoration.
- No gradients, no tinted shadows, no glass effects, no global dark mode in version 1. Only the photo viewer is dark.

## 4. Typography

| Role | Family | Notes |
|---|---|---|
| Interface | Atkinson Hyperlegible | Designed for legibility, which suits low-vision and older users |
| Reports and patient explanations | Source Serif 4 | Reads like a clinical letter |
| Devanagari fallback | Noto Sans Devanagari | For Hindi and Marathi later |

- Self-host fonts (for example through Fontsource) so the app makes no calls to third-party font servers and loads faster on slow networks. Use `font-display: swap`.
- Scale (px): 14, 16, 18, 20, 24, 30, 36. Body is 16 for staff screens and 18 for patient screens.
- Line height 1.5 for sans text and 1.6 for serif text. Keep lines under 70 characters.
- Use `font-variant-numeric: tabular-nums` for all data. Do not use a monospace face for labels.
- Headings are sentence case. Do not use all-caps labels, tracked-out eyebrow text above headings, or middle dots to join metadata. Show metadata as labelled fields.
- Do not emphasise a single word in a heading with a different colour or style.

## 5. Shape, space, and surface

- Spacing scale in px: 4, 8, 12, 16, 24, 32, 48.
- Radius is deliberate: controls 4px, panels 0 with a rule instead, clinical photo frames 0 (never round a medical image).
- Separate sections with rules and spacing, not shadows. The only shadow allowed is on menus that float above content.
- No grids of identical cards. Use tables, ruled lists, and sections of different weight.
- Use numbered steps only when the content really is a sequence, such as capture steps.

## 6. Signature component: OralSiteMap

An accessible SVG schematic of the oral cavity with seven selectable regions: left cheek, right cheek, tongue top, tongue sides, floor of mouth, hard palate, lips and gums.

- **Three states per region:** not captured (outline only), captured (solid fill in ink at low opacity plus a tick), rejected (hatched fill plus a cross). Always accompanied by text.
- **Uses:** capture progress, site selection when saving a photo, site label in the doctor's viewer, and the marked-sites figure on the report.
- Works with touch, keyboard (arrow keys move between regions, Enter selects), and screen readers through a plain text list alternative.
- Readable at 320px wide. Region names match the capture protocol in the spec. Have a dentist or doctor confirm the layout before relying on it.

## 7. Layouts

### Screener and patient capture (mobile first, 360px and up)

```
+--------------------------------+
| Case 0412-17        Step 3 of 6|
|--------------------------------|
|        [ OralSiteMap ]         |
|                                |
| Tongue, sides                  |
| Stick out your tongue and turn |
| it to one side. Keep it in the |
| frame.                         |
| +----------------------------+ |
| |        camera view         | |
| |      [framing guide]       | |
| +----------------------------+ |
| Light: good     Focus: soft    |
| [ Take photo ]                 |
+--------------------------------+
```

- Live feedback on light and focus appears before the shutter, not after.
- The screener mode adds a session ledger (a ruled list of people screened today, with status), reachable from the top bar.
- Compress photos on the device before upload and show skeleton placeholders, not spinners.

### Doctor viewer (desktop)

```
+---------------+--------------------------------+------------------+
| Worklist      | Photos                         | Decision         |
|---------------|--------------------------------|------------------|
| ▲ 0412-17  3h | [ viewer grey background ]     | History          |
| ◆ 0409-02  1d | [ photo ] [ compare photo ]    | Model result     |
| ● 0407-11  2d | zoom  pan  heatmap [on/off]    |  class, version  |
| □ 0405-30  2d | Where the model looked         | Your decision    |
|               | Site: Tongue, sides            |  confirm / override|
|               |                                | Reason           |
|               |                                | [ Sign report ]  |
+---------------+--------------------------------+------------------+
| Viewed by Dr. A. Rao, 14:02 (audit line)                           |
+--------------------------------------------------------------------+
```

- Worklist rows, not cards: marker, reference, age, waiting time, SLA indicator. Red-flag cases are pinned with a 4px left border in the urgent colour.
- Keyboard shortcuts: J and K move through cases, H toggles the heatmap, C toggles compare, O starts an override. Provide a help panel listing them.
- Below 1024px the three panes become three tabs (Worklist, Photos, Decision), not a stacked page.
- The heatmap is never shown without its label 'Where the model looked'.

### Hospital appointment book (desktop)

```
+---------------------------------------------------------------+
| Dr. Mehta, Oral oncology        Week of 2 Nov                 |
|---------+-------------+-------------+-------------+-----------|
|         | Mon         | Tue         | Wed         | Thu       |
| 09:00   | ▲ 0412-17   | open        | ◆ 0409-02   | open      |
| 09:30   | open        | held 08:52  | open        | blocked   |
| 10:00   | ● 0407-11   | open        | open        | open      |
+---------+-------------+-------------+-------------+-----------+
| Referral inbox: sorted by urgency, with Accept, Reschedule,   |
| Decline (reason required)                                     |
+---------------------------------------------------------------+
```

### Report (printable clinical letter)

```
+------------------------------------------------+
| Facility name                  Ref: 0412-17    |
| Address                        Date: 2 Nov 2026|
|------------------------------------------------|
| Patient: name, age, sex                        |
| Findings (plain language)                      |
| [ site map with marked sites ]                 |
| Model result: assistive estimate, not a        |
| diagnosis. Model version 1.2                   |
| Doctor's notes                                 |
| Next steps, in order of urgency                |
|------------------------------------------------|
| Signed: Dr. A. Rao, Reg. no. ____              |
| Verify this report: code ____                  |
| Intended-use notice                            |
+------------------------------------------------+
```

- Source Serif 4 for body text. A4 print stylesheet that works in black and white, with urgency shown by shape and word.

### Admin

- Ruled tables with small inline charts. Each chart has a title stating what it measures, labelled axes, and the sample size. Show 'insufficient data' when the sample is small. No tile grids and no decorative charts.

## 8. Components

| Component | Behaviour |
|---|---|
| Button | Primary is gentian fill. Secondary is an ink outline. Destructive actions such as Decline referral use an outline, never a red fill. Labels are verbs with no arrows. 44px minimum touch target |
| Field | Visible label above the input, never placeholder-only. Errors appear below the field and in a summary at the top of the form |
| DataTable | 36px dense rows for staff screens, 44px on touch screens. Sticky header, sortable columns, tabular numerals |
| StatusMarker | The four shapes plus the word. Used in lists, headers, and reports |
| Banner (intended-use) | A calm strip with a top rule on result and report screens. Not a dismissible popup |
| Timeline | Vertical case history with timestamps in 24-hour time and the actor's name |
| AuditLine | One line at the foot of a case: who viewed it, when |
| OralSiteMap | See section 6 |
| ImageViewer | Neutral grey surround, zoom, pan, side-by-side compare, heatmap toggle with opacity control |
| SlotGrid | Time grid with open, held, booked, and blocked states shown by pattern and text |
| ReportSheet | White sheet for on-screen preview and print |

## 9. Writing

- Plain words, sentence case, active voice. Name things the way users do.
- Buttons say what happens: 'Take photo', 'Retake photo', 'Request retake', 'Sign report', 'Send referral', 'Book slot'. The same action keeps the same name everywhere, including in confirmations.
- Errors say what happened and how to fix it. Examples: 'Photo too dark. Move near a window or turn on a light, then retake.' 'This slot was just booked. Choose another time.'
- Empty states give direction: 'No cases waiting. New screenings appear here as they arrive.'
- Results are labelled honestly: 'Model result (assistive, not a diagnosis)' and 'Where the model looked'.
- Patient-facing language is calm and specific: 'A doctor reviewed your photos and recommends a visit to a specialist within two weeks.' Do not use frightening or diagnostic words in notifications.
- Keep all text in locale files so Hindi and Marathi can be added later. Never put text inside images.

## 10. Motion

- Only three animations are allowed: a site map region filling when a photo is accepted, the heatmap crossfading on toggle, and a brief confirmation after a save. Each lasts about 150ms.
- No entrance animations, no scroll effects, no hover flourishes.
- Respect `prefers-reduced-motion` by removing all three.

## 11. Accessibility and low bandwidth

- WCAG AA contrast. Visible focus on every control: a 2px gentian ring with a 2px paper gap.
- Works at 320px wide and at 200% text zoom.
- Target size 44px on touch screens.
- Site map and charts have text alternatives.
- Compress photos before upload (maximum 1600px on the long side), use skeletons for loading, and keep pages light for slow connections.

## 12. Principles

1. Clinical clarity beats visual flair. Remove anything that does not help someone read, decide, or act.
2. Structure carries information. Rules, labels, and numbering appear only when they mean something.
3. Spend boldness in one place: the site map.
4. Honesty is part of the design. Model output is always labelled as an assistive estimate, and the intended-use notice is always visible on result screens.
5. A mid-range phone on a slow network is the baseline, not an edge case.

## 13. What to avoid

- Emojis anywhere in the interface
- Gradients, glass effects, neon accents, and decorative blobs
- Heartbeat lines, stethoscope or heart clipart, stock photos of doctors
- A blue-teal medical template look
- Identical rounded cards with the same shadow
- Big-number hero stats, fake testimonials, 'trusted by' logos
- All-caps eyebrow labels, spaced em-dash labels, arrows on buttons
- Colour used alone to carry meaning

## 14. Before you finish any screen

Take screenshots at 360px, 768px, and 1280px. Check against this guide. Then remove one element that does not earn its place.
