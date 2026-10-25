import React from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { AuthProvider, useAuth } from "./context";
import { AdminPage } from "./pages/AdminPage";
import { CoordinatorHomePage } from "./pages/CoordinatorHomePage";
import { DoctorHomePage } from "./pages/DoctorHomePage";
import { ForbiddenPage } from "./pages/ForbiddenPage";
import { HealthPage } from "./pages/HealthPage";
import { LoginPage } from "./pages/LoginPage";
import { PatientHomePage } from "./pages/PatientHomePage";
import { RegisterPage } from "./pages/RegisterPage";
import { ScreenerHomePage } from "./pages/ScreenerHomePage";
import { TwoFactorSetupPage } from "./pages/TwoFactorSetupPage";

const DevComponentsPage = import.meta.env.DEV
  ? React.lazy(() =>
      import("./pages/DevComponentsPage").then((m) => ({
        default: m.DevComponentsPage,
      }))
    )
  : null;

const RootRedirect: React.FC = () => {
  const { user, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="min-h-screen bg-paper flex items-center justify-center font-sans text-ink">
        <p className="text-sm text-ink/70">Connecting to clinical session...</p>
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  if ((user.role === "doctor" || user.role === "admin") && !user.totp_enrolled) {
    return <Navigate to="/login" replace />;
  }

  switch (user.role) {
    case "patient":
      return <Navigate to="/patient" replace />;
    case "screener":
      return <Navigate to="/screener" replace />;
    case "doctor":
      return <Navigate to="/doctor" replace />;
    case "hospital_coordinator":
      return <Navigate to="/coordinator" replace />;
    case "admin":
      return <Navigate to="/admin" replace />;
    default:
      return <Navigate to="/login" replace />;
  }
};

export const AppRoutes: React.FC = () => {
  return (
    <Routes>
      {/* Root redirect */}
      <Route path="/" element={<RootRedirect />} />

      {/* Public Routes */}
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/forbidden" element={<ForbiddenPage />} />
      <Route path="/health" element={<HealthPage />} />

      {/* 2FA Setup Route (requires authenticated user session, bypasses totp_enrolled check) */}
      <Route element={<ProtectedRoute requireTotp={false} />}>
        <Route path="/2fa/setup" element={<TwoFactorSetupPage />} />
      </Route>

      {/* Role-Protected Routes (require totp_enrolled for doctor & admin) */}
      <Route element={<ProtectedRoute allowedRoles={["patient"]} />}>
        <Route path="/patient" element={<PatientHomePage />} />
      </Route>

      <Route element={<ProtectedRoute allowedRoles={["screener"]} />}>
        <Route path="/screener" element={<ScreenerHomePage />} />
      </Route>

      <Route element={<ProtectedRoute allowedRoles={["doctor"]} />}>
        <Route path="/doctor" element={<DoctorHomePage />} />
      </Route>

      <Route element={<ProtectedRoute allowedRoles={["hospital_coordinator"]} />}>
        <Route path="/coordinator" element={<CoordinatorHomePage />} />
      </Route>

      <Route element={<ProtectedRoute allowedRoles={["admin"]} />}>
        <Route path="/admin" element={<AdminPage />} />
      </Route>

      {/* Dev Design System Gallery (development only) */}
      {import.meta.env.DEV && DevComponentsPage && (
        <Route
          path="/dev/components"
          element={
            <React.Suspense fallback={null}>
              <DevComponentsPage />
            </React.Suspense>
          }
        />
      )}

      {/* Fallback */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
};

export const App: React.FC = () => {
  return (
    <AuthProvider>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </AuthProvider>
  );
};

export default App;
