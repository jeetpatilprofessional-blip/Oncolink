import React from "react";
import { t } from "../locales/i18n";

export interface AuditLineProps {
  actor: string;
  time: string; // 24-hour time or date string, e.g. "14:02"
  className?: string;
}

/**
 * AuditLine Component adhering to DESIGN.md section 8:
 * "One line at the foot of a case: who viewed it, when."
 */
export const AuditLine: React.FC<AuditLineProps> = ({ actor, time, className = "" }) => {
  return (
    <footer
      className={`border-t border-[#D5DAD8] pt-2 pb-1 text-xs text-[#18242C]/70 font-sans tabular-nums text-left ${className}`.trim()}
    >
      <span>{t("audit.viewed_by", { actor, time })}</span>
    </footer>
  );
};
