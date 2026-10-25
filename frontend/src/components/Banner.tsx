import React from "react";
import { t } from "../locales/i18n";

export interface BannerProps {
  className?: string;
}

/**
 * Intended-use Banner Component.
 * A calm strip with a top and bottom rule per DESIGN.md section 8.
 * Not a dismissible popup; always clearly states the intended use.
 */
export const Banner: React.FC<BannerProps> = ({ className = "" }) => {
  return (
    <aside
      role="region"
      aria-label={t("common.intended_use_title")}
      className={`border-t border-b border-[#D5DAD8] bg-white py-3 px-4 text-left font-sans text-sm leading-relaxed text-[#18242C] ${className}`.trim()}
    >
      <div className="max-w-4xl mx-auto">
        <p className="font-semibold text-[#18242C] mb-0.5">{t("common.intended_use_title")}</p>
        <p className="text-[#18242C]/90">{t("common.intended_use_statement")}</p>
      </div>
    </aside>
  );
};
