export type UserRole = "patient" | "screener" | "doctor" | "hospital_coordinator" | "admin";

export type DoctorVerificationStatus = "pending" | "verified" | "rejected";

export interface User {
  id: string;
  email: string;
  role: UserRole;
  is_active: boolean;
  is_demo: boolean;
  created_at: string;
  registration_number?: string | null;
  verification_status?: DoctorVerificationStatus | null;
  verified_by?: string | null;
  verified_at?: string | null;
  totp_enrolled: boolean;
}

export type AdminUser = User;

export interface LoginResponse {
  access_token?: string;
  token_type?: string;
  requires_2fa?: boolean;
  temp_token?: string;
  totp_enrolled?: boolean;
}

export interface ConsentCurrentResponse {
  version: string;
  text: string;
  updated_at: string;
}

export interface TwoFactorSetupResponse {
  provisioning_uri: string;
  secret: string;
}

export interface TwoFactorVerifySetupResponse {
  message: string;
  recovery_codes: string[];
}

export interface CreateStaffPayload {
  email: string;
  password: string;
  role: "screener" | "doctor" | "hospital_coordinator" | "admin";
  registration_number?: string;
}
