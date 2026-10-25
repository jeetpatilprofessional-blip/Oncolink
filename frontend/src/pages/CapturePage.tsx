import React, { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { getCase, uploadCaseImage } from "../api/client";
import type {
  AnatomicalSite,
  CaseStatusResponse,
  ImageSummary,
  ImageUploadResponse,
  SiteMapState,
  ViewType,
} from "../api/types";
import { Banner } from "../components/Banner";
import { Button } from "../components/Button";
import { OralSiteMap } from "../components/OralSiteMap";
import { useAuth } from "../context";
import { t } from "../locales/i18n";

export const CapturePage: React.FC = () => {
  const { id: caseId } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { user } = useAuth();

  const [caseData, setCaseData] = useState<CaseStatusResponse | null>(null);
  const [loadingCase, setLoadingCase] = useState<boolean>(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Active selections
  const initialSite = (searchParams.get("site") as AnatomicalSite) || "tongue_top";
  const initialView = (searchParams.get("view_type") as ViewType) || "lesion_closeup";
  const [selectedSite, setSelectedSite] = useState<AnatomicalSite>(initialSite);
  const [selectedView, setSelectedView] = useState<ViewType>(initialView);

  // Site map states derived from uploaded images
  const [siteStates, setSiteStates] = useState<Partial<Record<AnatomicalSite, SiteMapState>>>({});
  const [uploadedImages, setUploadedImages] = useState<ImageSummary[]>([]);

  // Camera & stream state
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [cameraAvailable, setCameraAvailable] = useState<boolean>(true);

  // Live quality feedback (advisory only)
  const [lightStatus, setLightStatus] = useState<{ text: string; shape: string }>({
    text: t("capture.live_indicators.light_good"),
    shape: "●",
  });
  const [focusStatus, setFocusStatus] = useState<{ text: string; shape: string }>({
    text: t("capture.live_indicators.focus_sharp"),
    shape: "●",
  });

  // Processing & upload status
  const [isProcessing, setIsProcessing] = useState<boolean>(false);
  const [lastUploadResult, setLastUploadResult] = useState<ImageUploadResponse | null>(null);

  // 1. Fetch case details on mount
  useEffect(() => {
    if (!caseId) return;
    let isMounted = true;
    setLoadingCase(true);

    getCase(caseId)
      .then((data) => {
        if (!isMounted) return;
        setCaseData(data);
        if (data.images) {
          setUploadedImages(data.images);
          const states: Partial<Record<AnatomicalSite, SiteMapState>> = {};
          for (const im of data.images) {
            states[im.site] = im.quality_status === "accepted" ? "captured" : "rejected";
          }
          setSiteStates(states);
        }
      })
      .catch((err) => {
        if (!isMounted) return;
        setErrorMsg(err.message || t("errors.generic_error"));
      })
      .finally(() => {
        if (isMounted) setLoadingCase(false);
      });

    return () => {
      isMounted = false;
    };
  }, [caseId]);

  // 2. Initialize getUserMedia with fallback
  useEffect(() => {
    let activeStream: MediaStream | null = null;

    async function startCamera() {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        setCameraAvailable(false);
        return;
      }
      try {
        const s = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 } },
          audio: false,
        });
        activeStream = s;
        setStream(s);
        setCameraAvailable(true);
        if (videoRef.current) {
          videoRef.current.srcObject = s;
        }
      } catch {
        setCameraAvailable(false);
      }
    }

    startCamera();

    return () => {
      if (activeStream) {
        activeStream.getTracks().forEach((track) => track.stop());
      }
    };
  }, []);

  // 3. Live video frame analysis loop for light and focus
  useEffect(() => {
    if (!cameraAvailable || !stream) return;

    let animId: number;
    let lastCheck = 0;

    const analyzeFrame = (time: number) => {
      if (time - lastCheck > 250 && videoRef.current && canvasRef.current) {
        lastCheck = time;
        const video = videoRef.current;
        const canvas = canvasRef.current;

        if (video.videoWidth > 0 && video.videoHeight > 0) {
          const ctx = canvas.getContext("2d", { willReadFrequently: true });
          if (ctx) {
            canvas.width = 160;
            canvas.height = 120;
            ctx.drawImage(video, 0, 0, 160, 120);
            const imgData = ctx.getImageData(0, 0, 160, 120);
            const data = imgData.data;

            // 1. Mean Luminance
            let totalLum = 0;
            const gray: number[] = new Array(160 * 120);
            for (let i = 0, g = 0; i < data.length; i += 4, g++) {
              const r = data[i] ?? 0;
              const grn = data[i + 1] ?? 0;
              const b = data[i + 2] ?? 0;
              const lum = 0.299 * r + 0.587 * grn + 0.114 * b;
              totalLum += lum;
              gray[g] = lum;
            }
            const meanLum = totalLum / (160 * 120);

            if (meanLum < 55) {
              setLightStatus({ text: t("capture.live_indicators.light_dark"), shape: "▲" });
            } else if (meanLum > 205) {
              setLightStatus({ text: t("capture.live_indicators.light_bright"), shape: "▲" });
            } else {
              setLightStatus({ text: t("capture.live_indicators.light_good"), shape: "●" });
            }

            // 2. Laplacian Variance Estimate for Blur
            let sumLap = 0;
            let sumLapSq = 0;
            let count = 0;
            for (let y = 1; y < 119; y++) {
              for (let x = 1; x < 159; x++) {
                const idx = y * 160 + x;
                const top = gray[idx - 160] ?? 0;
                const bottom = gray[idx + 160] ?? 0;
                const left = gray[idx - 1] ?? 0;
                const right = gray[idx + 1] ?? 0;
                const center = gray[idx] ?? 0;
                const lap = top + bottom + left + right - 4 * center;
                sumLap += lap;
                sumLapSq += lap * lap;
                count++;
              }
            }
            const meanLap = sumLap / count;
            const variance = sumLapSq / count - meanLap * meanLap;

            if (variance < 70) {
              setFocusStatus({ text: t("capture.live_indicators.focus_soft"), shape: "▲" });
            } else {
              setFocusStatus({ text: t("capture.live_indicators.focus_sharp"), shape: "●" });
            }
          }
        }
      }
      animId = requestAnimationFrame(analyzeFrame);
    };

    animId = requestAnimationFrame(analyzeFrame);
    return () => cancelAnimationFrame(animId);
  }, [cameraAvailable, stream]);

  // 4. Compress image on device (max 1600px on long side) and upload
  const handleUploadBlob = async (rawBlob: Blob) => {
    if (!caseId) return;
    setIsProcessing(true);
    setLastUploadResult(null);
    setErrorMsg(null);

    try {
      // Scale down image on offscreen canvas if exceeding 1600px
      const img = new Image();
      const objectUrl = URL.createObjectURL(rawBlob);

      await new Promise<void>((resolve, reject) => {
        img.onload = () => resolve();
        img.onerror = reject;
        img.src = objectUrl;
      });

      const maxDim = 1600;
      let targetW = img.width;
      let targetH = img.height;
      if (targetW > maxDim || targetH > maxDim) {
        if (targetW > targetH) {
          targetH = Math.round((targetH * maxDim) / targetW);
          targetW = maxDim;
        } else {
          targetW = Math.round((targetW * maxDim) / targetH);
          targetH = maxDim;
        }
      }

      const offCanvas = document.createElement("canvas");
      offCanvas.width = targetW;
      offCanvas.height = targetH;
      const offCtx = offCanvas.getContext("2d");
      if (!offCtx) throw new Error("Could not create canvas context for compression");
      offCtx.drawImage(img, 0, 0, targetW, targetH);
      URL.revokeObjectURL(objectUrl);

      const compressedBlob = await new Promise<Blob>((resolve, reject) => {
        offCanvas.toBlob(
          (b) => {
            if (b) resolve(b);
            else reject(new Error("Image compression failed"));
          },
          "image/jpeg",
          0.88
        );
      });

      const result = await uploadCaseImage(caseId, compressedBlob, selectedSite, selectedView);
      setLastUploadResult(result);

      // Update local state
      const newState: SiteMapState = result.quality_status === "accepted" ? "captured" : "rejected";
      setSiteStates((prev) => ({ ...prev, [selectedSite]: newState }));

      // Update uploaded images array
      setUploadedImages((prev) => {
        const filtered = prev.filter((im) => !(im.site === selectedSite && im.view_type === selectedView));
        return [
          ...filtered,
          {
            id: result.id,
            site: result.site,
            view_type: result.view_type,
            quality_status: result.quality_status,
            reason_codes: result.reason_codes,
            created_at: result.created_at,
          },
        ];
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : t("errors.generic_error");
      setErrorMsg(msg);
    } finally {
      setIsProcessing(false);
    }
  };

  // Capture shutter handler (from live video)
  const handleShutter = () => {
    if (!videoRef.current) return;
    const video = videoRef.current;
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth || 1280;
    canvas.height = video.videoHeight || 720;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob(
      (blob) => {
        if (blob) handleUploadBlob(blob);
      },
      "image/jpeg",
      0.95
    );
  };

  // Fallback file input handler
  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      handleUploadBlob(e.target.files[0]);
    }
  };

  // Compute protocol fulfillment counts
  const closeupCount = uploadedImages.filter(
    (im) => im.view_type === "lesion_closeup" && im.quality_status === "accepted"
  ).length;
  const contextCount = uploadedImages.filter(
    (im) => im.view_type === "context" && im.quality_status === "accepted"
  ).length;
  const protocolFulfilled = closeupCount >= 1 && contextCount >= 2;

  if (loadingCase) {
    return (
      <div className="max-w-2xl mx-auto p-4 space-y-4">
        <div className="h-8 bg-rule/40 animate-pulse rounded-none" />
        <div className="h-64 bg-rule/30 animate-pulse rounded-none" />
        <div className="h-40 bg-rule/20 animate-pulse rounded-none" />
      </div>
    );
  }

  return (
    <div className="max-w-xl mx-auto p-4 pb-12 font-sans space-y-5">
      <Banner />

      {/* Header with Case Reference & Step */}
      <div className="border-b border-rule pb-3 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1">
        <div>
          <span className="text-xs uppercase tracking-wider text-ink/70">
            {user?.role === "screener" ? "Screener Intake" : "Patient Self-Screening"}
          </span>
          <h1 className="font-sans text-xl sm:text-2xl font-bold text-ink">
            {t("capture.step_header", {
              reference: caseData?.reference || caseId || "",
              step: "1",
              total: "3",
            })}
          </h1>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <Link
            to={user?.role === "screener" ? "/screener" : "/patient"}
            className="text-gentian hover:underline font-medium"
          >
            Dashboard
          </Link>
          <span className="text-rule">|</span>
          <Link
            to={`/cases/${caseId}/history`}
            className="text-gentian hover:underline font-medium"
          >
            Questionnaire
          </Link>
          <span className="text-rule">|</span>
          <Link
            to={`/cases/${caseId}/review`}
            className="text-gentian hover:underline font-medium"
          >
            Review
          </Link>
        </div>
      </div>

      {errorMsg && (
        <div role="alert" className="p-3 bg-urgent/10 border-l-4 border-urgent text-xs text-ink">
          {errorMsg}
        </div>
      )}

      {/* Protocol Progress Status */}
      <div className="p-3 bg-white border border-rule text-xs space-y-1">
        <div className="font-semibold text-ink">{t("capture.view_type_help")}</div>
        <div className="flex gap-4 text-ink/80 tabular-nums">
          <span>
            Close-up: <strong>{closeupCount}/1</strong> {closeupCount >= 1 ? "✓" : ""}
          </span>
          <span>
            Context views: <strong>{contextCount}/2</strong> {contextCount >= 2 ? "✓" : ""}
          </span>
        </div>
      </div>

      {/* Site Map Signature Component */}
      <div className="bg-white p-4 border border-rule">
        <h2 className="text-sm font-bold text-ink mb-2">1. Select Oral Examination Site</h2>
        <OralSiteMap
          siteStates={siteStates}
          selectedSite={selectedSite}
          onSelectSite={(site) => {
            setSelectedSite(site);
            setLastUploadResult(null);
          }}
        />
      </div>

      {/* View Type Selection */}
      <div className="bg-white p-4 border border-rule space-y-2">
        <label className="block text-xs font-bold text-ink uppercase tracking-wider">
          {t("capture.view_type_label")}
        </label>
        <div className="flex gap-4">
          <label className="flex items-center gap-2 text-sm text-ink cursor-pointer">
            <input
              type="radio"
              name="viewType"
              value="lesion_closeup"
              checked={selectedView === "lesion_closeup"}
              onChange={() => setSelectedView("lesion_closeup")}
              className="accent-gentian"
            />
            {t("capture.lesion_closeup")}
          </label>
          <label className="flex items-center gap-2 text-sm text-ink cursor-pointer">
            <input
              type="radio"
              name="viewType"
              value="context"
              checked={selectedView === "context"}
              onChange={() => setSelectedView("context")}
              className="accent-gentian"
            />
            {t("capture.context")}
          </label>
        </div>
      </div>

      {/* Plain Language Instruction per Site */}
      <div className="p-4 bg-paper border border-rule space-y-1">
        <div className="text-xs uppercase font-bold text-ink/70">
          {t(`sites.${selectedSite}`)}
        </div>
        <p className="text-sm text-ink leading-relaxed font-serif">
          {t(`capture.instructions.${selectedSite}`)}
        </p>
      </div>

      {/* Camera Viewport / Wireframe Box */}
      <div className="bg-[#4A4C4E] p-2 relative overflow-hidden">
        {/* Hidden analysis canvas */}
        <canvas ref={canvasRef} className="hidden" aria-hidden="true" />

        {isProcessing ? (
          <div
            role="status"
            aria-label={t("capture.uploading")}
            className="w-full h-64 bg-rule/30 animate-pulse flex flex-col items-center justify-center text-white text-xs font-sans"
          >
            <div className="h-6 w-32 bg-white/20 mb-2 animate-pulse" />
            <span>{t("capture.uploading")}</span>
          </div>
        ) : cameraAvailable ? (
          <div className="relative w-full h-64 sm:h-72 bg-black flex items-center justify-center overflow-hidden">
            <video
              ref={videoRef}
              autoPlay
              playsInline
              muted
              className="w-full h-full object-cover"
              aria-label="Live camera view"
            />
            {/* Clinical Framing Guide Overlay */}
            <div
              className="absolute inset-4 border-2 border-white/60 pointer-events-none flex flex-col justify-between p-2"
              aria-hidden="true"
            >
              <div className="flex justify-between text-[10px] text-white/80 font-sans tabular-nums">
                <span>[ + ]</span>
                <span>[ + ]</span>
              </div>
              <div className="text-center text-[11px] text-white/70 font-sans tracking-wide">
                Center lesion inside frame
              </div>
              <div className="flex justify-between text-[10px] text-white/80 font-sans tabular-nums">
                <span>[ + ]</span>
                <span>[ + ]</span>
              </div>
            </div>
          </div>
        ) : (
          <div className="w-full h-56 bg-paper border border-rule flex flex-col items-center justify-center p-4 text-center">
            <p className="text-xs text-ink/80 mb-3">{t("capture.camera_unavailable")}</p>
            <label className="inline-flex items-center justify-center px-4 py-2 bg-gentian text-white text-xs font-medium rounded-control cursor-pointer hover:bg-gentian/90">
              {t("capture.choose_file")}
              <input
                type="file"
                accept="image/jpeg,image/png,image/webp"
                capture="environment"
                onChange={handleFileInput}
                className="sr-only"
                aria-label="Upload oral photograph"
              />
            </label>
          </div>
        )}

        {/* Live Light & Focus Indicators (Advisory Only) */}
        {cameraAvailable && !isProcessing && (
          <div className="bg-[#18242C] text-white px-3 py-2 flex items-center justify-between text-xs tabular-nums border-t border-white/10">
            <span className="flex items-center gap-1.5">
              <span>{lightStatus.shape}</span>
              <span>{lightStatus.text}</span>
            </span>
            <span className="flex items-center gap-1.5">
              <span>{focusStatus.shape}</span>
              <span>{focusStatus.text}</span>
            </span>
          </div>
        )}
      </div>

      {/* Shutter & File Fallback Controls */}
      <div className="flex flex-col gap-2">
        {cameraAvailable && (
          <Button
            type="button"
            variant="primary"
            onClick={handleShutter}
            disabled={isProcessing}
            className="w-full justify-center text-base py-3"
          >
            {t("capture.take_photo")}
          </Button>
        )}

        <label className="w-full flex items-center justify-center px-4 py-2.5 bg-white border border-rule text-xs font-medium text-ink rounded-control hover:bg-paper cursor-pointer text-center">
          {t("capture.choose_file")}
          <input
            type="file"
            accept="image/jpeg,image/png,image/webp"
            capture="environment"
            onChange={handleFileInput}
            className="sr-only"
            aria-label="Choose photo file fallback"
          />
        </label>
      </div>

      {/* Quality Gate Server Result Box */}
      {lastUploadResult && (
        <div
          role="status"
          className={`p-4 border-l-4 ${
            lastUploadResult.quality_status === "accepted"
              ? "bg-routine/10 border-routine text-ink"
              : "bg-urgent/10 border-urgent text-ink"
          }`}
        >
          <div className="font-bold text-sm">
            {lastUploadResult.quality_status === "accepted"
              ? t("capture.accepted_title")
              : t("capture.rejected_title")}
          </div>
          <p className="text-xs mt-1 leading-relaxed">
            {lastUploadResult.quality_status === "accepted"
              ? t("capture.accepted_message")
              : lastUploadResult.reason_codes.map((rc) => t(`capture.reasons.${rc}`)).join(" ")}
          </p>

          {lastUploadResult.quality_status === "rejected" && (
            <div className="mt-3">
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => setLastUploadResult(null)}
              >
                {t("capture.retake_photo")}
              </Button>
            </div>
          )}
        </div>
      )}

      {/* Bottom Step Actions */}
      <div className="pt-4 border-t border-rule flex flex-col sm:flex-row gap-3">
        <Button
          type="button"
          variant="primary"
          onClick={() => navigate(`/cases/${caseId}/history`)}
          className="flex-1 justify-center"
        >
          {t("capture.next_questionnaire")}
        </Button>
        {protocolFulfilled && (
          <Button
            type="button"
            variant="secondary"
            onClick={() => navigate(`/cases/${caseId}/review`)}
            className="justify-center"
          >
            {t("capture.review_case")}
          </Button>
        )}
      </div>
    </div>
  );
};
