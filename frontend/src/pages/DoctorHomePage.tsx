import React from "react";
import { Banner } from "../components/Banner";
import { Nav } from "../components/Nav";
import { useAuth } from "../context";
import { t } from "../locales/i18n";

export const DoctorHomePage: React.FC = () => {
  const { user } = useAuth();
  const isPending = user?.verification_status === "pending";

  return (
    <div className="min-h-screen bg-paper font-sans text-ink flex flex-col">
      <Nav />
      <main className="max-w-7xl mx-auto w-full px-4 sm:px-6 lg:px-8 py-8 space-y-6">
        <Banner />
        <div className="border-b border-rule pb-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
          <h1 className="font-serif text-2xl font-bold tracking-tight text-ink">
            {t("home.doctor_title")}
          </h1>
          {user?.registration_number && (
            <span className="text-xs tabular-nums text-ink/70 bg-white px-2 py-1 rounded-xs border border-rule self-start sm:self-auto">
              {t("admin.doctor_registration", { reg: user.registration_number })}
            </span>
          )}
        </div>

        {isPending && (
          <div
            role="status"
            className="p-4 bg-uncertain/15 border-l-4 border-uncertain text-sm text-ink"
          >
            <strong>{t("admin.pending")}:</strong> Your medical practitioner registration is awaiting review by a hospital administrator. Clinical sign-off privileges will unlock once verified.
          </div>
        )}

        <div className="bg-white p-6 border border-rule rounded-sm shadow-xs">
          <p className="text-sm text-ink/80 leading-relaxed">
            {t("home.doctor_placeholder")}
          </p>
        </div>
      </main>
    </div>
  );
};
