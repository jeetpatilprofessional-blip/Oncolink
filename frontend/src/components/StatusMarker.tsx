import React from "react";
import { t } from "../locales/i18n";

export type TriageUrgency = "urgent" | "soon" | "routine" | "uncertain";

export interface StatusMarkerProps {
  urgency: TriageUrgency;
  className?: string;
  showWord?: boolean;
}

/**
 * StatusMarker Component adhering strictly to DESIGN.md section 3:
 * - Urgent: #B42318, Filled triangle
 * - Soon: #B7791F, Filled diamond
 * - Routine: #2F7D57, Filled circle
 * - Uncertain: #52627A, Hollow square
 *
 * Rules:
 * - Colour is never the only signal. Every state shows its shape and its word.
 * - Triage colours are used for markers only, never for text. Text stays ink (#18242C).
 */
export const StatusMarker: React.FC<StatusMarkerProps> = ({
  urgency,
  className = "",
  showWord = true,
}) => {
  const label = t(`status.${urgency}`);

  const renderShape = () => {
    switch (urgency) {
      case "urgent":
        // Filled triangle (#B42318)
        return (
          <svg
            aria-hidden="true"
            viewBox="0 0 16 16"
            className="w-3 h-3 flex-shrink-0"
            fill="#B42318"
          >
            <path d="M8 2l6 12H2z" />
          </svg>
        );
      case "soon":
        // Filled diamond (#B7791F)
        return (
          <svg
            aria-hidden="true"
            viewBox="0 0 16 16"
            className="w-3 h-3 flex-shrink-0"
            fill="#B7791F"
          >
            <path d="M8 1l7 7-7 7-7-7z" />
          </svg>
        );
      case "routine":
        // Filled circle (#2F7D57)
        return (
          <svg
            aria-hidden="true"
            viewBox="0 0 16 16"
            className="w-3 h-3 flex-shrink-0"
            fill="#2F7D57"
          >
            <circle cx="8" cy="8" r="6" />
          </svg>
        );
      case "uncertain":
        // Hollow square (#52627A)
        return (
          <svg
            aria-hidden="true"
            viewBox="0 0 16 16"
            className="w-3 h-3 flex-shrink-0 stroke-[#52627A]"
            fill="none"
            strokeWidth="2"
          >
            <rect x="2.5" y="2.5" width="11" height="11" />
          </svg>
        );
    }
  };

  return (
    <span
      role="status"
      aria-label={`${label} urgency`}
      className={`inline-flex items-center gap-1.5 font-sans text-sm font-medium text-[#18242C] ${className}`.trim()}
    >
      {renderShape()}
      {showWord && <span className="text-[#18242C]">{label}</span>}
    </span>
  );
};
