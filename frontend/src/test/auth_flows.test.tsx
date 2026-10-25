import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { BrowserRouter, MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { apiFetch, getAccessToken, setAccessToken } from "../api/client";
import { AuthProvider } from "../context/AuthContext";
import { LoginPage } from "../pages/LoginPage";
import { RegisterPage } from "../pages/RegisterPage";
import { TwoFactorSetupPage } from "../pages/TwoFactorSetupPage";
import { AppRoutes } from "../App";
import { server } from "./mocks/server";

describe("Authentication Flows & Token Security", () => {
  it("executes two-step login flow (password then TOTP)", async () => {
    render(
      <AuthProvider>
        <MemoryRouter initialEntries={["/login"]}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/" element={<div>Dashboard Home</div>} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    );

    // Step 1: Password authentication
    await waitFor(() => {
      expect(screen.getByLabelText(/Email address/i)).toBeInTheDocument();
    });

    const emailInput = screen.getByLabelText(/Email address/i);
    const passwordInput = screen.getByLabelText(/^Password/i);
    const submitBtn = screen.getByRole("button", { name: /Sign in/i });

    fireEvent.change(emailInput, { target: { value: "doctor@hospital.org" } });
    fireEvent.change(passwordInput, { target: { value: "ValidPassword123!" } });
    fireEvent.click(submitBtn);

    // Step 2: 2FA Prompt
    await waitFor(() => {
      expect(screen.getByText(/Two-Factor Verification/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/Verification code \(6 digits\)/i)).toBeInTheDocument();
    });

    const totpInput = screen.getByLabelText(/Verification code \(6 digits\)/i);
    const verifyBtn = screen.getByRole("button", { name: /Verify and continue/i });

    fireEvent.change(totpInput, { target: { value: "123456" } });
    fireEvent.click(verifyBtn);

    // Successfully transitioned
    await waitFor(() => {
      expect(screen.getByText("Dashboard Home")).toBeInTheDocument();
    });

    // Verify token is in memory and NEVER in web storage
    expect(getAccessToken()).toBe("mock-doctor-access-jwt");
    expect(localStorage.getItem("access_token")).toBeNull();
    expect(localStorage.getItem("token")).toBeNull();
    expect(sessionStorage.getItem("access_token")).toBeNull();
    expect(sessionStorage.getItem("token")).toBeNull();
  });

  it("supports recovery code in step 2 of login", async () => {
    render(
      <AuthProvider>
        <MemoryRouter initialEntries={["/login"]}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/" element={<div>Dashboard Home</div>} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByLabelText(/Email address/i)).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText(/Email address/i), {
      target: { value: "doctor@hospital.org" },
    });
    fireEvent.change(screen.getByLabelText(/^Password/i), {
      target: { value: "ValidPassword123!" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Sign in/i }));

    await waitFor(() => {
      expect(screen.getByText(/Two-Factor Verification/i)).toBeInTheDocument();
    });

    // Toggle to recovery code input
    const toggleBtn = screen.getByRole("button", { name: /Use a recovery code instead/i });
    fireEvent.click(toggleBtn);

    const recoveryInput = screen.getByLabelText(/Recovery code \(8 characters\)/i);
    fireEvent.change(recoveryInput, { target: { value: "RECOV123" } });
    fireEvent.click(screen.getByRole("button", { name: /Verify and continue/i }));

    await waitFor(() => {
      expect(screen.getByText("Dashboard Home")).toBeInTheDocument();
    });
  });

  it("disables registration button until consent checkbox is ticked", async () => {
    render(
      <AuthProvider>
        <BrowserRouter>
          <RegisterPage />
        </BrowserRouter>
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByText(/Informed Consent for Research and Triage/i)).toBeInTheDocument();
    });

    const submitBtn = screen.getByRole("button", { name: /Create patient account/i });
    const consentCheckbox = screen.getByLabelText(
      /I have read and agree to the research consent terms above/i
    );

    // Fill valid registration fields
    fireEvent.change(screen.getByLabelText(/Email address/i), {
      target: { value: "newpatient@example.org" },
    });
    fireEvent.change(screen.getByLabelText(/Date of birth/i), {
      target: { value: "1990-01-01" },
    });
    fireEvent.change(screen.getByLabelText(/^Password/i), {
      target: { value: "SecurePassword123!" },
    });
    fireEvent.change(screen.getByLabelText(/Confirm password/i), {
      target: { value: "SecurePassword123!" },
    });

    // Button MUST remain disabled while consent is unchecked
    expect(consentCheckbox).not.toBeChecked();
    expect(submitBtn).toBeDisabled();

    // Check consent checkbox
    fireEvent.click(consentCheckbox);
    expect(consentCheckbox).toBeChecked();
    expect(submitBtn).not.toBeDisabled();

    // Uncheck consent checkbox
    fireEvent.click(consentCheckbox);
    expect(consentCheckbox).not.toBeChecked();
    expect(submitBtn).toBeDisabled();
  });

  it("rejects an under-18 date with plain message without calling the API", async () => {
    let apiCalled = false;
    server.use(
      http.post("http://127.0.0.1:8000/auth/register", () => {
        apiCalled = true;
        return HttpResponse.json({ user_id: "patient-123" });
      })
    );

    render(
      <AuthProvider>
        <BrowserRouter>
          <RegisterPage />
        </BrowserRouter>
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByText(/Informed Consent for Research and Triage/i)).toBeInTheDocument();
    });

    // Enter under-18 date of birth (e.g., born 16 years ago)
    const today = new Date();
    const minorYear = today.getFullYear() - 16;
    const minorDob = `${minorYear}-05-15`;

    fireEvent.change(screen.getByLabelText(/Email address/i), {
      target: { value: "minor@example.org" },
    });
    fireEvent.change(screen.getByLabelText(/Date of birth/i), {
      target: { value: minorDob },
    });
    fireEvent.change(screen.getByLabelText(/^Password/i), {
      target: { value: "SecurePassword123!" },
    });
    fireEvent.change(screen.getByLabelText(/Confirm password/i), {
      target: { value: "SecurePassword123!" },
    });
    fireEvent.click(
      screen.getByLabelText(/I have read and agree to the research consent terms above/i)
    );

    const submitBtn = screen.getByRole("button", { name: /Create patient account/i });
    expect(submitBtn).not.toBeDisabled();
    fireEvent.click(submitBtn);

    // Verify error message is displayed
    await waitFor(() => {
      expect(screen.getByText("You must be 18 or older to register.")).toBeInTheDocument();
    });

    // API must NEVER have been called
    expect(apiCalled).toBe(false);
  });

  it("includes date_of_birth in the registration request when valid", async () => {
    let capturedBody: Record<string, unknown> | null = null;
    server.use(
      http.post("http://127.0.0.1:8000/auth/register", async ({ request }) => {
        capturedBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({
          user_id: "registered-patient-123",
          message: "Patient registered successfully",
        });
      })
    );

    render(
      <AuthProvider>
        <BrowserRouter>
          <RegisterPage />
        </BrowserRouter>
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByText(/Informed Consent for Research and Triage/i)).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText(/Email address/i), {
      target: { value: "adult@example.org" },
    });
    fireEvent.change(screen.getByLabelText(/Date of birth/i), {
      target: { value: "1990-01-01" },
    });
    fireEvent.change(screen.getByLabelText(/^Password/i), {
      target: { value: "SecurePassword123!" },
    });
    fireEvent.change(screen.getByLabelText(/Confirm password/i), {
      target: { value: "SecurePassword123!" },
    });
    fireEvent.click(
      screen.getByLabelText(/I have read and agree to the research consent terms above/i)
    );

    fireEvent.click(screen.getByRole("button", { name: /Create patient account/i }));

    await waitFor(() => {
      expect(capturedBody).not.toBeNull();
    });

    const body = capturedBody as unknown as Record<string, unknown>;
    expect(body.email).toBe("adult@example.org");
    expect(body.date_of_birth).toBe("1990-01-01");
    expect(body.consent_accepted).toBe(true);
  });

  it("strictly enforces token security: tokens never exist in localStorage or sessionStorage", () => {
    // Assert storage starts completely empty
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);

    setAccessToken("test-secret-token-123");
    expect(getAccessToken()).toBe("test-secret-token-123");

    // Must still be empty
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);

    setAccessToken(null);
    expect(getAccessToken()).toBeNull();
  });

  it("handles single-flight refresh under parallel 401s", async () => {
    let refreshCallCount = 0;

    server.use(
      http.post("http://127.0.0.1:8000/auth/refresh", () => {
        refreshCallCount++;
        return HttpResponse.json({
          access_token: "refreshed-single-flight-token",
          token_type: "bearer",
        });
      }),
      http.get("http://127.0.0.1:8000/test-endpoint", ({ request }) => {
        const auth = request.headers.get("Authorization");
        if (auth !== "Bearer refreshed-single-flight-token") {
          return HttpResponse.json({ detail: "Unauthorized" }, { status: 401 });
        }
        return HttpResponse.json({ success: true });
      })
    );

    setAccessToken("initial-stale-token");

    // Fire 5 concurrent requests that will return 401
    const promises = [
      apiFetch("/test-endpoint"),
      apiFetch("/test-endpoint"),
      apiFetch("/test-endpoint"),
      apiFetch("/test-endpoint"),
      apiFetch("/test-endpoint"),
    ];

    const responses = await Promise.all(promises);

    // All 5 requests should have resolved successfully after retry
    for (const res of responses) {
      expect(res.status).toBe(200);
      const data = await res.json();
      expect(data.success).toBe(true);
    }

    // Crucial requirement: /auth/refresh MUST have been called exactly ONCE (single-flight mutex)
    expect(refreshCallCount).toBe(1);
    expect(getAccessToken()).toBe("refreshed-single-flight-token");
  });

  it("blocks continuation on 2FA setup until recovery codes confirmation checkbox is ticked", async () => {
    render(
      <AuthProvider>
        <MemoryRouter
          initialEntries={[{ pathname: "/2fa/setup", state: { temp_token: "mock-temp-token-valid" } }]}
        >
          <TwoFactorSetupPage />
        </MemoryRouter>
      </AuthProvider>
    );

    // Step 1: wait for QR code and code verification form
    await waitFor(() => {
      expect(screen.getByText(/Set Up Two-Factor Authentication/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/2\. Enter the 6-digit code from your app/i)).toBeInTheDocument();
    });

    const codeInput = screen.getByLabelText(/2\. Enter the 6-digit code from your app/i);
    const verifyBtn = screen.getByRole("button", { name: /Verify & Enable Two-Factor/i });

    fireEvent.change(codeInput, { target: { value: "123456" } });
    fireEvent.click(verifyBtn);

    // Step 2: Emergency Recovery Codes screen appears
    await waitFor(() => {
      expect(screen.getByText(/Emergency Recovery Codes/i)).toBeInTheDocument();
      expect(screen.getByText("A1B2C3D4")).toBeInTheDocument();
    });

    const confirmCheckbox = screen.getByLabelText(
      /I have saved these recovery codes in a safe place/i
    );
    const continueBtn = screen.getByRole("button", { name: /Continue to portal/i });

    // Continue button MUST be disabled until checkbox is checked
    expect(confirmCheckbox).not.toBeChecked();
    expect(continueBtn).toBeDisabled();

    // Check box -> Button becomes enabled
    fireEvent.click(confirmCheckbox);
    expect(confirmCheckbox).toBeChecked();
    expect(continueBtn).not.toBeDisabled();

    // Uncheck box -> Button becomes disabled
    fireEvent.click(confirmCheckbox);
    expect(confirmCheckbox).not.toBeChecked();
    expect(continueBtn).toBeDisabled();
  });

  it("/2fa/setup is reachable only when a temporary token is in navigation state", async () => {
    render(
      <AuthProvider>
        <MemoryRouter
          initialEntries={[{ pathname: "/2fa/setup", state: { temp_token: "mock-temp-token-123" } }]}
        >
          <AppRoutes />
        </MemoryRouter>
      </AuthProvider>
    );

    // Reaches /2fa/setup because temp_token is present in navigation state
    await waitFor(() => {
      expect(screen.getByText(/Set Up Two-Factor Authentication/i)).toBeInTheDocument();
    });
  });

  it("reloading or navigating to /2fa/setup without temporary token sends the user to login", async () => {
    render(
      <AuthProvider>
        <MemoryRouter initialEntries={["/2fa/setup"]}>
          <AppRoutes />
        </MemoryRouter>
      </AuthProvider>
    );

    // Since state is undefined (as happens on browser reload without active session), redirected to /login
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Sign in/i })).toBeInTheDocument();
      expect(screen.getByText(/Sign in to access the ONCOLINK clinical portal/i)).toBeInTheDocument();
      expect(screen.queryByText(/Set Up Two-Factor Authentication/i)).not.toBeInTheDocument();
    });
  });
});
