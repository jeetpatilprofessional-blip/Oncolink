import { t } from "../locales/i18n";
import type {
  AdminUser,
  ConsentCurrentResponse,
  CreateStaffPayload,
  DoctorVerificationStatus,
  LoginResponse,
  TwoFactorSetupResponse,
  User,
} from "./types";

const API_BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

let inMemoryAccessToken: string | null = null;
let refreshPromise: Promise<string | null> | null = null;
type AuthFailureCallback = () => void;
const authFailureListeners: Set<AuthFailureCallback> = new Set();

export function onAuthFailure(callback: AuthFailureCallback): () => void {
  authFailureListeners.add(callback);
  return () => {
    authFailureListeners.delete(callback);
  };
}

function notifyAuthFailure(): void {
  for (const listener of authFailureListeners) {
    listener();
  }
}

export function setAccessToken(token: string | null): void {
  inMemoryAccessToken = token;
}

export function getAccessToken(): string | null {
  return inMemoryAccessToken;
}

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

/**
 * Executes a single-flight token refresh against /auth/refresh using httpOnly cookie.
 */
export async function refreshSession(): Promise<string | null> {
  if (refreshPromise) {
    return refreshPromise;
  }

  refreshPromise = (async () => {
    try {
      const res = await fetch(`${API_BASE}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
      });

      if (!res.ok) {
        setAccessToken(null);
        return null;
      }

      const data = await res.json();
      const newToken = (data.access_token as string) || null;
      setAccessToken(newToken);
      return newToken;
    } catch {
      setAccessToken(null);
      return null;
    } finally {
      refreshPromise = null;
    }
  })();

  return refreshPromise;
}

/**
 * Core authenticated fetch with single-flight 401 retry.
 */
export async function apiFetch(
  endpoint: string,
  options: RequestInit = {},
  retryOn401 = true
): Promise<Response> {
  const url = endpoint.startsWith("http") ? endpoint : `${API_BASE}${endpoint}`;
  const headers = new Headers(options.headers || {});

  if (!headers.has("Content-Type") && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  if (inMemoryAccessToken && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${inMemoryAccessToken}`);
  }

  const response = await fetch(url, {
    ...options,
    headers,
    credentials: "include",
  });

  const isAuthEndpoint =
    endpoint.includes("/auth/login") ||
    endpoint.includes("/auth/2fa/login") ||
    endpoint.includes("/auth/refresh") ||
    endpoint.includes("/auth/logout");

  if (response.status === 401 && retryOn401 && !isAuthEndpoint) {
    const newToken = await refreshSession();
    if (newToken) {
      headers.set("Authorization", `Bearer ${newToken}`);
      return apiFetch(endpoint, { ...options, headers }, false);
    }
    notifyAuthFailure();
  }

  return response;
}

/**
 * Handle API error payloads and format user-friendly localized messages.
 */
async function parseErrorResponse(res: Response, fallbackKey = "errors.generic_error"): Promise<ApiError> {
  try {
    const data = await res.json();
    let message = t(fallbackKey);

    if (data?.detail) {
      if (typeof data.detail === "string") {
        if (data.detail.toLowerCase().includes("locked")) {
          message = t("errors.account_locked");
        } else if (data.detail.toLowerCase().includes("incorrect email or password")) {
          message = t("errors.invalid_credentials");
        } else if (data.detail.toLowerCase().includes("invalid or expired verification code")) {
          message = t("errors.invalid_totp");
        } else if (data.detail.toLowerCase().includes("invalid recovery code")) {
          message = t("errors.invalid_recovery_code");
        } else if (data.detail.toLowerCase().includes("already exists")) {
          message = t("errors.user_already_exists");
        } else if (data.detail.toLowerCase().includes("cannot deactivate your own account")) {
          message = t("errors.cannot_deactivate_self");
        } else {
          message = data.detail;
        }
      } else if (Array.isArray(data.detail) && data.detail[0]?.msg) {
        message = data.detail[0].msg;
      }
    }
    return new ApiError(res.status, message, data?.detail);
  } catch {
    return new ApiError(res.status, t(fallbackKey));
  }
}

// ---------------------------------------------------------------------------
// Authentication Endpoints
// ---------------------------------------------------------------------------

export async function login(email: string, password: string): Promise<LoginResponse> {
  const res = await apiFetch("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });

  if (!res.ok) {
    throw await parseErrorResponse(res, "errors.invalid_credentials");
  }

  const data: LoginResponse = await res.json();
  if (data.access_token) {
    setAccessToken(data.access_token);
  }
  return data;
}

export async function login2fa(
  tempToken: string,
  code?: string,
  recoveryCode?: string
): Promise<LoginResponse> {
  const res = await apiFetch("/auth/2fa/login", {
    method: "POST",
    body: JSON.stringify({
      temp_token: tempToken,
      code: code ? code.trim() : undefined,
      recovery_code: recoveryCode ? recoveryCode.trim().toUpperCase() : undefined,
    }),
  });

  if (!res.ok) {
    const fallback = recoveryCode ? "errors.invalid_recovery_code" : "errors.invalid_totp";
    throw await parseErrorResponse(res, fallback);
  }

  const data: LoginResponse = await res.json();
  if (data.access_token) {
    setAccessToken(data.access_token);
  }
  return data;
}

export async function registerPatient(
  email: string,
  password: string,
  consentVersionAgreed: string,
  consentTimestamp: string
): Promise<{ message: string; user_id: string }> {
  const res = await apiFetch("/auth/register", {
    method: "POST",
    body: JSON.stringify({
      email,
      password,
      consent_version_agreed: consentVersionAgreed,
      consent_timestamp: consentTimestamp,
    }),
  });

  if (!res.ok) {
    throw await parseErrorResponse(res, "errors.user_already_exists");
  }

  return res.json();
}

export async function logout(): Promise<void> {
  try {
    await apiFetch("/auth/logout", { method: "POST" });
  } finally {
    setAccessToken(null);
  }
}

export async function getMe(): Promise<User> {
  const res = await apiFetch("/auth/me", { method: "GET" });
  if (!res.ok) {
    throw await parseErrorResponse(res, "errors.session_expired");
  }
  return res.json();
}

export async function getConsentCurrent(): Promise<ConsentCurrentResponse> {
  const res = await apiFetch("/consent/current", { method: "GET" });
  if (!res.ok) {
    throw await parseErrorResponse(res);
  }
  return res.json();
}

export async function setup2fa(): Promise<TwoFactorSetupResponse> {
  const res = await apiFetch("/auth/2fa/setup", { method: "POST" });
  if (!res.ok) {
    throw await parseErrorResponse(res);
  }
  return res.json();
}

export async function verifySetup2fa(
  code: string,
  secret: string
): Promise<{ message: string; recovery_codes: string[] }> {
  const res = await apiFetch("/auth/2fa/verify-setup", {
    method: "POST",
    body: JSON.stringify({ code: code.trim(), secret: secret.trim() }),
  });
  if (!res.ok) {
    throw await parseErrorResponse(res, "errors.invalid_totp");
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Admin Endpoints
// ---------------------------------------------------------------------------

export async function getAdminUsers(): Promise<AdminUser[]> {
  const res = await apiFetch("/admin/users", { method: "GET" });
  if (!res.ok) {
    throw await parseErrorResponse(res);
  }
  return res.json();
}

export async function createStaffUser(payload: CreateStaffPayload): Promise<AdminUser> {
  const res = await apiFetch("/admin/users", {
    method: "POST",
    body: JSON.stringify({
      email: payload.email.trim(),
      password: payload.password,
      role: payload.role,
      registration_number: payload.registration_number ? payload.registration_number.trim() : undefined,
    }),
  });
  if (!res.ok) {
    throw await parseErrorResponse(res, "errors.generic_error");
  }
  return res.json();
}

export async function verifyDoctor(
  userId: string,
  status: DoctorVerificationStatus
): Promise<AdminUser> {
  const res = await apiFetch(`/admin/users/${userId}/verification`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
  if (!res.ok) {
    throw await parseErrorResponse(res);
  }
  return res.json();
}

export async function deactivateUser(userId: string): Promise<AdminUser> {
  const res = await apiFetch(`/admin/users/${userId}/status`, {
    method: "PATCH",
    body: JSON.stringify({ is_active: false }),
  });
  if (!res.ok) {
    throw await parseErrorResponse(res);
  }
  return res.json();
}
