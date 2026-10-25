import { render } from "@testing-library/react";
import axe from "axe-core";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { setAccessToken } from "../api/client";
import { AuthProvider } from "../context/AuthContext";
import { AdminPage } from "../pages/AdminPage";
import { DoctorHomePage } from "../pages/DoctorHomePage";
import { ForbiddenPage } from "../pages/ForbiddenPage";
import { LoginPage } from "../pages/LoginPage";
import { PatientHomePage } from "../pages/PatientHomePage";
import { RegisterPage } from "../pages/RegisterPage";
import { TwoFactorSetupPage } from "../pages/TwoFactorSetupPage";

const axeOptions = {
  rules: {
    // In JSDOM, canvas is not implemented, so color-contrast rule throws an error
    "color-contrast": { enabled: false },
  },
};

describe("Axe-Core Accessibility Checks on All Screens", () => {
  it("LoginPage has zero accessibility violations", async () => {
    const { container, findByRole } = render(
      <AuthProvider>
        <MemoryRouter>
          <LoginPage />
        </MemoryRouter>
      </AuthProvider>
    );

    await findByRole("button", { name: /Sign in/i });
    const results = await axe.run(container, axeOptions);
    expect(results.violations).toEqual([]);
  });

  it("RegisterPage has zero accessibility violations", async () => {
    const { container, findByText } = render(
      <AuthProvider>
        <MemoryRouter>
          <RegisterPage />
        </MemoryRouter>
      </AuthProvider>
    );

    await findByText(/Informed Consent for Research and Triage/i);
    const results = await axe.run(container, axeOptions);
    expect(results.violations).toEqual([]);
  });

  it("TwoFactorSetupPage has zero accessibility violations", async () => {
    const { container, findByText } = render(
      <AuthProvider>
        <MemoryRouter
          initialEntries={[{ pathname: "/2fa/setup", state: { temp_token: "mock-temp-token-a11y" } }]}
        >
          <TwoFactorSetupPage />
        </MemoryRouter>
      </AuthProvider>
    );

    await findByText(/Set Up Two-Factor Authentication/i);
    const results = await axe.run(container, axeOptions);
    expect(results.violations).toEqual([]);
  });

  it("ForbiddenPage has zero accessibility violations", async () => {
    const { container, findByText } = render(
      <AuthProvider>
        <MemoryRouter>
          <ForbiddenPage />
        </MemoryRouter>
      </AuthProvider>
    );

    await findByText(/Access Restricted/i);
    const results = await axe.run(container, axeOptions);
    expect(results.violations).toEqual([]);
  });

  it("PatientHomePage has zero accessibility violations", async () => {
    setAccessToken("mock-patient-access-jwt");
    const { container, findByText } = render(
      <AuthProvider>
        <MemoryRouter>
          <PatientHomePage />
        </MemoryRouter>
      </AuthProvider>
    );

    await findByText(/Patient Screening Portal/i);
    const results = await axe.run(container, axeOptions);
    expect(results.violations).toEqual([]);
  });

  it("DoctorHomePage has zero accessibility violations", async () => {
    setAccessToken("mock-doctor-access-jwt");
    const { container, findByText } = render(
      <AuthProvider>
        <MemoryRouter>
          <DoctorHomePage />
        </MemoryRouter>
      </AuthProvider>
    );

    await findByText(/Clinical Review Workspace/i);
    const results = await axe.run(container, axeOptions);
    expect(results.violations).toEqual([]);
  });

  it("AdminPage has zero accessibility violations", async () => {
    setAccessToken("mock-admin-access-jwt");
    const { container, findByText } = render(
      <AuthProvider>
        <MemoryRouter>
          <AdminPage />
        </MemoryRouter>
      </AuthProvider>
    );

    await findByText(/Administrator Console/i);
    const results = await axe.run(container, axeOptions);
    expect(results.violations).toEqual([]);
  });
});
