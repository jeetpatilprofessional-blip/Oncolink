import React, { useState } from "react";
import {
  AuditLine,
  Banner,
  Button,
  DataTable,
  Field,
  StatusMarker,
  Timeline,
  type Column,
} from "../components";
import { t } from "../locales/i18n";

interface SampleRow extends Record<string, unknown> {
  id: string;
  caseRef: string;
  patientAge: number;
  site: string;
  urgency: "urgent" | "soon" | "routine" | "uncertain";
  waitingHours: number;
}

export const DevComponentsPage: React.FC = () => {
  const [fieldVal, setFieldVal] = useState("0412-17");
  const [errorVal, setErrorVal] = useState("");
  const [simulateError, setSimulateError] = useState(true);

  // Guard: Available only in development builds
  if (!import.meta.env.DEV) {
    return (
      <main className="p-8 max-w-xl mx-auto text-left font-sans">
        <h1 className="text-xl font-bold text-[#18242C]">404 — Not Found</h1>
        <p className="text-sm text-[#18242C]/80 mt-2">
          This development gallery is only available in development mode.
        </p>
      </main>
    );
  }

  const sampleRows: SampleRow[] = [
    {
      id: "1",
      caseRef: "0412-17",
      patientAge: 52,
      site: "Tongue, sides",
      urgency: "urgent",
      waitingHours: 3,
    },
    {
      id: "2",
      caseRef: "0409-02",
      patientAge: 47,
      site: "Left cheek",
      urgency: "soon",
      waitingHours: 24,
    },
    {
      id: "3",
      caseRef: "0407-11",
      patientAge: 61,
      site: "Hard palate",
      urgency: "routine",
      waitingHours: 48,
    },
    {
      id: "4",
      caseRef: "0405-30",
      patientAge: 38,
      site: "Floor of mouth",
      urgency: "uncertain",
      waitingHours: 48,
    },
  ];

  const columns: Column<SampleRow>[] = [
    {
      key: "urgency",
      header: t("table.urgency"),
      sortable: true,
      render: (row) => <StatusMarker urgency={row.urgency} />,
    },
    { key: "caseRef", header: t("table.case_ref"), sortable: true },
    { key: "patientAge", header: "Age", sortable: true, align: "right" },
    { key: "site", header: t("table.site"), sortable: true },
    {
      key: "waitingHours",
      header: t("table.waiting_time"),
      sortable: true,
      align: "right",
      render: (row) => <span>{row.waitingHours}h</span>,
    },
  ];

  const timelineItems = [
    {
      id: "t1",
      time: "09:15",
      actor: "Screener Sunita V.",
      event: t("timeline.case_submitted"),
      notes: "High risk tobacco user. Lesion duration 3 weeks on lateral tongue border.",
    },
    {
      id: "t2",
      time: "09:16",
      actor: "Automated Triage (EfficientNet-B0 v1.0.0)",
      event: t("timeline.ai_analyzed"),
      notes: "Class: Suspicious for cancer. Attention localized to lateral border.",
    },
    {
      id: "t3",
      time: "11:30",
      actor: "Dr. A. Rao (Reg 48291)",
      event: t("timeline.doctor_reviewed"),
      notes: "AI finding confirmed. Referred for urgent biopsy.",
    },
    {
      id: "t4",
      time: "11:35",
      actor: "Dr. A. Rao (Reg 48291)",
      event: t("timeline.referral_sent"),
      notes: "Slot requested at District Hospital ENT department.",
    },
  ];

  return (
    <div className="min-h-screen bg-[#F5F7F6] text-[#18242C] font-sans pb-16">
      {/* 1. Intended-Use Banner */}
      <Banner />

      <main className="max-w-4xl mx-auto px-4 py-8 space-y-12 text-left">
        <header className="border-b border-[#D5DAD8] pb-4">
          <h1 className="text-2xl font-bold tracking-tight text-[#18242C]">
            {t("dev.components_title")}
          </h1>
          <p className="text-sm text-[#18242C]/70 mt-1">{t("dev.components_desc")}</p>
        </header>

        {/* Section: Status Markers */}
        <section aria-labelledby="status-markers-heading" className="space-y-4">
          <h2
            id="status-markers-heading"
            className="text-lg font-semibold border-b border-[#D5DAD8] pb-1"
          >
            {t("dev.status_markers_section")}
          </h2>
          <p className="text-xs text-[#18242C]/70">
            Triage colours reserved for urgency only, always paired with a shape and word. Text
            stays ink.
          </p>
          <div className="flex flex-wrap gap-6 p-4 bg-white border border-[#D5DAD8]">
            <StatusMarker urgency="urgent" />
            <StatusMarker urgency="soon" />
            <StatusMarker urgency="routine" />
            <StatusMarker urgency="uncertain" />
          </div>
        </section>

        {/* Section: Buttons */}
        <section aria-labelledby="buttons-heading" className="space-y-4">
          <h2 id="buttons-heading" className="text-lg font-semibold border-b border-[#D5DAD8] pb-1">
            {t("dev.buttons_section")}
          </h2>
          <p className="text-xs text-[#18242C]/70">
            Primary is gentian fill. Secondary is ink outline. Destructive actions use ink outline
            (never red fill). 44px min touch target.
          </p>
          <div className="p-4 bg-white border border-[#D5DAD8] space-y-4">
            <div className="flex flex-wrap items-center gap-4">
              <Button variant="primary">{t("actions.sign_report")}</Button>
              <Button variant="secondary">{t("actions.take_photo")}</Button>
              <Button variant="destructive">{t("actions.decline_referral")}</Button>
            </div>
            <div className="flex flex-wrap items-center gap-4 pt-2 border-t border-[#D5DAD8]">
              <span className="text-xs font-semibold text-[#18242C]/60 uppercase tracking-wide">
                Disabled states:
              </span>
              <Button variant="primary" disabled>
                {t("actions.sign_report")}
              </Button>
              <Button variant="secondary" disabled>
                {t("actions.take_photo")}
              </Button>
              <Button variant="destructive" disabled>
                {t("actions.decline_referral")}
              </Button>
            </div>
          </div>
        </section>

        {/* Section: Form Fields */}
        <section aria-labelledby="fields-heading" className="space-y-4">
          <h2 id="fields-heading" className="text-lg font-semibold border-b border-[#D5DAD8] pb-1">
            {t("dev.fields_section")}
          </h2>
          <div className="p-4 bg-white border border-[#D5DAD8] space-y-4 max-w-lg">
            <Field
              label={t("fields.patient_id")}
              value={fieldVal}
              onChange={(e) => setFieldVal(e.target.value)}
              hint={t("hints.patient_ref_hint")}
            />

            <Field
              label={t("fields.notes")}
              value={errorVal}
              onChange={(e) => {
                setErrorVal(e.target.value);
                if (e.target.value) setSimulateError(false);
              }}
              error={simulateError ? t("errors.field_required") : undefined}
              placeholder="Enter doctor consultation notes..."
            />

            <Field
              label="Registration number (disabled)"
              value="MCI-48291-MH (Verified)"
              disabled
            />
          </div>
        </section>

        {/* Section: Data Tables */}
        <section aria-labelledby="datatable-heading" className="space-y-4">
          <h2
            id="datatable-heading"
            className="text-lg font-semibold border-b border-[#D5DAD8] pb-1"
          >
            {t("dev.datatable_section")}
          </h2>

          <div className="space-y-6">
            <div>
              <h3 className="text-sm font-medium text-[#18242C] mb-2">
                Staff Worklist Table (Dense density: 36px rows, keyboard sortable)
              </h3>
              <DataTable
                columns={columns}
                data={sampleRows}
                density="dense"
                initialSortKey="waitingHours"
                initialSortDirection="desc"
                caption="Oral cancer screening cases waiting queue"
              />
            </div>

            <div>
              <h3 className="text-sm font-medium text-[#18242C] mb-2">
                Touch-Friendly Table (Touch density: 44px rows)
              </h3>
              <DataTable
                columns={columns}
                data={sampleRows.slice(0, 2)}
                density="touch"
                caption="Touch density screening table"
              />
            </div>
          </div>
        </section>

        {/* Section: Case Timeline */}
        <section aria-labelledby="timeline-heading" className="space-y-4">
          <h2
            id="timeline-heading"
            className="text-lg font-semibold border-b border-[#D5DAD8] pb-1"
          >
            {t("dev.timeline_section")}
          </h2>
          <div className="p-6 bg-white border border-[#D5DAD8]">
            <Timeline items={timelineItems} />
          </div>
        </section>

        {/* Section: Audit Line */}
        <section aria-labelledby="audit-heading" className="space-y-4">
          <h2 id="audit-heading" className="text-lg font-semibold border-b border-[#D5DAD8] pb-1">
            {t("dev.audit_section")}
          </h2>
          <div className="p-4 bg-white border border-[#D5DAD8]">
            <AuditLine actor="Dr. A. Rao" time="14:02" />
          </div>
        </section>
      </main>
    </div>
  );
};

export default DevComponentsPage;
