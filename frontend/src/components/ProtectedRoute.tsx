import React from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";
import type { UserRole } from "../api/types";
import { useAuth } from "../context";

interface ProtectedRouteProps {
  allowedRoles?: UserRole[];
  requireTotp?: boolean;
}

export const ProtectedRoute: React.FC<ProtectedRouteProps> = ({
  allowedRoles,
  requireTotp = true,
}) => {
  const { user, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return (
      <div className="min-h-screen bg-paper flex items-center justify-center font-sans text-ink">
        <p className="text-sm text-ink/70">Loading clinical session...</p>
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  // Doctor and Admin accounts MUST complete 2FA enrollment before accessing protected routes
  const isHighPrivilege = user.role === "doctor" || user.role === "admin";
  if (requireTotp && isHighPrivilege && !user.totp_enrolled && location.pathname !== "/2fa/setup") {
    return <Navigate to="/2fa/setup" replace />;
  }

  if (allowedRoles && !allowedRoles.includes(user.role)) {
    return <Navigate to="/forbidden" replace />;
  }

  return <Outlet />;
};
