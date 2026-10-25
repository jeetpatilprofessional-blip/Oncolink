import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import QRCode from "qrcode";
import { setup2fa, verifySetup2fa } from "../api/client";
import type { TwoFactorSetupResponse } from "../api/types";
import { Button } from "../components/Button";
import { Field } from "../components/Field";
import { useAuth } from "../context";
import { t } from "../locales/i18n";

export const TwoFactorSetupPage: React.FC = () => {
  const { user, refreshUser } = useAuth();
  const navigate = useNavigate();

  const [setupData, setSetupData] = useState<TwoFactorSetupResponse | null>(null);
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([]);
  const [qrSvg, setQrSvg] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [isVerified, setIsVerified] = useState(false);
  const [codesConfirmed, setCodesConfirmed] = useState(false);

  const [isLoading, setIsLoading] = useState(false);
  const [loadingSetup, setLoadingSetup] = useState(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;

    setup2fa()
      .then(async (data) => {
        if (!mounted) return;
        setSetupData(data);
        try {
          const svgString = await QRCode.toString(data.provisioning_uri, {
            type: "svg",
            margin: 1,
            color: { dark: "#18242C", light: "#FFFFFF" },
          });
          if (mounted) {
            setQrSvg(svgString);
          }
        } catch {
          if (mounted) {
            setErrorMsg("Failed to generate local QR code");
          }
        }
      })
      .catch(async (err) => {
        if (!mounted) return;
        if (import.meta.env.DEV) {
          const fallbackData = {
            provisioning_uri: "otpauth://totp/ONCOLINK:doctor%40hospital.org?secret=JBSWY3DPEHPK3PXP&issuer=ONCOLINK",
            secret: "JBSWY3DPEHPK3PXP",
          };
          setSetupData(fallbackData);
          try {
            const svgString = await QRCode.toString(fallbackData.provisioning_uri, {
              type: "svg",
              margin: 1,
              color: { dark: "#18242C", light: "#FFFFFF" },
            });
            if (mounted) setQrSvg(svgString);
          } catch {
            // ignore
          }
        } else {
          setErrorMsg(err instanceof Error ? err.message : t("errors.generic_error"));
        }
      })
      .finally(() => {
        if (mounted) setLoadingSetup(false);
      });

    return () => {
      mounted = false;
    };
  }, []);

  const handleVerify = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!setupData) return;
    setErrorMsg(null);

    if (!code.trim() || code.trim().length !== 6) {
      setErrorMsg(t("errors.invalid_totp"));
      return;
    }

    setIsLoading(true);
    try {
      const res = await verifySetup2fa(code.trim(), setupData.secret);
      setRecoveryCodes(res.recovery_codes || []);
      await refreshUser();
      setIsVerified(true);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : t("errors.invalid_totp"));
    } finally {
      setIsLoading(false);
    }
  };

  const handleDownloadCodes = () => {
    if (recoveryCodes.length === 0) return;
    const blob = new Blob(
      [
        `ONCOLINK Emergency Recovery Codes\nUser: ${user?.email || "Unknown"}\nDate: ${new Date().toISOString()}\n\n` +
          recoveryCodes.join("\n") +
          "\n\nEach code can only be used once. Store this document securely.",
      ],
      { type: "text/plain;charset=utf-8" }
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `oncolink-recovery-codes-${new Date().toISOString().slice(0, 10)}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handlePrintCodes = () => {
    window.print();
  };

  const handleFinish = () => {
    if (user?.role === "admin") {
      navigate("/admin", { replace: true });
    } else if (user?.role === "doctor") {
      navigate("/doctor", { replace: true });
    } else {
      navigate("/", { replace: true });
    }
  };

  return (
    <div className="min-h-screen bg-paper flex flex-col justify-center py-12 sm:px-6 lg:px-8 font-sans text-ink">
      <div className="sm:mx-auto sm:w-full sm:max-w-xl">
        <h1 className="text-center font-serif text-3xl font-bold tracking-tight text-ink">
          ONCOLINK
        </h1>
        <p className="mt-2 text-center text-sm text-ink/70">
          {t("auth.totp_setup_subtitle")}
        </p>
      </div>

      <div className="mt-8 sm:mx-auto sm:w-full sm:max-w-xl px-4 sm:px-0">
        <div className="bg-white py-8 px-6 sm:px-10 border border-rule rounded-sm shadow-xs">
          {errorMsg && (
            <div
              role="alert"
              className="mb-6 p-3 text-sm text-ink bg-urgent/10 border-l-4 border-urgent"
            >
              {errorMsg}
            </div>
          )}

          {loadingSetup ? (
            <div className="text-center py-8 text-sm text-ink/70">
              Generating secure credentials...
            </div>
          ) : !isVerified ? (
            <div className="space-y-6">
              <div>
                <h2 className="font-serif font-bold text-xl text-ink">
                  {t("auth.totp_setup_title")}
                </h2>
                <p className="mt-1 text-xs text-ink/70">
                  {t("auth.scan_qr_instructions")}
                </p>
              </div>

              {/* Local QR Code SVG */}
              <div className="flex justify-center p-4 bg-white border border-rule rounded-xs">
                {qrSvg ? (
                  <div
                    className="w-48 h-48"
                    role="img"
                    aria-label="Authenticator setup QR code"
                    dangerouslySetInnerHTML={{ __html: qrSvg }}
                  />
                ) : (
                  <div className="w-48 h-48 flex items-center justify-center text-xs text-ink/60">
                    Generating QR code...
                  </div>
                )}
              </div>

              <div>
                <p className="text-xs text-ink/70 mb-1.5 font-medium">
                  {t("auth.manual_key_instructions")}
                </p>
                <div className="p-2.5 bg-paper border border-rule rounded-xs font-mono text-xs text-ink select-all text-center tracking-widest font-semibold">
                  {setupData?.secret}
                </div>
              </div>

              <form onSubmit={handleVerify} className="space-y-4 pt-2">
                <Field
                  id="totp-verify-code"
                  label={t("auth.enter_code_instructions")}
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={6}
                  required
                  placeholder="123456"
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                />

                <Button
                  type="submit"
                  variant="primary"
                  disabled={isLoading || code.length !== 6}
                  className="w-full justify-center"
                >
                  {isLoading ? t("auth.verifying") : t("auth.verify_and_enable")}
                </Button>
              </form>
            </div>
          ) : (
            <div className="space-y-6">
              <div>
                <h2 className="font-serif font-bold text-xl text-ink">
                  {t("auth.recovery_codes_title")}
                </h2>
                <div className="mt-2 p-3 text-xs text-ink bg-urgent/10 border-l-4 border-urgent">
                  {t("auth.recovery_codes_warning")}
                </div>
              </div>

              <div
                tabIndex={0}
                aria-label="Emergency recovery codes"
                className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 p-4 bg-paper border border-rule rounded-xs font-mono text-sm font-bold text-ink text-center focus-visible:outline-2 focus-visible:outline-gentian focus-visible:outline-offset-2"
              >
                {recoveryCodes.map((rc, idx) => (
                  <div
                    key={idx}
                    className="p-2 bg-white border border-rule rounded-xs shadow-2xs tracking-wider"
                  >
                    {rc}
                  </div>
                ))}
              </div>

              <div className="flex gap-3">
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  onClick={handleDownloadCodes}
                  className="flex-1 justify-center"
                >
                  {t("auth.download_codes")}
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  onClick={handlePrintCodes}
                  className="flex-1 justify-center"
                >
                  {t("auth.print_codes")}
                </Button>
              </div>

              <div className="flex items-start gap-3 pt-2">
                <input
                  id="recovery-confirmed"
                  type="checkbox"
                  required
                  checked={codesConfirmed}
                  onChange={(e) => setCodesConfirmed(e.target.checked)}
                  className="mt-1 h-4 w-4 rounded-xs border-rule text-gentian focus:ring-2 focus:ring-gentian focus:ring-offset-2"
                />
                <label
                  htmlFor="recovery-confirmed"
                  className="text-xs font-medium text-ink leading-normal select-none"
                >
                  {t("auth.recovery_codes_confirmed")}
                </label>
              </div>

              <Button
                type="button"
                variant="primary"
                disabled={!codesConfirmed}
                onClick={handleFinish}
                className="w-full justify-center"
              >
                {t("auth.continue_button")}
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
