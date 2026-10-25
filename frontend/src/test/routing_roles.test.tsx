import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { setAccessToken } from "../api/client";
import { AppRoutes } from "../App";
import { AuthProvider } from "../context/AuthContext";
import { server } from "./mocks/server";
import { mockUsers } from "./mocks/handlers";

describe("Routing, Role Protection & Admin Management", () => {
  it("redirects unauthenticated user from protected route to /login", async () => {
    // Ensure no token and refresh returns 401
    server.use(
      http.post("http://127.0.0.1:8000/auth/refresh", () => {
        return HttpResponse.json({ detail: "No refresh token" }, { status: 401 });
      })
    );
    setAccessToken(null);

    render(
      <AuthProvider>
        <MemoryRouter initialEntries={["/patient"]}>
          <AppRoutes />
        </MemoryRouter>
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Sign in/i })).toBeInTheDocument();
      expect(screen.getByLabelText(/Email address/i)).toBeInTheDocument();
    });
  });

  it("redirects user to /forbidden when accessing route forbidden for their role", async () => {
    // Authenticate as patient
    server.use(
      http.get("http://127.0.0.1:8000/auth/me", () => HttpResponse.json(mockUsers[2])),
      http.post("http://127.0.0.1:8000/auth/refresh", () =>
        HttpResponse.json({ access_token: "mock-patient-access-jwt", token_type: "bearer" })
      )
    );
    setAccessToken("mock-patient-access-jwt");

    render(
      <AuthProvider>
        <MemoryRouter initialEntries={["/admin"]}>
          <AppRoutes />
        </MemoryRouter>
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByText(/Access Restricted/i)).toBeInTheDocument();
      expect(
        screen.getByText(/You do not have permission to access this clinical portal resource/i)
      ).toBeInTheDocument();
    });
  });

  it("redirects doctor without enrolled 2FA to /2fa/setup", async () => {
    server.use(
      http.get("http://127.0.0.1:8000/auth/me", () =>
        HttpResponse.json({ ...mockUsers[1], totp_enrolled: false })
      ),
      http.post("http://127.0.0.1:8000/auth/refresh", () =>
        HttpResponse.json({ access_token: "mock-unverified-doctor-jwt", token_type: "bearer" })
      )
    );
    setAccessToken("mock-unverified-doctor-jwt");

    render(
      <AuthProvider>
        <MemoryRouter initialEntries={["/doctor"]}>
          <AppRoutes />
        </MemoryRouter>
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByText(/Set Up Two-Factor Authentication/i)).toBeInTheDocument();
      expect(
        screen.getByText(/Two-factor authentication is mandatory for clinical and administrative accounts/i)
      ).toBeInTheDocument();
    });
  });

  it("renders Admin Console with users table, staff creation form, and deactivation modal", async () => {
    server.use(
      http.get("http://127.0.0.1:8000/auth/me", () => HttpResponse.json(mockUsers[0])),
      http.post("http://127.0.0.1:8000/auth/refresh", () =>
        HttpResponse.json({ access_token: "mock-admin-access-jwt", token_type: "bearer" })
      )
    );
    setAccessToken("mock-admin-access-jwt");

    render(
      <AuthProvider>
        <MemoryRouter initialEntries={["/admin"]}>
          <AppRoutes />
        </MemoryRouter>
      </AuthProvider>
    );

    // 1. Admin title & users table loaded
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /Administrator Console/i })).toBeInTheDocument();
      expect(screen.getByText("doctor@hospital.org")).toBeInTheDocument();
      expect(screen.getByText("patient@example.org")).toBeInTheDocument();
    });

    // 2. Doctor registration number visible
    expect(screen.getByText(/Reg: MCI-98765/i)).toBeInTheDocument();

    // 3. Verify doctor button is present
    const verifyDoctorBtn = screen.getByRole("button", {
      name: /Verify doctor doctor@hospital\.org/i,
    });
    expect(verifyDoctorBtn).toBeInTheDocument();

    // Click verify doctor
    fireEvent.click(verifyDoctorBtn);
    await waitFor(() => {
      expect(screen.getByText(/Doctor account verified successfully/i)).toBeInTheDocument();
    });

    // 4. Deactivation with confirmation step
    const deactivateBtn = screen.getByRole("button", {
      name: /Deactivate user doctor@hospital\.org/i,
    });
    fireEvent.click(deactivateBtn);

    // Modal appears
    await waitFor(() => {
      expect(screen.getByText(/Confirm Account Deactivation/i)).toBeInTheDocument();
      expect(screen.getByText(/Are you sure you want to deactivate account doctor@hospital\.org/i)).toBeInTheDocument();
    });

    const confirmDeactivateBtn = screen.getByRole("button", {
      name: /Confirm Deactivation/i,
    });
    fireEvent.click(confirmDeactivateBtn);

    await waitFor(() => {
      expect(screen.getByText(/Account deactivated successfully/i)).toBeInTheDocument();
    });
  });
});
