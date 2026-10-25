import { http, HttpResponse } from "msw";

export const mockUsers = [
  {
    id: "user-admin-1",
    email: "admin@oncolink.org",
    role: "admin",
    is_active: true,
    is_demo: false,
    created_at: "2026-10-25T10:00:00Z",
    registration_number: null,
    verification_status: null,
    totp_enrolled: true,
  },
  {
    id: "user-doctor-1",
    email: "doctor@hospital.org",
    role: "doctor",
    is_active: true,
    is_demo: false,
    created_at: "2026-10-25T10:05:00Z",
    registration_number: "MCI-98765",
    verification_status: "pending",
    totp_enrolled: true,
  },
  {
    id: "user-patient-1",
    email: "patient@example.org",
    role: "patient",
    is_active: true,
    is_demo: true,
    created_at: "2026-10-25T10:10:00Z",
    registration_number: null,
    verification_status: null,
    totp_enrolled: false,
  },
  {
    id: "user-screener-1",
    email: "screener@oncolink.org",
    role: "screener",
    is_active: true,
    is_demo: false,
    created_at: "2026-10-25T10:15:00Z",
    registration_number: null,
    verification_status: null,
    totp_enrolled: false,
  },
];

export const mockConsent = {
  version: "1.0",
  text: "ONCOLINK Research Prototype Consent.\n1. Participation is voluntary.\n2. Data is used for training and validation.\n3. Prototype is not a diagnostic device.",
  updated_at: "2026-10-25T00:00:00Z",
};

