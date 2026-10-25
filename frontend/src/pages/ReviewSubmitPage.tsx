import React, { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getCase, submitCase } from "../api/client";
import type {
  CaseStatusResponse,
  CaseSubmitResponse,
  FailedImageSummary,
  ImageSummary,
} from "../api/types";
import { Banner } from "../components/Banner";
import { Button } from "../components/Button";
import { useAuth } from "../context";
import { t } from "../locales/i18n";

export const ReviewSubmitPage: React.FC = () => {
  const { id: caseId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();

  const [caseData, setCaseData] = useState<CaseStatusResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Preconditions state
  const [missingItems, setMissingItems] = useState<string[]>([]);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [submitResult, setSubmitResult] = useState<CaseSubmitResponse | null>(null);

  useEffect(() => {
    if (!caseId) return;
    let isMounted = true;
    setLoading(true);

    getCase(caseId)
      .then((data) => {
        if (!isMounted) return;
        setCaseData(data);
        evaluateClientPreconditions(data.images || []);
      })
      .catch((err) => {
        if (!isMounted) return;
        setErrorMsg(err.message || t("errors.generic_error"));
      })
      .finally(() => {
        if (isMounted) setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [caseId]);

  const evaluateClientPreconditions = (images: ImageSummary[]) => {
    const missing: string[] = [];
    const closeups = images.filter((im) => im.view_type === "lesion_closeup" && im.quality_status === "accepted");
    const contexts = images.filter((im) => im.view_type === "context" && im.quality_status === "accepted");

    if (closeups.length < 1) missing.push("lesion_closeup_image");
    if (contexts.length < 2) missing.push("context_images");

    setMissingItems(missing);
  };

  const handleSubmit = async () => {
    if (!caseId) return;
    setIsSubmitting(true);
    setErrorMsg(null);

    try {
      const res = await submitCase(caseId);
      setSubmitResult(res);
    } catch (err: unknown) {
      if (err && typeof err === "object" && "status" in err && (err as { status: number }).status === 422) {
        const detail = (err as { detail?: { missing_items?: string[] } }).detail;
        if (detail && Array.isArray(detail.missing_items)) {
          setMissingItems(detail.missing_items);
        }
      }
      const msg = err instanceof Error ? err.message : t("errors.generic_error");
      setErrorMsg(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  const images = caseData?.images || [];
  const acceptedCloseups = images.filter((i) => i.view_type === "lesion_closeup" && i.quality_status === "accepted");
  const acceptedContexts = images.filter((i) => i.view_type === "context" && i.quality_status === "accepted");

  if (loading) {
    return (
      <div className="max-w-xl mx-auto p-4 space-y-4">
        <div className="h-8 bg-rule/40 animate-pulse rounded-none" />
        <div className="h-40 bg-rule/30 animate-pulse rounded-none" />
        <div className="h-32 bg-rule/20 animate-pulse rounded-none" />
      </div>
    );
  }

  // RESULT VIEW AFTER SUCCESSFUL SUBMISSION
  if (submitResult) {
    return (
      <div className="max-w-xl mx-auto p-4 pb-12 font-sans space-y-5">
        <Banner />

        <div className="border-b border-rule pb-3">
          <h1 className="font-sans text-2xl font-bold text-ink">
            {t("review.submitted_title")}
          </h1>
          <p className="text-xs text-ink/70 mt-1">
            Case Reference: <strong className="tabular-nums">{caseData?.reference || caseId}</strong>
          </p>
        </div>

        {/* Emergency Alert Banner if red flag detected */}
        {submitResult.red_flag && (
          <div
            role="alert"
            aria-live="assertive"
            className="p-4 bg-urgent/15 border-l-4 border-urgent text-ink space-y-1.5"
          >
            <div className="font-bold text-sm text-urgent uppercase tracking-wide">
              {t("review.emergency_result_title")}
            </div>
            <p className="text-xs leading-relaxed font-medium">
              {t("review.emergency_result_body")}
            </p>
          </div>
        )}

        {/* Status Confirmation Box */}
        <div className="p-4 bg-white border border-rule space-y-2">
          <div className="text-xs uppercase font-bold text-ink/70">Case Status</div>
          <div className="text-base font-bold text-ink flex items-center gap-2">
            <span>●</span>
            <span>
              {submitResult.status === "queued" && t("review.status_queued")}
              {submitResult.status === "needs_retake" && t("review.status_needs_retake")}
              {submitResult.status !== "queued" && submitResult.status !== "needs_retake" && submitResult.status}
            </span>
          </div>
          <p className="text-xs text-ink/80 leading-relaxed">{submitResult.message}</p>
        </div>

        {/* Failed Images Requiring Retake */}
        {submitResult.failed_images && submitResult.failed_images.length > 0 && (
          <div className="p-4 bg-paper border border-rule space-y-3">
            <h2 className="text-sm font-bold text-urgent uppercase tracking-wide">
              {t("review.failed_images_title")} ({submitResult.failed_images.length})
            </h2>
            <div className="space-y-2">
              {submitResult.failed_images.map((failed: FailedImageSummary) => (
                <div
                  key={failed.id}
                  className="p-3 bg-white border border-rule flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2"
                >
                  <div className="space-y-0.5">
                    <div className="font-semibold text-xs text-ink">
                      {t(`sites.${failed.site}`)} — {t(`capture.${failed.view_type}`)}
                    </div>
                    <div className="text-[11px] text-urgent font-medium">
                      {failed.reason_codes.map((rc) => t(`capture.reasons.${rc}`)).join(" ")}
                    </div>
                  </div>
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    onClick={() =>
                      navigate(`/cases/${caseId}/capture?site=${failed.site}&view_type=${failed.view_type}`)
                    }
                  >
                    {t("review.retake_button")}
                  </Button>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="pt-2">
          <Button
            type="button"
            variant="primary"
            onClick={() => navigate(user?.role === "screener" ? "/screener" : "/patient")}
            className="w-full justify-center py-3"
          >
            {t("review.return_home")}
          </Button>
        </div>
      </div>
    );
  }

  // CHECKLIST AND SUBMISSION VIEW
  return (
    <div className="max-w-xl mx-auto p-4 pb-12 font-sans space-y-5">
      <Banner />

      <div className="border-b border-rule pb-3 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1">
        <div>
          <span className="text-xs uppercase tracking-wider text-ink/70">
            {user?.role === "screener" ? "Screener Intake" : "Patient Self-Screening"}
          </span>
          <h1 className="font-sans text-xl sm:text-2xl font-bold text-ink">
            {t("review.title")}
          </h1>
          <p className="text-xs text-ink/70 mt-0.5">
            Case Ref: <strong className="tabular-nums">{caseData?.reference || caseId}</strong>
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <Link to={`/cases/${caseId}/capture`} className="text-gentian hover:underline font-medium">
            Photos
          </Link>
          <span className="text-rule">|</span>
          <Link to={`/cases/${caseId}/history`} className="text-gentian hover:underline font-medium">
            Questionnaire
          </Link>
        </div>
      </div>

      {errorMsg && (
        <div role="alert" className="p-3 bg-urgent/10 border-l-4 border-urgent text-xs text-ink">
          {errorMsg}
        </div>
      )}

      {/* Preconditions Checklist matching server 422 list */}
      <div className="bg-white p-4 border border-rule space-y-3">
        <h2 className="text-sm font-bold text-ink border-b border-rule pb-1.5">
          {t("review.checklist_title")}
        </h2>

        <ul className="space-y-2 text-xs">
          {/* 1. Informed Consent */}
          <li className="flex items-center justify-between p-2 rounded-control bg-paper">
            <span className="flex items-center gap-2">
              <span className={missingItems.includes("active_consent") ? "text-urgent font-bold" : "text-routine font-bold"}>
                {missingItems.includes("active_consent") ? "✕" : "✓"}
              </span>
              <span className="text-ink">{t("review.item_consent")}</span>
            </span>
            {missingItems.includes("active_consent") && (
              <span className="text-urgent font-medium text-[11px]">
                {t("review.missing_item_active_consent")}
              </span>
            )}
          </li>

          {/* 2. Questionnaire History */}
          <li className="flex items-center justify-between p-2 rounded-control bg-paper">
            <span className="flex items-center gap-2">
              <span className={missingItems.includes("case_history") ? "text-urgent font-bold" : "text-routine font-bold"}>
                {missingItems.includes("case_history") ? "✕" : "✓"}
              </span>
              <span className="text-ink">{t("review.item_history")}</span>
            </span>
            {missingItems.includes("case_history") && (
              <span className="text-urgent font-medium text-[11px]">
                {t("review.missing_item_case_history")}
              </span>
            )}
          </li>

          {/* 3. Lesion Close-up */}
          <li className="flex items-center justify-between p-2 rounded-control bg-paper">
            <span className="flex items-center gap-2">
              <span className={acceptedCloseups.length >= 1 ? "text-routine font-bold" : "text-urgent font-bold"}>
                {acceptedCloseups.length >= 1 ? "✓" : "✕"}
              </span>
              <span className="text-ink">
                {t("review.item_closeup")} (
                <strong className="tabular-nums">{acceptedCloseups.length}</strong>/1)
              </span>
            </span>
            {acceptedCloseups.length < 1 && (
              <Link to={`/cases/${caseId}/capture?view_type=lesion_closeup`} className="text-gentian underline text-[11px] font-medium">
                Add photo
              </Link>
            )}
          </li>

          {/* 4. Context Views */}
          <li className="flex items-center justify-between p-2 rounded-control bg-paper">
            <span className="flex items-center gap-2">
              <span className={acceptedContexts.length >= 2 ? "text-routine font-bold" : "text-urgent font-bold"}>
                {acceptedContexts.length >= 2 ? "✓" : "✕"}
              </span>
              <span className="text-ink">
                {t("review.item_context")} (
                <strong className="tabular-nums">{acceptedContexts.length}</strong>/2)
              </span>
            </span>
            {acceptedContexts.length < 2 && (
              <Link to={`/cases/${caseId}/capture?view_type=context`} className="text-gentian underline text-[11px] font-medium">
                Add photos
              </Link>
            )}
          </li>
        </ul>
      </div>

      {/* Uploaded Images Summary */}
      <div className="bg-white p-4 border border-rule space-y-2">
        <h2 className="text-sm font-bold text-ink">Recorded Case Images ({images.length})</h2>
        {images.length === 0 ? (
          <p className="text-xs text-ink/70">No images uploaded yet.</p>
        ) : (
          <div className="space-y-1.5">
            {images.map((im) => (
              <div
                key={im.id}
                className="flex items-center justify-between text-xs p-2 bg-paper rounded-control border border-rule"
              >
                <span>
                  <strong>{t(`sites.${im.site}`)}</strong> — {t(`capture.${im.view_type}`)}
                </span>
                <span className={im.quality_status === "accepted" ? "text-routine font-bold" : "text-urgent font-bold"}>
                  {im.quality_status === "accepted" ? "✓ Accepted" : "✕ Rejected"}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Submission Action */}
      <div className="pt-2 flex flex-col sm:flex-row gap-3">
        <Button
          type="button"
          variant="primary"
          onClick={handleSubmit}
          disabled={isSubmitting}
          className="flex-1 justify-center py-3 text-base"
        >
          {isSubmitting ? t("review.submitting") : t("review.submit_button")}
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
    </div>
  );
};
