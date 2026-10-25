import React, { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Button } from "../components/Button";
import { Field } from "../components/Field";
import { useAuth } from "../context";
import { t } from "../locales/i18n";

export const LoginPage: React.FC = () => {
  const { login, login2fa } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  // Step 1 state
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [step, setStep] = useState<1 | 2>(1);
  const [tempToken, setTempToken] = useState<string | null>(null);

  // Step 2 state
  const [totpCode, setTotpCode] = useState("");
  const [recoveryCode, setRecoveryCode] = useState("");
  const [useRecovery, setUseRecovery] = useState(false);

  // UI state
  const [isLoading, setIsLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const handleStep1Submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);

    if (!email.trim() || !password) {
      setErrorMsg(t("errors.field_required"));
      return;
    }

    setIsLoading(true);
    try {
      const res = await login(email.trim(), password);
      if (res.requires_2fa && res.temp_token) {
        setTempToken(res.temp_token);
        if (res.totp_enrolled === false) {
          navigate("/2fa/setup", { state: { temp_token: res.temp_token } });
        } else {
          setStep(2);
        }
      } else {
        redirectAfterLogin();
      }
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : t("errors.generic_error"));
    } finally {
      setIsLoading(false);
    }
  };

  const handleStep2Submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!tempToken) return;

    setErrorMsg(null);
    if (!useRecovery && (!totpCode.trim() || totpCode.trim().length !== 6)) {
      setErrorMsg(t("errors.invalid_totp"));
      return;
    }
    if (useRecovery && (!recoveryCode.trim() || recoveryCode.trim().length !== 8)) {
      setErrorMsg(t("errors.invalid_recovery_code"));
      return;
    }

    setIsLoading(true);
    try {
      await login2fa(
        tempToken,
        useRecovery ? undefined : totpCode.trim(),
        useRecovery ? recoveryCode.trim() : undefined
      );
      redirectAfterLogin();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : t("errors.generic_error"));
    } finally {
      setIsLoading(false);
    }
  };

  const redirectAfterLogin = () => {
    const fromPath = (location.state as { from?: { pathname?: string } })?.from?.pathname;
    if (fromPath && fromPath !== "/login" && fromPath !== "/forbidden") {
      navigate(fromPath, { replace: true });
    } else {
      navigate("/", { replace: true });
    }
  };

  return (
    <div className="min-h-screen bg-paper flex flex-col justify-center py-12 sm:px-6 lg:px-8 font-sans text-ink">
      <div className="sm:mx-auto sm:w-full sm:max-w-md">
        <h1 className="text-center font-serif text-3xl font-bold tracking-tight text-ink">
          ONCOLINK
        </h1>
        <p className="mt-2 text-center text-sm text-ink/70">
          {step === 1 ? t("auth.login_subtitle") : t("auth.step2_subtitle")}
        </p>
      </div>

      <div className="mt-8 sm:mx-auto sm:w-full sm:max-w-md px-4 sm:px-0">
        <div className="bg-white py-8 px-6 sm:px-10 border border-rule rounded-sm shadow-xs">
          {errorMsg && (
            <div
              role="alert"
              className="mb-6 p-3 text-sm text-ink bg-urgent/10 border-l-4 border-urgent"
            >
              {errorMsg}
            </div>
          )}

          {step === 1 ? (
            <form onSubmit={handleStep1Submit} className="space-y-6">
              <Field
                id="login-email"
                label={t("auth.email_label")}
                type="email"
                required
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />

              <Field
                id="login-password"
                label={t("auth.password_label")}
                type="password"
                required
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />

              <Button
                type="submit"
                variant="primary"
                disabled={isLoading}
                className="w-full justify-center"
              >
                {isLoading ? t("auth.signing_in") : t("auth.sign_in_button")}
              </Button>

              <div className="pt-4 text-center border-t border-rule">
                <span className="text-sm text-ink/70">{t("auth.no_account")}{" "}</span>
                <Link
                  to="/register"
                  className="text-sm font-medium text-gentian hover:underline focus-visible:outline-2 focus-visible:outline-gentian focus-visible:outline-offset-2 rounded-xs"
                >
                  {t("auth.register_link")}
                </Link>
              </div>
            </form>
          ) : (
            <form onSubmit={handleStep2Submit} className="space-y-6">
              <h2 className="font-serif font-bold text-lg text-ink">
                {t("auth.step2_title")}
              </h2>

              {!useRecovery ? (
                <Field
                  id="totp-code"
                  label={t("auth.totp_code_label")}
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={6}
                  required
                  placeholder="123456"
                  value={totpCode}
                  onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, ""))}
                />
              ) : (
                <Field
                  id="recovery-code"
                  label={t("auth.recovery_code_label")}
                  type="text"
                  maxLength={8}
                  required
                  placeholder="A1B2C3D4"
                  value={recoveryCode}
                  onChange={(e) => setRecoveryCode(e.target.value)}
                />
              )}

              <div className="flex items-center justify-between text-xs">
                <button
                  type="button"
                  onClick={() => {
                    setUseRecovery(!useRecovery);
                    setErrorMsg(null);
                  }}
                  className="text-gentian hover:underline focus-visible:outline-2 focus-visible:outline-gentian focus-visible:outline-offset-2 rounded-xs"
                >
                  {useRecovery ? t("auth.use_totp_code") : t("auth.use_recovery_code")}
                </button>
              </div>

              <div className="space-y-3">
                <Button
                  type="submit"
                  variant="primary"
                  disabled={isLoading}
                  className="w-full justify-center"
                >
                  {isLoading ? t("auth.verifying") : t("auth.verify_button")}
                </Button>

                <Button
                  type="button"
                  variant="secondary"
                  disabled={isLoading}
                  onClick={() => {
                    setStep(1);
                    setErrorMsg(null);
                  }}
                  className="w-full justify-center"
                >
                  {t("auth.back_to_login")}
                </Button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
};
