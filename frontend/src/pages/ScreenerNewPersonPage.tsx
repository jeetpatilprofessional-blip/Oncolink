import React, { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { createCase, createPatient, getConsentCurrent, submitConsent } from "../api/client";
import type { ConsentCurrentResponse, PatientResponse } from "../api/types";
import { Banner } from "../components/Banner";
import { Button } from "../components/Button";
import { Field } from "../components/Field";
import { Nav } from "../components/Nav";
import { t } from "../locales/i18n";

const isUnder18 = (dobString: string): boolean => {
  if (!dobString) return true;
  const dob = new Date(dobString);
  if (isNaN(dob.getTime())) return true;
  const today = new Date();
  let age = today.getFullYear() - dob.getFullYear();
  const m = today.getMonth() - dob.getMonth();
  if (m < 0 || (m === 0 && today.getDate() < dob.getDate())) {
    age--;
  }
  return age < 18;
};

export const ScreenerNewPersonPage: React.FC = () => {
  const navigate = useNavigate();

  // Step 1 vs Step 2
  const [step, setStep] = useState<"person" | "consent">("person");

  // Step 1: Person Profile
  const [dateOfBirth, setDateOfBirth] = useState<string>("");
  const [language, setLanguage] = useState<string>("en");
  const [contact, setContact] = useState<string>("");
  const [createdPatient, setCreatedPatient] = useState<PatientResponse | null>(null);

  // Step 2: Informed Consent
  const [consentDoc, setConsentDoc] = useState<ConsentCurrentResponse | null>(null);
  const [consentAccepted, setConsentAccepted] = useState<boolean>(false);
  const [loadingConsent, setLoadingConsent] = useState<boolean>(false);

  // Shared status
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Load consent document when reaching step 2
  useEffect(() => {
    if (step === "consent") {
      setLoadingConsent(true);
      getConsentCurrent()
        .then((doc) => setConsentDoc(doc))
        .catch((err) => setErrorMsg(err.message || t("errors.generic_error")))
        .finally(() => setLoadingConsent(false));
    }
  }, [step]);

  // Step 1: Submit Person Info
  const handleCreatePerson = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);

    // Client-side age check: reject under-18 WITHOUT calling the API
    if (!dateOfBirth) {
      setErrorMsg(t("errors.field_required"));
      return;
    }

    if (isUnder18(dateOfBirth)) {
      setErrorMsg(t("errors.under_18_screener"));
      return;
    }

    setIsSubmitting(true);
    try {
      const patient = await createPatient({
        date_of_birth: dateOfBirth,
        language: language || "en",
        contact: contact.trim() || undefined,
      });
      setCreatedPatient(patient);
      setStep("consent");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : t("errors.generic_error");
      setErrorMsg(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  // Step 2: Submit In-Person Consent & Create Draft Case
  const handleRecordConsent = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!createdPatient || !consentDoc || !consentAccepted) return;

    setIsSubmitting(true);
    setErrorMsg(null);

    try {
      await submitConsent({
        patient_id: createdPatient.id,
        consent_version: consentDoc.version,
        language: language || "en",
        consent_accepted: true,
      });

      // Create draft case linked to this patient profile
      const newCase = await createCase(createdPatient.id);
      navigate(`/cases/${newCase.id}/capture`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : t("errors.generic_error");
      setErrorMsg(msg);
      setIsSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-paper font-sans text-ink flex flex-col">
      <Nav />
      <main className="max-w-2xl mx-auto w-full px-4 sm:px-6 lg:px-8 py-8 space-y-6">
        <Banner />

        <div className="border-b border-rule pb-3 flex items-center justify-between">
          <div>
            <h1 className="font-serif text-2xl font-bold tracking-tight text-ink">
              {step === "person" ? t("screener_flow.new_person_title") : t("screener_flow.consent_step_title")}
            </h1>
            <p className="text-xs text-ink/70 mt-0.5">
              {step === "person" ? t("screener_flow.new_person_subtitle") : t("screener_flow.consent_step_subtitle")}
            </p>
          </div>
          <Link to="/screener" className="text-xs font-medium text-gentian hover:underline">
            Cancel
          </Link>
        </div>

        {errorMsg && (
          <div role="alert" className="p-3 bg-urgent/10 border-l-4 border-urgent text-xs text-ink">
            {errorMsg}
          </div>
        )}

        {/* STEP 1: CREATE PERSON */}
        {step === "person" && (
          <form onSubmit={handleCreatePerson} className="bg-white p-6 border border-rule space-y-5">
            <Field
              id="patient-dob"
              label={t("screener_flow.dob_label")}
              type="date"
              required
              value={dateOfBirth}
              onChange={(e) => setDateOfBirth(e.target.value)}
              hint="Participant must be 18 years or older."
            />

            <div>
              <label htmlFor="patient-language" className="block text-xs font-semibold text-ink mb-1">
                {t("screener_flow.language_label")}
              </label>
              <select
                id="patient-language"
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                className="w-full p-2.5 text-xs bg-white border border-rule rounded-control"
              >
                <option value="en">English</option>
                <option value="hi">Hindi (हिंदी)</option>
                <option value="mr">Marathi (मराठी)</option>
                <option value="kn">Kannada (ಕನ್ನಡ)</option>
              </select>
            </div>

            <Field
              id="patient-contact"
              label={t("screener_flow.contact_label")}
              type="text"
              value={contact}
              onChange={(e) => setContact(e.target.value)}
              placeholder="e.g. Camp ID, Phone number, or Clinic Slip #"
            />

            <div className="pt-2">
              <Button
                type="submit"
                variant="primary"
                disabled={isSubmitting}
                className="w-full justify-center py-3"
              >
                {isSubmitting ? "Creating profile..." : t("screener_flow.save_person_button")}
              </Button>
            </div>
          </form>
        )}

        {/* STEP 2: IN-PERSON CONSENT */}
        {step === "consent" && (
          <form onSubmit={handleRecordConsent} className="bg-white p-6 border border-rule space-y-5">
            <div>
              <span className="text-xs font-semibold text-ink/70">
                Patient Ref: <strong className="tabular-nums text-ink">{createdPatient?.id}</strong>
              </span>
              <h2 className="text-base font-bold text-ink mt-1">
                Research & Screening Informed Consent (v{consentDoc?.version || "1.0"})
              </h2>
            </div>

            <div
              tabIndex={0}
              aria-label="Informed consent text"
              className="max-h-56 overflow-y-auto p-4 bg-paper border border-rule rounded-control text-xs text-ink/80 leading-relaxed font-serif focus-visible:outline-2 focus-visible:outline-gentian focus-visible:outline-offset-2"
            >
              {loadingConsent ? (
                <p className="text-ink/60">Loading active consent agreement...</p>
              ) : (
                <div className="whitespace-pre-line">{consentDoc?.text}</div>
              )}
            </div>

            <div className="flex items-start gap-3 pt-1">
              <input
                id="in-person-consent-agreed"
                type="checkbox"
                required
                checked={consentAccepted}
                onChange={(e) => setConsentAccepted(e.target.checked)}
                className="mt-1 h-4 w-4 rounded-control border-rule text-gentian focus:ring-gentian cursor-pointer accent-gentian"
              />
              <label htmlFor="in-person-consent-agreed" className="text-xs text-ink cursor-pointer leading-normal">
                {t("screener_flow.consent_checkbox")}
              </label>
            </div>

            <div className="pt-2">
              <Button
                type="submit"
                variant="primary"
                disabled={isSubmitting || !consentAccepted}
                className="w-full justify-center py-3 text-base"
              >
                {isSubmitting ? "Recording..." : t("screener_flow.record_consent_button")}
              </Button>
            </div>
          </form>
        )}
      </main>
    </div>
  );
};
