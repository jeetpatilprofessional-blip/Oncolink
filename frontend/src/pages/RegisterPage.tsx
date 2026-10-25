import React, { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getConsentCurrent, registerPatient } from "../api/client";
import type { ConsentCurrentResponse } from "../api/types";
import { Button } from "../components/Button";
import { Field } from "../components/Field";
import { useAuth } from "../context";
import { t } from "../locales/i18n";

export const RegisterPage: React.FC = () => {
  const { login } = useAuth();
  const navigate = useNavigate();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [dateOfBirth, setDateOfBirth] = useState("");
  const [dobError, setDobError] = useState<string | null>(null);
  const [consent, setConsent] = useState<ConsentCurrentResponse | null>(null);
  const [consentAgreed, setConsentAgreed] = useState(false);

  const [isLoading, setIsLoading] = useState(false);
  const [loadingConsent, setLoadingConsent] = useState(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const calculateAge = (dobString: string): number => {
    if (!dobString) return 0;
    const parts = dobString.split("-").map(Number);
    if (parts.length !== 3 || parts.some(isNaN)) return 0;
    const [year, month, day] = parts as [number, number, number];
    const birthDate = new Date(year, month - 1, day);
    const today = new Date();
    let age = today.getFullYear() - birthDate.getFullYear();
    const monthDiff = today.getMonth() - birthDate.getMonth();
    if (monthDiff < 0 || (monthDiff === 0 && today.getDate() < birthDate.getDate())) {
      age--;
    }
    return age;
  };

  useEffect(() => {
    let mounted = true;
    getConsentCurrent()
      .then((data) => {
        if (mounted) setConsent(data);
      })
      .catch((err) => {
        if (mounted) setErrorMsg(err instanceof Error ? err.message : t("errors.generic_error"));
      })
      .finally(() => {
        if (mounted) setLoadingConsent(false);
      });

    return () => {
      mounted = false;
    };
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);
    setDobError(null);

    if (!email.trim() || !password || !confirmPassword || !dateOfBirth) {
      setErrorMsg(t("errors.field_required"));
      return;
    }

    if (calculateAge(dateOfBirth) < 18) {
      setDobError(t("errors.under_18"));
      return;
    }

    if (password !== confirmPassword) {
      setErrorMsg(t("auth.passwords_must_match"));
      return;
    }

    if (password.length < 10) {
      setErrorMsg(t("errors.password_too_short"));
      return;
    }

    if (password.toLowerCase() === email.trim().toLowerCase()) {
      setErrorMsg(t("errors.password_equals_email"));
      return;
    }

    if (!consentAgreed || !consent) {
      setErrorMsg(t("auth.consent_checkbox"));
      return;
    }

    setIsLoading(true);
    try {
      await registerPatient(
        email.trim(),
        password,
        dateOfBirth,
        consent.version
      );
      // Automatically log the newly registered patient in
      await login(email.trim(), password);
      navigate("/patient", { replace: true });
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : t("errors.generic_error"));
    } finally {
      setIsLoading(false);
    }
  };

  const isFormValid =
    consentAgreed &&
    email.trim().length > 0 &&
    dateOfBirth.length > 0 &&
    password.length >= 10 &&
    password === confirmPassword &&
    !loadingConsent;

  return (
    <div className="min-h-screen bg-paper flex flex-col justify-center py-12 sm:px-6 lg:px-8 font-sans text-ink">
      <div className="sm:mx-auto sm:w-full sm:max-w-lg">
        <h1 className="text-center font-serif text-3xl font-bold tracking-tight text-ink">
          ONCOLINK
        </h1>
        <p className="mt-2 text-center text-sm text-ink/70">
          {t("auth.register_subtitle")}
        </p>
      </div>

      <div className="mt-8 sm:mx-auto sm:w-full sm:max-w-lg px-4 sm:px-0">
        <div className="bg-white py-8 px-6 sm:px-10 border border-rule rounded-sm shadow-xs">
          {errorMsg && (
            <div
              role="alert"
              className="mb-6 p-3 text-sm text-ink bg-urgent/10 border-l-4 border-urgent"
            >
              {errorMsg}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-6">
            <Field
              id="register-email"
              label={t("auth.email_label")}
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />

            <Field
              id="register-dob"
              label={t("auth.date_of_birth_label")}
              type="date"
              required
              value={dateOfBirth}
              error={dobError || undefined}
              onChange={(e) => {
                setDateOfBirth(e.target.value);
                if (dobError) {
                  if (calculateAge(e.target.value) >= 18) {
                    setDobError(null);
                  }
                }
              }}
            />

            <Field
              id="register-password"
              label={t("auth.password_label")}
              type="password"
              required
              autoComplete="new-password"
              hint={t("errors.password_too_short")}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />

            <Field
              id="register-confirm-password"
              label={t("auth.confirm_password_label")}
              type="password"
              required
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
            />

            <div className="space-y-2">
              <label className="block text-sm font-medium text-ink">
                {t("auth.consent_title")} {consent ? `(v${consent.version})` : ""}
              </label>
              <div
                tabIndex={0}
                aria-label={t("auth.consent_title")}
                className="max-h-48 overflow-y-auto p-3.5 bg-paper border border-rule rounded-xs text-xs text-ink/80 leading-relaxed font-serif focus-visible:outline-2 focus-visible:outline-gentian focus-visible:outline-offset-2"
              >
                {loadingConsent ? (
                  <p className="text-ink/60">Loading research consent terms...</p>
                ) : (
                  <div className="whitespace-pre-line">{consent?.text}</div>
                )}
              </div>
            </div>

            <div className="flex items-start gap-3 pt-2">
              <input
                id="consent-agreed"
                type="checkbox"
                required
                checked={consentAgreed}
                onChange={(e) => setConsentAgreed(e.target.checked)}
                className="mt-1 h-4 w-4 rounded-xs border-rule text-gentian focus:ring-2 focus:ring-gentian focus:ring-offset-2"
              />
              <label htmlFor="consent-agreed" className="text-xs text-ink/90 leading-normal select-none">
                {t("auth.consent_checkbox")}
              </label>
            </div>

            <Button
              type="submit"
              variant="primary"
              disabled={!isFormValid || isLoading}
              className="w-full justify-center"
            >
              {isLoading ? t("auth.registering") : t("auth.register_button")}
            </Button>

            <div className="pt-4 text-center border-t border-rule">
              <span className="text-sm text-ink/70">{t("auth.have_account")}{" "}</span>
              <Link
                to="/login"
                className="text-sm font-medium text-gentian hover:underline focus-visible:outline-2 focus-visible:outline-gentian focus-visible:outline-offset-2 rounded-xs"
              >
                {t("auth.login_link")}
              </Link>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
};
