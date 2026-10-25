import React from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button } from "../components/Button";
import { useAuth } from "../context";
import { t } from "../locales/i18n";

export const ForbiddenPage: React.FC = () => {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleSignOut = async () => {
    await logout();
    navigate("/login", { replace: true });
  };

  const getHomePath = (): string => {
    if (!user) return "/login";
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
    <div className="min-h-screen bg-paper flex flex-col justify-center py-12 sm:px-6 lg:px-8 font-sans text-ink">
      <div className="sm:mx-auto sm:w-full sm:max-w-md">
        <h1 className="text-center font-sans text-3xl font-bold tracking-tight text-ink">
          ONCOLINK
        </h1>
      </div>

      <div className="mt-8 sm:mx-auto sm:w-full sm:max-w-md px-4 sm:px-0">
        <div className="bg-white py-8 px-6 sm:px-10 border border-rule rounded-sm shadow-xs text-center space-y-6">
          <div className="w-12 h-12 mx-auto rounded-full bg-uncertain/15 flex items-center justify-center text-ink font-sans font-bold text-xl">
            !
          </div>

          <div>
            <h2 className="font-sans font-bold text-xl text-ink">
              {t("auth.forbidden_title")}
            </h2>
            <p className="mt-2 text-sm text-ink/70 leading-relaxed">
              {t("auth.forbidden_message")}
            </p>
          </div>

          <div className="pt-2 flex flex-col gap-3 sm:flex-row sm:justify-center">
            <Link to={getHomePath()} className="flex-1">
              <Button variant="primary" className="w-full justify-center">
                {t("auth.go_home")}
              </Button>
            </Link>

            <Button
              variant="secondary"
              onClick={handleSignOut}
              className="flex-1 justify-center"
            >
              {t("auth.sign_out")}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
};
