import React from "react";
import type { User } from "../api/types";
import { AuthContext, type AuthContextType } from "../context/auth-context-def";
import { AdminPage } from "./AdminPage";
import { CoordinatorHomePage } from "./CoordinatorHomePage";
import { DoctorHomePage } from "./DoctorHomePage";
import { PatientHomePage } from "./PatientHomePage";
import { ScreenerHomePage } from "./ScreenerHomePage";
import { TwoFactorSetupPage } from "./TwoFactorSetupPage";

const dummyAdmin: User = {
  id: "admin-1",
  email: "admin@oncolink.org",
  role: "admin",
  is_active: true,
  is_demo: false,
  created_at: "2026-10-25T10:00:00Z",
  totp_enrolled: true,
};

const dummyDoctor: User = {
  id: "doctor-1",
  email: "dr.sharma@hospital.org",
  role: "doctor",
  is_active: true,
  is_demo: false,
  created_at: "2026-10-25T10:05:00Z",
  registration_number: "MCI-45892",
  verification_status: "pending",
  totp_enrolled: true,
};

const dummyPatient: User = {
  id: "patient-1",
  email: "anita.patel@example.org",
  role: "patient",
  is_active: true,
  is_demo: true,
  created_at: "2026-10-25T10:10:00Z",
  totp_enrolled: false,
};

const dummyScreener: User = {
  id: "screener-1",
  email: "screener.raj@clinic.org",
  role: "screener",
  is_active: true,
  is_demo: false,
  created_at: "2026-10-25T10:15:00Z",
  totp_enrolled: true,
};

const dummyCoordinator: User = {
  id: "coordinator-1",
  email: "coord.verma@district-hospital.org",
  role: "hospital_coordinator",
  is_active: true,
  is_demo: false,
  created_at: "2026-10-25T10:20:00Z",
  totp_enrolled: true,
};

function createMockAuthContext(user: User): AuthContextType {
  return {
    user,
    isLoading: false,
    isAuthenticated: true,
    login: async () => ({}),
    login2fa: async () => ({}),
    logout: async () => {},
    setUser: () => {},
    refreshUser: async () => user,
  };
}

export const DevAdminPreview: React.FC = () => {
  return (
    <AuthContext.Provider value={createMockAuthContext(dummyAdmin)}>
      <AdminPage />
    </AuthContext.Provider>
  );
};

export const DevDoctorPreview: React.FC = () => {
  return (
    <AuthContext.Provider value={createMockAuthContext(dummyDoctor)}>
      <DoctorHomePage />
    </AuthContext.Provider>
  );
};

export const DevPatientPreview: React.FC = () => {
  return (
    <AuthContext.Provider value={createMockAuthContext(dummyPatient)}>
      <PatientHomePage />
    </AuthContext.Provider>
  );
};

export const DevScreenerPreview: React.FC = () => {
  return (
    <AuthContext.Provider value={createMockAuthContext(dummyScreener)}>
      <ScreenerHomePage />
    </AuthContext.Provider>
  );
};

export const DevCoordinatorPreview: React.FC = () => {
  return (
    <AuthContext.Provider value={createMockAuthContext(dummyCoordinator)}>
      <CoordinatorHomePage />
    </AuthContext.Provider>
  );
};

export const DevTwoFactorPreview: React.FC = () => {
  return (
    <AuthContext.Provider value={createMockAuthContext(dummyDoctor)}>
      <TwoFactorSetupPage />
    </AuthContext.Provider>
  );
};
