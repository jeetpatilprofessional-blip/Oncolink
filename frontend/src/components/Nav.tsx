import React from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context";
import { t } from "../locales/i18n";
import { Button } from "./Button";

export const Nav: React.FC = () => {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  if (!user) {
    return null;
  }

  const handleSignOut = async () => {
    await logout();
    navigate("/login", { replace: true });
  };

  const getRoleDashboardPath = (): string => {
    switch (user.role) {
      case "patient":
        return "/patient";
      case "screener":
        return "/screener";
      case "doctor":
        return "/doctor";
      case "hospital_coordinator":
        return "/coordinator";
      case "admin":
        return "/admin";
      default:
        return "/login";
    }
  };

  return (
    <header className="bg-white border-b border-rule w-full">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        <div className="flex items-center gap-6">
          <Link
            to={getRoleDashboardPath()}
            className="font-serif font-bold text-xl text-ink tracking-tight hover:text-gentian focus-visible:outline-2 focus-visible:outline-gentian focus-visible:outline-offset-2 rounded-xs"
          >
            ONCOLINK
          </Link>

          <nav aria-label="Portal Navigation" className="hidden sm:flex items-center gap-4">
            {user.role === "patient" && (
              <Link
                to="/patient"
                className="text-sm font-medium text-ink/80 hover:text-gentian focus-visible:outline-2 focus-visible:outline-gentian focus-visible:outline-offset-2 rounded-xs"
              >
                {t("home.patient_title")}
              </Link>
            )}
            {user.role === "screener" && (
              <Link
                to="/screener"
                className="text-sm font-medium text-ink/80 hover:text-gentian focus-visible:outline-2 focus-visible:outline-gentian focus-visible:outline-offset-2 rounded-xs"
              >
                {t("home.screener_title")}
              </Link>
            )}
            {user.role === "doctor" && (
              <Link
                to="/doctor"
                className="text-sm font-medium text-ink/80 hover:text-gentian focus-visible:outline-2 focus-visible:outline-gentian focus-visible:outline-offset-2 rounded-xs"
              >
                {t("home.doctor_title")}
              </Link>
            )}
            {user.role === "hospital_coordinator" && (
              <Link
                to="/coordinator"
                className="text-sm font-medium text-ink/80 hover:text-gentian focus-visible:outline-2 focus-visible:outline-gentian focus-visible:outline-offset-2 rounded-xs"
              >
                {t("home.coordinator_title")}
              </Link>
            )}
            {user.role === "admin" && (
              <Link
                to="/admin"
                className="text-sm font-medium text-ink/80 hover:text-gentian focus-visible:outline-2 focus-visible:outline-gentian focus-visible:outline-offset-2 rounded-xs"
              >
                {t("admin.title")}
              </Link>
            )}
          </nav>
        </div>

        <div className="flex items-center gap-4">
          <div className="text-right hidden sm:block">
            <div className="text-xs text-ink/70 tabular-nums truncate max-w-[200px]" title={user.email}>
              {user.email}
            </div>
            <div className="flex items-center gap-1.5 justify-end">
              <span className="text-[11px] font-medium uppercase tracking-wider text-ink/60 bg-paper px-1.5 py-0.5 rounded-xs border border-rule">
                {user.role.replace("_", " ")}
              </span>
              {user.is_demo && (
                <span className="text-[10px] font-bold text-amber-800 bg-amber-50 px-1 py-0.2 rounded-xs border border-amber-300">
                  DEMO
                </span>
              )}
            </div>
          </div>

          <Button
            variant="secondary"
            size="sm"
            onClick={handleSignOut}
            aria-label={t("auth.sign_out")}
          >
            {t("auth.sign_out")}
          </Button>
        </div>
      </div>
    </header>
  );
};
