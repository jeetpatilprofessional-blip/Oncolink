import React from "react";

export interface TimelineItem {
  id: string | number;
  time: string; // 24-hour format, e.g. "14:02" or "2026-10-25 14:02"
  actor: string; // Actor name, e.g. "Dr. A. Rao"
  event: string; // Event description, e.g. "Case reviewed and signed"
  notes?: string;
}

export interface TimelineProps {
  items: TimelineItem[];
  className?: string;
}

/**
 * Vertical Timeline Component adhering to DESIGN.md section 8:
 * - Timestamps strictly in 24-hour time
 * - Explicit actor name for each entry
 * - Clean ruled vertical layout with tabular numerals
 */
export const Timeline: React.FC<TimelineProps> = ({ items, className = "" }) => {
  return (
    <div
      className={`relative pl-6 border-l border-[#D5DAD8] space-y-6 font-sans ${className}`.trim()}
    >
      {items.map((item) => (
        <div key={item.id} className="relative group text-left">
          {/* Node marker on the vertical rule */}
          <span
            aria-hidden="true"
            className="absolute -left-[29px] top-1.5 w-2.5 h-2.5 bg-[#18242C] border-2 border-[#F5F7F6]"
          />
          <div className="flex flex-wrap items-baseline gap-2">
            <span className="text-xs font-semibold tabular-nums text-[#18242C]">{item.time}</span>
            <span className="text-xs text-[#18242C]/70">—</span>
            <span className="text-xs font-medium text-[#4B2E83]">{item.actor}</span>
          </div>
          <p className="text-sm font-medium text-[#18242C] mt-0.5">{item.event}</p>
          {item.notes && (
            <p className="text-xs text-[#18242C]/80 mt-1 leading-relaxed bg-[#F5F7F6] p-2 border border-[#D5DAD8] rounded-[2px]">
              {item.notes}
            </p>
          )}
        </div>
      ))}
    </div>
  );
};