export const handlers = [
  // Health
  http.get("http://127.0.0.1:8000/health", () => {
    return HttpResponse.json({ status: "healthy" });
  }),

  http.get("http://127.0.0.1:8000/health/details", () => {
    return HttpResponse.json({
      status: "healthy",
      timestamp: "2026-10-25T12:00:00Z",
      services: {
        mongodb: { status: "connected", replica_set: "rs0" },
        gridfs: { status: "connected", bucket: "case_images", file_count: 0 },
      },
    });
  }),

  // Consent
  http.get("http://127.0.0.1:8000/consent/current", () => {
    return HttpResponse.json(mockConsent);
  }),

  // Auth: Login (Step 1)
  http.post("http://127.0.0.1:8000/auth/login", async ({ request }) => {
    const body = (await request.json()) as { email?: string; password?: string };
    if (body.email === "locked@hospital.org") {
      return HttpResponse.json(
        { detail: "Account is locked until 2026-10-25T12:30:00Z" },
        { status: 401 }
      );
    }
    if (body.email === "doctor@hospital.org" && body.password === "ValidPassword123!") {
      return HttpResponse.json({
        requires_2fa: true,
        temp_token: "temp-doctor-session-token",
      });
    }
    if (body.email === "patient@example.org" && body.password === "ValidPassword123!") {
      return HttpResponse.json({
        access_token: "mock-patient-access-jwt",
        token_type: "bearer",
        requires_2fa: false,
      });
    }
    return HttpResponse.json(
      { detail: "Incorrect email or password" },
      { status: 401 }
    );
  }),

  // Auth: 2FA Login (Step 2)
  http.post("http://127.0.0.1:8000/auth/2fa/login", async ({ request }) => {
    const body = (await request.json()) as {
      temp_token?: string;
      code?: string;
      recovery_code?: string;
    };
    if (body.temp_token === "temp-doctor-session-token" || (body.temp_token && body.temp_token.includes("temp"))) {
      if (body.code === "123456" || body.recovery_code === "RECOV123") {
        return HttpResponse.json({
          access_token: "mock-doctor-access-jwt",
          token_type: "bearer",
        });
      }
      return HttpResponse.json(
        { detail: "Invalid or expired verification code" },
        { status: 401 }
      );
    }
    return HttpResponse.json({ detail: "Invalid session token" }, { status: 401 });
  }),

  // Auth: Refresh
  http.post("http://127.0.0.1:8000/auth/refresh", () => {
    return HttpResponse.json({
      access_token: "mock-refreshed-access-jwt",
      token_type: "bearer",
    });
  }),

  // Auth: Logout
  http.post("http://127.0.0.1:8000/auth/logout", () => {
    return HttpResponse.json({ message: "Logged out successfully" });
  }),

  // Auth: Me
  http.get("http://127.0.0.1:8000/auth/me", ({ request }) => {
    const authHeader = request.headers.get("Authorization");
    if (!authHeader || !authHeader.startsWith("Bearer ")) {
      return HttpResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }
    const token = authHeader.replace("Bearer ", "");
    if (token === "mock-doctor-access-jwt" || token === "mock-refreshed-access-jwt") {
      return HttpResponse.json(mockUsers[1]);
    }
    if (token === "mock-patient-access-jwt") {
      return HttpResponse.json(mockUsers[2]);
    }
    if (token === "mock-admin-access-jwt") {
      return HttpResponse.json(mockUsers[0]);
    }
    if (token === "mock-unverified-doctor-jwt") {
      return HttpResponse.json({
        ...mockUsers[1],
        totp_enrolled: false,
      });
    }
    return HttpResponse.json(mockUsers[0]);
  }),

  // Auth: Register
  http.post("http://127.0.0.1:8000/auth/register", async ({ request }) => {
    const body = (await request.json()) as {
      email: string;
      password?: string;
      date_of_birth?: string;
      consent_version?: string;
      consent_accepted?: boolean;
    };
    if (body.email === "existing@hospital.org") {
      return HttpResponse.json(
        { detail: "An account with this email already exists" },
        { status: 400 }
      );
    }
    return HttpResponse.json({
      access_token: "mock-new-patient-access-jwt",
      token_type: "bearer",
      user_id: "new-patient-999",
      message: "Patient registered successfully",
      date_of_birth: body.date_of_birth,
    });
  }),

  // 2FA: Setup
  http.post("http://127.0.0.1:8000/auth/2fa/setup", () => {
    return HttpResponse.json({
      provisioning_uri: "otpauth://totp/ONCOLINK:doctor%40hospital.org?secret=JBSWY3DPEHPK3PXP&issuer=ONCOLINK",
      secret: "JBSWY3DPEHPK3PXP",
    });
  }),

  // 2FA: Verify Setup
  http.post("http://127.0.0.1:8000/auth/2fa/verify-setup", async ({ request }) => {
    const body = (await request.json()) as { code?: string };
    if (body.code === "123456") {
      return HttpResponse.json({
        message: "Two-factor authentication successfully enabled",
        recovery_codes: [
          "A1B2C3D4",
          "E5F6G7H8",
          "I9J0K1L2",
          "M3N4O5P6",
          "Q7R8S9T0",
          "U1V2W3X4",
          "Y5Z6A7B8",
          "C9D0E1F2",
        ],
      });
    }
    return HttpResponse.json({ detail: "Invalid or expired verification code" }, { status: 400 });
  }),

  // Admin: Get users
  http.get("http://127.0.0.1:8000/admin/users", () => {
    return HttpResponse.json(mockUsers);
  }),

  // Admin: Create staff user
  http.post("http://127.0.0.1:8000/admin/users", async ({ request }) => {
    const body = (await request.json()) as {
      email: string;
      role: string;
      registration_number?: string;
    };
    const newUser = {
      id: `user-new-${Date.now()}`,
      email: body.email,
      role: body.role,
      is_active: true,
      is_demo: false,
      created_at: new Date().toISOString(),
      registration_number: body.registration_number || null,
      verification_status: body.role === "doctor" ? "pending" : null,
      totp_enrolled: false,
    };
    return HttpResponse.json(newUser);
  }),

  // Admin: Verify doctor
  http.patch("http://127.0.0.1:8000/admin/users/:id/verification", async ({ params, request }) => {
    const body = (await request.json()) as { status: string };
    const user = mockUsers.find((u) => u.id === params.id) || mockUsers[1];
    return HttpResponse.json({
      ...user,
      verification_status: body.status,
    });
  }),

  // Admin: Deactivate user
  http.patch("http://127.0.0.1:8000/admin/users/:id/status", async ({ params, request }) => {
    const body = (await request.json()) as { is_active: boolean };
    const user = mockUsers.find((u) => u.id === params.id) || mockUsers[1];
    return HttpResponse.json({
      ...user,
      is_active: body.is_active,
    });
  }),

  // Cases: List
  http.get("http://127.0.0.1:8000/cases", () => {
    return HttpResponse.json([
      {
        id: "case-mock-001",
        reference: "0412-17",
        status: "draft",
        patient_id: "patient-mock-1",
        created_at: "2026-10-25T11:00:00Z",
        updated_at: "2026-10-25T11:00:00Z",
        images: [],
      },
    ]);
  }),

  // Cases: Get one
  http.get("http://127.0.0.1:8000/cases/:id", ({ params }) => {
    return HttpResponse.json({
      id: params.id,
      reference: "0412-17",
      status: "draft",
      patient_id: "patient-mock-1",
      created_at: "2026-10-25T11:00:00Z",
      updated_at: "2026-10-25T11:00:00Z",
      images: [],
    });
  }),

  // Cases: Create
  http.post("http://127.0.0.1:8000/cases", () => {
    return HttpResponse.json({
      id: "case-new-999",
      reference: "0412-99",
      status: "draft",
      patient_id: "patient-mock-1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });
  }),

  // Patients: Create
  http.post("http://127.0.0.1:8000/patients", async ({ request }) => {
    const body = (await request.json()) as { date_of_birth: string; language?: string; contact?: string };
    return HttpResponse.json({
      id: `pat-${Date.now()}`,
      created_by: "user-screener-1",
      date_of_birth: body.date_of_birth,
      language: body.language || "en",
      contact: body.contact || null,
      erased: false,
      is_demo: false,
      created_at: new Date().toISOString(),
    });
  }),

  // Consent: Submit
  http.post("http://127.0.0.1:8000/consent", () => {
    return HttpResponse.json({
      id: "consent-rec-1",
      patient_id: "patient-mock-1",
      version: "1.0",
      language: "en",
      captured_by: "self",
      created_at: new Date().toISOString(),
    });
  }),

  // Cases: Save history
  http.post("http://127.0.0.1:8000/cases/:id/history", ({ params }) => {
    return HttpResponse.json({
      message: "Case history recorded successfully",
      case_id: params.id,
      red_flags: [],
      risk_factors: [],
    });
  }),

  // Cases: Upload image
  http.post("http://127.0.0.1:8000/cases/:id/images", ({ params }) => {
    return HttpResponse.json({
      id: `img-${Date.now()}`,
      case_id: params.id,
      site: "tongue_top",
      view_type: "lesion_closeup",
      storage_id: "gridfs-id-123",
      quality_status: "accepted",
      reason_codes: [],
      quality_scores: { blur: 150, brightness: 120 },
      created_at: new Date().toISOString(),
    });
  }),

  // Cases: Submit
  http.post("http://127.0.0.1:8000/cases/:id/submit", ({ params }) => {
    return HttpResponse.json({
      case_id: params.id,
      status: "queued",
      red_flag: false,
      failed_images: [],
      message: "Case submitted successfully and queued for clinical review",
    });
  }),
];
