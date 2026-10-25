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

export interface PatientRegisterPayload {
  email: string;
  password: string;
  date_of_birth: string;
  consent_version: string;
  consent_accepted: boolean;
}

export interface RegisterResponse {
  access_token: string;
  token_type: string;
  user_id: string;
  requires_2fa?: boolean;
}

// ---------------------------------------------------------------------------
// Screening, Photographic Protocol & Case Types
// ---------------------------------------------------------------------------

export type AnatomicalSite =
  | "left_cheek"
  | "right_cheek"
  | "tongue_top"
  | "tongue_sides"
  | "floor_of_mouth"
  | "hard_palate"
  | "lips_and_gums";

export const ORDERED_SITES: AnatomicalSite[] = [
  "lips_and_gums",
  "hard_palate",
  "tongue_top",
  "tongue_sides",
  "floor_of_mouth",
  "left_cheek",
  "right_cheek",
];

export type ViewType = "lesion_closeup" | "context";

export type QualityStatus = "accepted" | "rejected";

export type SiteMapState = "not_captured" | "captured" | "rejected";

export type UrgencyTier = "urgent" | "soon" | "routine";

export type CaseStatus =
  | "draft"
  | "submitted"
  | "quality_check"
  | "needs_retake"
  | "queued"
  | "ai_analyzed"
  | "under_review"
  | "uncertain_needs_inperson"
  | "signed"
  | "closed_monitor"
  | "referred"
  | "cancelled"
  | "consent_withdrawn";

export interface ImageSummary {
  id: string;
  site: AnatomicalSite;
  view_type: ViewType;
  quality_status: QualityStatus;
  reason_codes: string[];
  created_at?: string;
}

export interface CaseStatusResponse {
  id: string;
  reference: string;
  status: CaseStatus;
  patient_id: string;
  created_at: string;
  updated_at: string;
  images?: ImageSummary[];
  urgency?: UrgencyTier | null;
}

export interface PatientCreatePayload {
  date_of_birth: string;
  language?: string;
  contact?: string;
}

export interface PatientResponse {
  id: string;
  user_id?: string | null;
  created_by?: string;
  date_of_birth: string;
  language: string;
  contact?: string | null;
  erased: boolean;
  is_demo: boolean;
  created_at: string;
}

export interface ConsentSubmitPayload {
  patient_id: string;
  consent_version: string;
  language?: string;
  consent_accepted: boolean;
}

export type Frequency = "never" | "occasional" | "daily";

export interface CaseHistoryPayload {
  tobacco_smoked_frequency: Frequency;
  tobacco_smoked_years: number;
  tobacco_smokeless_frequency: Frequency;
  tobacco_smokeless_years: number;
  areca_nut_frequency: Frequency;
  areca_nut_years: number;
  betel_quid_frequency: Frequency;
  betel_quid_years: number;
  alcohol_frequency: Frequency;
  lesion_duration_weeks: number;
  lesion_pain: boolean;
  lesion_non_healing_two_weeks: boolean;
  lesion_bleeding: boolean;
  lesion_white_or_red_patch: boolean;
  lesion_lump: boolean;
  difficulty_swallowing: boolean;
  difficulty_opening_mouth: boolean;
  difficulty_speaking: boolean;
  unexplained_weight_loss: boolean;
  family_history_cancer: boolean;
  heavy_bleeding: boolean;
  difficulty_breathing: boolean;
  rapid_swelling: boolean;
}

export interface CaseHistoryResponse {
  message: string;
  case_id: string;
  red_flags: string[];
  risk_factors: string[];
}

export interface ImageUploadResponse {
  id: string;
  case_id: string;
  site: AnatomicalSite;
  view_type: ViewType;
  storage_id: string;
  quality_status: QualityStatus;
  reason_codes: string[];
  quality_scores: Record<string, number>;
  created_at: string;
}

export interface FailedImageSummary {
  id: string;
  site: AnatomicalSite;
  view_type: ViewType;
  reason_codes: string[];
}

export interface CaseSubmitResponse {
  case_id: string;
  status: CaseStatus;
  red_flag: boolean;
  failed_images: FailedImageSummary[];
  message: string;
}

