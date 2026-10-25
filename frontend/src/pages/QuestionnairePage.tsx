import React, { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { saveCaseHistory } from "../api/client";
import type { CaseHistoryPayload, Frequency } from "../api/types";
import { Banner } from "../components/Banner";
import { Button } from "../components/Button";
import { Field } from "../components/Field";
import { useAuth } from "../context";
import { t } from "../locales/i18n";

export const QuestionnairePage: React.FC = () => {
  const { id: caseId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();

  const [formData, setFormData] = useState<CaseHistoryPayload>({
    // 1. Red-flag symptoms FIRST
    heavy_bleeding: false,
    difficulty_breathing: false,
    rapid_swelling: false,

    // 2. Lesion characteristics
    lesion_duration_weeks: 0,
    lesion_pain: false,
    lesion_non_healing_two_weeks: false,
    lesion_bleeding: false,
    lesion_white_or_red_patch: false,
    lesion_lump: false,

    // 3. Functional signs
    difficulty_swallowing: false,
    difficulty_opening_mouth: false,
    difficulty_speaking: false,
    unexplained_weight_loss: false,

    // 4. Family history
    family_history_cancer: false,

    // 5. Exposure history
    tobacco_smoked_frequency: "never",
    tobacco_smoked_years: 0,
    tobacco_smokeless_frequency: "never",
    tobacco_smokeless_years: 0,
    areca_nut_frequency: "never",
    areca_nut_years: 0,
    betel_quid_frequency: "never",
    betel_quid_years: 0,
    alcohol_frequency: "never",
  });

  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Red-flag detector: any of the three emergency questions answered true
  const hasRedFlag =
    formData.heavy_bleeding || formData.difficulty_breathing || formData.rapid_swelling;

  const handleBooleanChange = (key: keyof CaseHistoryPayload, value: boolean) => {
    setFormData((prev) => ({ ...prev, [key]: value }));
  };

  const handleFrequencyChange = (key: keyof CaseHistoryPayload, value: Frequency) => {
    setFormData((prev) => ({ ...prev, [key]: value }));
  };

  const handleNumberChange = (key: keyof CaseHistoryPayload, value: number) => {
    setFormData((prev) => ({ ...prev, [key]: isNaN(value) ? 0 : value }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!caseId) return;
    setIsSubmitting(true);
    setErrorMsg(null);

    try {
      await saveCaseHistory(caseId, formData);
      navigate(`/cases/${caseId}/review`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : t("errors.generic_error");
      setErrorMsg(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="max-w-xl mx-auto p-4 pb-12 font-sans space-y-5">
      <Banner />

      {/* Header with Case Reference & Step */}
      <div className="border-b border-rule pb-3 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1">
        <div>
          <span className="text-xs uppercase tracking-wider text-ink/70">
            {user?.role === "screener" ? "Screener Intake" : "Patient Self-Screening"}
          </span>
          <h1 className="font-serif text-xl sm:text-2xl font-bold text-ink">
            {t("questionnaire.title")}
          </h1>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <Link to={`/cases/${caseId}/capture`} className="text-gentian hover:underline font-medium">
            Photos
          </Link>
          <span className="text-rule">|</span>
          <Link to={`/cases/${caseId}/review`} className="text-gentian hover:underline font-medium">
            Review
          </Link>
        </div>
      </div>

      {/* Emergency Red-Flag Banner (Visible Immediately When Any Red Flag is Yes) */}
      {hasRedFlag && (
        <div
          role="alert"
          aria-live="assertive"
          className="p-4 bg-urgent/15 border-l-4 border-urgent text-ink space-y-1"
        >
          <div className="font-bold text-sm text-urgent uppercase tracking-wide">
            {t("questionnaire.emergency_title")}
          </div>
          <p className="text-xs leading-relaxed font-medium">
            {t("questionnaire.emergency_message")}
          </p>
        </div>
      )}

      {errorMsg && (
        <div role="alert" className="p-3 bg-urgent/10 border-l-4 border-urgent text-xs text-ink">
          {errorMsg}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* SECTION 1: RED-FLAG QUESTIONS FIRST */}
        <fieldset className="bg-white p-4 border border-rule space-y-4">
          <legend className="text-sm font-bold text-ink border-b border-rule pb-1 w-full">
            1. {t("questionnaire.red_flags_title")}
          </legend>

          {/* Heavy Bleeding */}
          <div className="space-y-1.5">
            <span className="block text-xs font-semibold text-ink">
              {t("questionnaire.heavy_bleeding_label")}
            </span>
            <div className="flex gap-4">
              <label className="flex items-center gap-2 text-xs text-ink cursor-pointer">
                <input
                  type="radio"
                  name="heavy_bleeding"
                  checked={!formData.heavy_bleeding}
                  onChange={() => handleBooleanChange("heavy_bleeding", false)}
                  className="accent-gentian"
                />
                {t("questionnaire.no")}
              </label>
              <label className="flex items-center gap-2 text-xs text-ink cursor-pointer">
                <input
                  type="radio"
                  name="heavy_bleeding"
                  checked={formData.heavy_bleeding}
                  onChange={() => handleBooleanChange("heavy_bleeding", true)}
                  className="accent-gentian"
                />
                {t("questionnaire.yes")}
              </label>
            </div>
          </div>

          {/* Difficulty Breathing */}
          <div className="space-y-1.5">
            <span className="block text-xs font-semibold text-ink">
              {t("questionnaire.difficulty_breathing_label")}
            </span>
            <div className="flex gap-4">
              <label className="flex items-center gap-2 text-xs text-ink cursor-pointer">
                <input
                  type="radio"
                  name="difficulty_breathing"
                  checked={!formData.difficulty_breathing}
                  onChange={() => handleBooleanChange("difficulty_breathing", false)}
                  className="accent-gentian"
                />
                {t("questionnaire.no")}
              </label>
              <label className="flex items-center gap-2 text-xs text-ink cursor-pointer">
                <input
                  type="radio"
                  name="difficulty_breathing"
                  checked={formData.difficulty_breathing}
                  onChange={() => handleBooleanChange("difficulty_breathing", true)}
                  className="accent-gentian"
                />
                {t("questionnaire.yes")}
              </label>
            </div>
          </div>

          {/* Rapid Swelling */}
          <div className="space-y-1.5">
            <span className="block text-xs font-semibold text-ink">
              {t("questionnaire.rapid_swelling_label")}
            </span>
            <div className="flex gap-4">
              <label className="flex items-center gap-2 text-xs text-ink cursor-pointer">
                <input
                  type="radio"
                  name="rapid_swelling"
                  checked={!formData.rapid_swelling}
                  onChange={() => handleBooleanChange("rapid_swelling", false)}
                  className="accent-gentian"
                />
                {t("questionnaire.no")}
              </label>
              <label className="flex items-center gap-2 text-xs text-ink cursor-pointer">
                <input
                  type="radio"
                  name="rapid_swelling"
                  checked={formData.rapid_swelling}
                  onChange={() => handleBooleanChange("rapid_swelling", true)}
                  className="accent-gentian"
                />
                {t("questionnaire.yes")}
              </label>
            </div>
          </div>
        </fieldset>

        {/* SECTION 2: LESION CHARACTERISTICS */}
        <fieldset className="bg-white p-4 border border-rule space-y-4">
          <legend className="text-sm font-bold text-ink border-b border-rule pb-1 w-full">
            2. {t("questionnaire.lesion_section_title")}
          </legend>

          <Field
            id="lesion_duration_weeks"
            label={t("questionnaire.lesion_duration_label")}
            type="number"
            min={0}
            max={520}
            value={formData.lesion_duration_weeks}
            onChange={(e) => handleNumberChange("lesion_duration_weeks", parseInt(e.target.value, 10))}
          />

          <div className="space-y-1.5">
            <span className="block text-xs font-semibold text-ink">
              {t("questionnaire.lesion_pain_label")}
            </span>
            <div className="flex gap-4">
              <label className="flex items-center gap-2 text-xs text-ink cursor-pointer">
                <input
                  type="radio"
                  name="lesion_pain"
                  checked={!formData.lesion_pain}
                  onChange={() => handleBooleanChange("lesion_pain", false)}
                  className="accent-gentian"
                />
                {t("questionnaire.no")}
              </label>
              <label className="flex items-center gap-2 text-xs text-ink cursor-pointer">
                <input
                  type="radio"
                  name="lesion_pain"
                  checked={formData.lesion_pain}
                  onChange={() => handleBooleanChange("lesion_pain", true)}
                  className="accent-gentian"
                />
                {t("questionnaire.yes")}
              </label>
            </div>
          </div>

          <div className="space-y-1.5">
            <span className="block text-xs font-semibold text-ink">
              {t("questionnaire.lesion_non_healing_label")}
            </span>
            <div className="flex gap-4">
              <label className="flex items-center gap-2 text-xs text-ink cursor-pointer">
                <input
                  type="radio"
                  name="lesion_non_healing"
                  checked={!formData.lesion_non_healing_two_weeks}
                  onChange={() => handleBooleanChange("lesion_non_healing_two_weeks", false)}
                  className="accent-gentian"
                />
                {t("questionnaire.no")}
              </label>
              <label className="flex items-center gap-2 text-xs text-ink cursor-pointer">
                <input
                  type="radio"
                  name="lesion_non_healing"
                  checked={formData.lesion_non_healing_two_weeks}
                  onChange={() => handleBooleanChange("lesion_non_healing_two_weeks", true)}
                  className="accent-gentian"
                />
                {t("questionnaire.yes")}
              </label>
            </div>
          </div>

          <div className="space-y-1.5">
            <span className="block text-xs font-semibold text-ink">
              {t("questionnaire.lesion_bleeding_label")}
            </span>
            <div className="flex gap-4">
              <label className="flex items-center gap-2 text-xs text-ink cursor-pointer">
                <input
                  type="radio"
                  name="lesion_bleeding"
                  checked={!formData.lesion_bleeding}
                  onChange={() => handleBooleanChange("lesion_bleeding", false)}
                  className="accent-gentian"
                />
                {t("questionnaire.no")}
              </label>
              <label className="flex items-center gap-2 text-xs text-ink cursor-pointer">
                <input
                  type="radio"
                  name="lesion_bleeding"
                  checked={formData.lesion_bleeding}
                  onChange={() => handleBooleanChange("lesion_bleeding", true)}
                  className="accent-gentian"
                />
                {t("questionnaire.yes")}
              </label>
            </div>
          </div>

          <div className="space-y-1.5">
            <span className="block text-xs font-semibold text-ink">
              {t("questionnaire.lesion_patch_label")}
            </span>
            <div className="flex gap-4">
              <label className="flex items-center gap-2 text-xs text-ink cursor-pointer">
                <input
                  type="radio"
                  name="lesion_patch"
                  checked={!formData.lesion_white_or_red_patch}
                  onChange={() => handleBooleanChange("lesion_white_or_red_patch", false)}
                  className="accent-gentian"
                />
                {t("questionnaire.no")}
              </label>
              <label className="flex items-center gap-2 text-xs text-ink cursor-pointer">
                <input
                  type="radio"
                  name="lesion_patch"
                  checked={formData.lesion_white_or_red_patch}
                  onChange={() => handleBooleanChange("lesion_white_or_red_patch", true)}
                  className="accent-gentian"
                />
                {t("questionnaire.yes")}
              </label>
            </div>
          </div>

          <div className="space-y-1.5">
            <span className="block text-xs font-semibold text-ink">
              {t("questionnaire.lesion_lump_label")}
            </span>
            <div className="flex gap-4">
              <label className="flex items-center gap-2 text-xs text-ink cursor-pointer">
                <input
                  type="radio"
                  name="lesion_lump"
                  checked={!formData.lesion_lump}
                  onChange={() => handleBooleanChange("lesion_lump", false)}
                  className="accent-gentian"
                />
                {t("questionnaire.no")}
              </label>
              <label className="flex items-center gap-2 text-xs text-ink cursor-pointer">
                <input
                  type="radio"
                  name="lesion_lump"
                  checked={formData.lesion_lump}
                  onChange={() => handleBooleanChange("lesion_lump", true)}
                  className="accent-gentian"
                />
                {t("questionnaire.yes")}
              </label>
            </div>
          </div>
        </fieldset>

        {/* SECTION 3: FUNCTIONAL IMPAIRMENT */}
        <fieldset className="bg-white p-4 border border-rule space-y-4">
          <legend className="text-sm font-bold text-ink border-b border-rule pb-1 w-full">
            3. {t("questionnaire.function_section_title")}
          </legend>

          <div className="space-y-1.5">
            <span className="block text-xs font-semibold text-ink">
              {t("questionnaire.difficulty_swallowing_label")}
            </span>
            <div className="flex gap-4">
              <label className="flex items-center gap-2 text-xs text-ink cursor-pointer">
                <input
                  type="radio"
                  name="difficulty_swallowing"
                  checked={!formData.difficulty_swallowing}
                  onChange={() => handleBooleanChange("difficulty_swallowing", false)}
                  className="accent-gentian"
                />
                {t("questionnaire.no")}
              </label>
              <label className="flex items-center gap-2 text-xs text-ink cursor-pointer">
                <input
                  type="radio"
                  name="difficulty_swallowing"
                  checked={formData.difficulty_swallowing}
                  onChange={() => handleBooleanChange("difficulty_swallowing", true)}
                  className="accent-gentian"
                />
                {t("questionnaire.yes")}
              </label>
            </div>
          </div>

          <div className="space-y-1.5">
            <span className="block text-xs font-semibold text-ink">
              {t("questionnaire.difficulty_opening_label")}
            </span>
            <div className="flex gap-4">
              <label className="flex items-center gap-2 text-xs text-ink cursor-pointer">
                <input
                  type="radio"
                  name="difficulty_opening"
                  checked={!formData.difficulty_opening_mouth}
                  onChange={() => handleBooleanChange("difficulty_opening_mouth", false)}
                  className="accent-gentian"
                />
                {t("questionnaire.no")}
              </label>
              <label className="flex items-center gap-2 text-xs text-ink cursor-pointer">
                <input
                  type="radio"
                  name="difficulty_opening"
                  checked={formData.difficulty_opening_mouth}
                  onChange={() => handleBooleanChange("difficulty_opening_mouth", true)}
                  className="accent-gentian"
                />
                {t("questionnaire.yes")}
              </label>
            </div>
          </div>

          <div className="space-y-1.5">
            <span className="block text-xs font-semibold text-ink">
              {t("questionnaire.difficulty_speaking_label")}
            </span>
            <div className="flex gap-4">
              <label className="flex items-center gap-2 text-xs text-ink cursor-pointer">
                <input
                  type="radio"
                  name="difficulty_speaking"
                  checked={!formData.difficulty_speaking}
                  onChange={() => handleBooleanChange("difficulty_speaking", false)}
                  className="accent-gentian"
                />
                {t("questionnaire.no")}
              </label>
              <label className="flex items-center gap-2 text-xs text-ink cursor-pointer">
                <input
                  type="radio"
                  name="difficulty_speaking"
                  checked={formData.difficulty_speaking}
                  onChange={() => handleBooleanChange("difficulty_speaking", true)}
                  className="accent-gentian"
                />
                {t("questionnaire.yes")}
              </label>
            </div>
          </div>

          <div className="space-y-1.5">
            <span className="block text-xs font-semibold text-ink">
              {t("questionnaire.weight_loss_label")}
            </span>
            <div className="flex gap-4">
              <label className="flex items-center gap-2 text-xs text-ink cursor-pointer">
                <input
                  type="radio"
                  name="weight_loss"
                  checked={!formData.unexplained_weight_loss}
                  onChange={() => handleBooleanChange("unexplained_weight_loss", false)}
                  className="accent-gentian"
                />
                {t("questionnaire.no")}
              </label>
              <label className="flex items-center gap-2 text-xs text-ink cursor-pointer">
                <input
                  type="radio"
                  name="weight_loss"
                  checked={formData.unexplained_weight_loss}
                  onChange={() => handleBooleanChange("unexplained_weight_loss", true)}
                  className="accent-gentian"
                />
                {t("questionnaire.yes")}
              </label>
            </div>
          </div>
        </fieldset>

        {/* SECTION 4: FAMILY HISTORY */}
        <fieldset className="bg-white p-4 border border-rule space-y-2">
          <legend className="text-sm font-bold text-ink border-b border-rule pb-1 w-full">
            4. {t("questionnaire.family_section_title")}
          </legend>
          <div className="space-y-1.5">
            <span className="block text-xs font-semibold text-ink">
              {t("questionnaire.family_cancer_label")}
            </span>
            <div className="flex gap-4">
              <label className="flex items-center gap-2 text-xs text-ink cursor-pointer">
                <input
                  type="radio"
                  name="family_history"
                  checked={!formData.family_history_cancer}
                  onChange={() => handleBooleanChange("family_history_cancer", false)}
                  className="accent-gentian"
                />
                {t("questionnaire.no")}
              </label>
              <label className="flex items-center gap-2 text-xs text-ink cursor-pointer">
                <input
                  type="radio"
                  name="family_history"
                  checked={formData.family_history_cancer}
                  onChange={() => handleBooleanChange("family_history_cancer", true)}
                  className="accent-gentian"
                />
                {t("questionnaire.yes")}
              </label>
            </div>
          </div>
        </fieldset>

        {/* SECTION 5: TOBACCO & ARECA EXPOSURE */}
        <fieldset className="bg-white p-4 border border-rule space-y-4">
          <legend className="text-sm font-bold text-ink border-b border-rule pb-1 w-full">
            5. {t("questionnaire.tobacco_section_title")}
          </legend>

          {/* Smoked Tobacco */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label htmlFor="tobacco_smoked_frequency" className="block text-xs font-semibold text-ink mb-1">
                {t("questionnaire.smoked_frequency_label")}
              </label>
              <select
                id="tobacco_smoked_frequency"
                value={formData.tobacco_smoked_frequency}
                onChange={(e) => handleFrequencyChange("tobacco_smoked_frequency", e.target.value as Frequency)}
                className="w-full p-2 text-xs bg-white border border-rule rounded-control"
              >
                <option value="never">{t("questionnaire.freq_never")}</option>
                <option value="occasional">{t("questionnaire.freq_occasional")}</option>
                <option value="daily">{t("questionnaire.freq_daily")}</option>
              </select>
            </div>
            <Field
              id="tobacco_smoked_years"
              label={t("questionnaire.smoked_years_label")}
              type="number"
              min={0}
              max={100}
              value={formData.tobacco_smoked_years}
              onChange={(e) => handleNumberChange("tobacco_smoked_years", parseInt(e.target.value, 10))}
            />
          </div>

          {/* Smokeless Tobacco */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label htmlFor="tobacco_smokeless_frequency" className="block text-xs font-semibold text-ink mb-1">
                {t("questionnaire.smokeless_frequency_label")}
              </label>
              <select
                id="tobacco_smokeless_frequency"
                value={formData.tobacco_smokeless_frequency}
                onChange={(e) => handleFrequencyChange("tobacco_smokeless_frequency", e.target.value as Frequency)}
                className="w-full p-2 text-xs bg-white border border-rule rounded-control"
              >
                <option value="never">{t("questionnaire.freq_never")}</option>
                <option value="occasional">{t("questionnaire.freq_occasional")}</option>
                <option value="daily">{t("questionnaire.freq_daily")}</option>
              </select>
            </div>
            <Field
              id="tobacco_smokeless_years"
              label={t("questionnaire.smokeless_years_label")}
              type="number"
              min={0}
              max={100}
              value={formData.tobacco_smokeless_years}
              onChange={(e) => handleNumberChange("tobacco_smokeless_years", parseInt(e.target.value, 10))}
            />
          </div>

          {/* Areca Nut */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label htmlFor="areca_nut_frequency" className="block text-xs font-semibold text-ink mb-1">
                {t("questionnaire.areca_frequency_label")}
              </label>
              <select
                id="areca_nut_frequency"
                value={formData.areca_nut_frequency}
                onChange={(e) => handleFrequencyChange("areca_nut_frequency", e.target.value as Frequency)}
                className="w-full p-2 text-xs bg-white border border-rule rounded-control"
              >
                <option value="never">{t("questionnaire.freq_never")}</option>
                <option value="occasional">{t("questionnaire.freq_occasional")}</option>
                <option value="daily">{t("questionnaire.freq_daily")}</option>
              </select>
            </div>
            <Field
              id="areca_nut_years"
              label={t("questionnaire.areca_years_label")}
              type="number"
              min={0}
              max={100}
              value={formData.areca_nut_years}
              onChange={(e) => handleNumberChange("areca_nut_years", parseInt(e.target.value, 10))}
            />
          </div>

          {/* Betel Quid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label htmlFor="betel_quid_frequency" className="block text-xs font-semibold text-ink mb-1">
                {t("questionnaire.betel_frequency_label")}
              </label>
              <select
                id="betel_quid_frequency"
                value={formData.betel_quid_frequency}
                onChange={(e) => handleFrequencyChange("betel_quid_frequency", e.target.value as Frequency)}
                className="w-full p-2 text-xs bg-white border border-rule rounded-control"
              >
                <option value="never">{t("questionnaire.freq_never")}</option>
                <option value="occasional">{t("questionnaire.freq_occasional")}</option>
                <option value="daily">{t("questionnaire.freq_daily")}</option>
              </select>
            </div>
            <Field
              id="betel_quid_years"
              label={t("questionnaire.betel_years_label")}
              type="number"
              min={0}
              max={100}
              value={formData.betel_quid_years}
              onChange={(e) => handleNumberChange("betel_quid_years", parseInt(e.target.value, 10))}
            />
          </div>
        </fieldset>

        {/* SECTION 6: ALCOHOL EXPOSURE */}
        <fieldset className="bg-white p-4 border border-rule space-y-2">
          <legend className="text-sm font-bold text-ink border-b border-rule pb-1 w-full">
            6. {t("questionnaire.alcohol_section_title")}
          </legend>
          <div>
            <label htmlFor="alcohol_frequency" className="block text-xs font-semibold text-ink mb-1">
              {t("questionnaire.alcohol_frequency_label")}
            </label>
            <select
              id="alcohol_frequency"
              value={formData.alcohol_frequency}
              onChange={(e) => handleFrequencyChange("alcohol_frequency", e.target.value as Frequency)}
              className="w-full sm:w-1/2 p-2 text-xs bg-white border border-rule rounded-control"
            >
              <option value="never">{t("questionnaire.freq_never")}</option>
              <option value="occasional">{t("questionnaire.freq_occasional")}</option>
              <option value="daily">{t("questionnaire.freq_daily")}</option>
            </select>
          </div>
        </fieldset>

        {/* Form Actions */}
        <div className="pt-2 flex flex-col sm:flex-row gap-3">
          <Button
            type="submit"
            variant="primary"
            disabled={isSubmitting}
            className="flex-1 justify-center py-3"
          >
            {isSubmitting ? t("questionnaire.saving") : t("questionnaire.save_button")}
          </Button>
          <Button
            type="button"
            variant="secondary"
            onClick={() => navigate(`/cases/${caseId}/capture`)}
            className="justify-center"
          >
            Back to photos
          </Button>
        </div>
      </form>
    </div>
  );
};
