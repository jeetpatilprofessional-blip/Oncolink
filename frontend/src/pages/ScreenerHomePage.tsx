import React from "react";
import { Banner } from "../components/Banner";
import { Nav } from "../components/Nav";
import { t } from "../locales/i18n";

export const ScreenerHomePage: React.FC = () => {
  return (
    <div className="min-h-screen bg-paper font-sans text-ink flex flex-col">
      <Nav />
      <main className="max-w-7xl mx-auto w-full px-4 sm:px-6 lg:px-8 py-8 space-y-6">
        <Banner />
        <div className="border-b border-rule pb-4">
          <h1 className="font-serif text-2xl font-bold tracking-tight text-ink">
            {t("home.screener_title")}
          </h1>
        </div>
        <div className="bg-white p-6 border border-rule rounded-sm shadow-xs">
          <p className="text-sm text-ink/80 leading-relaxed">
            {t("home.screener_placeholder")}
          </p>
        </div>
      </main>
    </div>
  );
};
