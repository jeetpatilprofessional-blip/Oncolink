import React, { useRef, useState } from "react";
import { type AnatomicalSite, ORDERED_SITES, type SiteMapState } from "../api/types";
import { t } from "../locales/i18n";

export interface OralSiteMapProps {
  siteStates: Partial<Record<AnatomicalSite, SiteMapState>>;
  selectedSite?: AnatomicalSite;
  onSelectSite?: (site: AnatomicalSite) => void;
  interactive?: boolean;
  className?: string;
  showListAlternative?: boolean;
}

/**
 * Drawn SVG tick mark using vector paths (no unicode text glyphs).
 * Color: ink (#18242C).
 */
const SvgTick: React.FC<{ cx: number; cy: number }> = ({ cx, cy }) => (
  <g transform={`translate(${cx}, ${cy})`} className="pointer-events-none" aria-hidden="true">
    <path
      d="M -5 0 L -1 4 L 6 -3"
      fill="none"
      stroke="#18242C"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </g>
);

/**
 * Drawn SVG cross mark using vector paths (no unicode text glyphs).
 * Color: urgent (#B42318).
 */
const SvgCross: React.FC<{ cx: number; cy: number }> = ({ cx, cy }) => (
  <g transform={`translate(${cx}, ${cy})`} className="pointer-events-none" aria-hidden="true">
    <path
      d="M -4 -4 L 4 4 M 4 -4 L -4 4"
      fill="none"
      stroke="#B42318"
      strokeWidth="2.2"
      strokeLinecap="round"
    />
  </g>
);

export const OralSiteMap: React.FC<OralSiteMapProps> = ({
  siteStates,
  selectedSite,
  onSelectSite,
  interactive = true,
  className = "",
  showListAlternative = true,
}) => {
  const [focusedIndex, setFocusedIndex] = useState<number>(0);
  const regionRefs = useRef<(SVGGElement | null)[]>([]);

  const handleKeyDown = (e: React.KeyboardEvent, index: number) => {
    if (!interactive) return;

    let nextIndex = index;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") {
      e.preventDefault();
      nextIndex = (index + 1) % ORDERED_SITES.length;
    } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
      e.preventDefault();
      nextIndex = (index - 1 + ORDERED_SITES.length) % ORDERED_SITES.length;
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      const site = ORDERED_SITES[index];
      if (site) {
        onSelectSite?.(site);
      }
      return;
    }

    if (nextIndex !== index) {
      setFocusedIndex(nextIndex);
      regionRefs.current[nextIndex]?.focus();
    }
  };

  const getRegionState = (site: AnatomicalSite): SiteMapState => {
    return siteStates[site] || "not_captured";
  };

  const getFillStyle = (state: SiteMapState, isSelected: boolean) => {
    if (state === "rejected") {
      return { fill: "url(#site-map-hatch)", stroke: "#B42318", strokeWidth: isSelected ? 3 : 2 };
    }
    if (state === "captured") {
      return {
        fill: "#18242C",
        fillOpacity: 0.12,
        stroke: isSelected ? "#4B2E83" : "#18242C",
        strokeWidth: isSelected ? 3 : 2,
      };
    }
    // not_captured
    return {
      fill: isSelected ? "#4B2E83" : "transparent",
      fillOpacity: isSelected ? 0.08 : 0,
      stroke: isSelected ? "#4B2E83" : "#18242C",
      strokeWidth: isSelected ? 3 : 2,
    };
  };

  const renderRegionIndicator = (state: SiteMapState, cx: number, cy: number) => {
    if (state === "captured") return <SvgTick cx={cx} cy={cy} />;
    if (state === "rejected") return <SvgCross cx={cx} cy={cy} />;
    return null;
  };

  return (
    <div className={`oral-site-map-container flex flex-col items-center w-full max-w-[340px] mx-auto ${className}`}>
      {/* SVG Schematic */}
      <svg
        viewBox="0 0 320 280"
        className="w-full h-auto select-none overflow-visible"
        role="region"
        aria-label="Oral cavity site map"
      >
        <defs>
          <pattern
            id="site-map-hatch"
            width="8"
            height="8"
            patternUnits="userSpaceOnUse"
            patternTransform="rotate(45)"
          >
            <line x1="0" y1="0" x2="0" y2="8" stroke="#B42318" strokeWidth="2.5" />
          </pattern>
        </defs>

        {/* Clinical Outline - Mouth Surround Guide */}
        <ellipse
          cx="160"
          cy="140"
          rx="145"
          ry="125"
          fill="none"
          stroke="#D5DAD8"
          strokeWidth="1.5"
          strokeDasharray="4 4"
        />

        {/* 1. LIPS & GUMS */}
        <g
          ref={(el) => (regionRefs.current[0] = el)}
          role={interactive ? "button" : undefined}
          tabIndex={interactive ? (focusedIndex === 0 ? 0 : -1) : undefined}
          aria-label={`${t("sites.lips_and_gums")}: ${t(`site_states.${getRegionState("lips_and_gums")}`)}`}
          aria-pressed={selectedSite === "lips_and_gums"}
          onClick={() => interactive && onSelectSite?.("lips_and_gums")}
          onKeyDown={(e) => handleKeyDown(e, 0)}
          className={`cursor-pointer transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-gentian ${
            selectedSite === "lips_and_gums" ? "brightness-95" : ""
          }`}
        >
          <path
            d="M 50 38 Q 160 10 270 38 L 260 55 Q 160 30 60 55 Z M 50 242 Q 160 270 270 242 L 260 225 Q 160 250 60 225 Z"
            {...getFillStyle(getRegionState("lips_and_gums"), selectedSite === "lips_and_gums")}
            className="transition-all duration-150"
          />
          <text
            x="160"
            y="262"
            textAnchor="middle"
            className="font-sans text-[11px] font-semibold fill-ink pointer-events-none"
          >
            {t("sites.lips_and_gums")}
          </text>
          {renderRegionIndicator(getRegionState("lips_and_gums"), 160, 246)}
        </g>

        {/* 2. HARD PALATE */}
        <g
          ref={(el) => (regionRefs.current[1] = el)}
          role={interactive ? "button" : undefined}
          tabIndex={interactive ? (focusedIndex === 1 ? 0 : -1) : undefined}
          aria-label={`${t("sites.hard_palate")}: ${t(`site_states.${getRegionState("hard_palate")}`)}`}
          aria-pressed={selectedSite === "hard_palate"}
          onClick={() => interactive && onSelectSite?.("hard_palate")}
          onKeyDown={(e) => handleKeyDown(e, 1)}
          className="cursor-pointer transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-gentian"
        >
          <path
            d="M 105 65 Q 160 40 215 65 L 205 98 Q 160 88 115 98 Z"
            {...getFillStyle(getRegionState("hard_palate"), selectedSite === "hard_palate")}
            className="transition-all duration-150"
          />
          <text
            x="160"
            y="78"
            textAnchor="middle"
            className="font-sans text-[11px] font-semibold fill-ink pointer-events-none"
          >
            {t("sites.hard_palate")}
          </text>
          {renderRegionIndicator(getRegionState("hard_palate"), 160, 62)}
        </g>

        {/* 3. TONGUE TOP */}
        <g
          ref={(el) => (regionRefs.current[2] = el)}
          role={interactive ? "button" : undefined}
          tabIndex={interactive ? (focusedIndex === 2 ? 0 : -1) : undefined}
          aria-label={`${t("sites.tongue_top")}: ${t(`site_states.${getRegionState("tongue_top")}`)}`}
          aria-pressed={selectedSite === "tongue_top"}
          onClick={() => interactive && onSelectSite?.("tongue_top")}
          onKeyDown={(e) => handleKeyDown(e, 2)}
          className="cursor-pointer transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-gentian"
        >
          <path
            d="M 125 106 Q 160 98 195 106 L 190 165 Q 160 174 130 165 Z"
            {...getFillStyle(getRegionState("tongue_top"), selectedSite === "tongue_top")}
            className="transition-all duration-150"
          />
          <text
            x="160"
            y="142"
            textAnchor="middle"
            className="font-sans text-[11px] font-semibold fill-ink pointer-events-none"
          >
            {t("sites.tongue_top")}
          </text>
          {renderRegionIndicator(getRegionState("tongue_top"), 160, 124)}
        </g>

        {/* 4. TONGUE SIDES */}
        <g
          ref={(el) => (regionRefs.current[3] = el)}
          role={interactive ? "button" : undefined}
          tabIndex={interactive ? (focusedIndex === 3 ? 0 : -1) : undefined}
          aria-label={`${t("sites.tongue_sides")}: ${t(`site_states.${getRegionState("tongue_sides")}`)}`}
          aria-pressed={selectedSite === "tongue_sides"}
          onClick={() => interactive && onSelectSite?.("tongue_sides")}
          onKeyDown={(e) => handleKeyDown(e, 3)}
          className="cursor-pointer transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-gentian"
        >
          <path
            d="M 100 115 L 122 108 L 127 165 L 110 185 Z M 220 115 L 198 108 L 193 165 L 210 185 Z"
            {...getFillStyle(getRegionState("tongue_sides"), selectedSite === "tongue_sides")}
            className="transition-all duration-150"
          />
          <text
            x="115"
            y="172"
            textAnchor="middle"
            className="font-sans text-[9px] font-semibold fill-ink pointer-events-none"
          >
            Sides
          </text>
          <text
            x="205"
            y="172"
            textAnchor="middle"
            className="font-sans text-[9px] font-semibold fill-ink pointer-events-none"
          >
            Sides
          </text>
          {renderRegionIndicator(getRegionState("tongue_sides"), 115, 154)}
          {renderRegionIndicator(getRegionState("tongue_sides"), 205, 154)}
        </g>

        {/* 5. FLOOR OF MOUTH */}
        <g
          ref={(el) => (regionRefs.current[4] = el)}
          role={interactive ? "button" : undefined}
          tabIndex={interactive ? (focusedIndex === 4 ? 0 : -1) : undefined}
          aria-label={`${t("sites.floor_of_mouth")}: ${t(`site_states.${getRegionState("floor_of_mouth")}`)}`}
          aria-pressed={selectedSite === "floor_of_mouth"}
          onClick={() => interactive && onSelectSite?.("floor_of_mouth")}
          onKeyDown={(e) => handleKeyDown(e, 4)}
          className="cursor-pointer transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-gentian"
        >
          <path
            d="M 112 188 Q 160 178 208 188 L 195 218 Q 160 228 125 218 Z"
            {...getFillStyle(getRegionState("floor_of_mouth"), selectedSite === "floor_of_mouth")}
            className="transition-all duration-150"
          />
          <text
            x="160"
            y="206"
            textAnchor="middle"
            className="font-sans text-[10px] font-semibold fill-ink pointer-events-none"
          >
            {t("sites.floor_of_mouth")}
          </text>
          {renderRegionIndicator(getRegionState("floor_of_mouth"), 160, 192)}
        </g>

        {/* 6. LEFT CHEEK (Patient Left / Viewer Right) */}
        <g
          ref={(el) => (regionRefs.current[5] = el)}
          role={interactive ? "button" : undefined}
          tabIndex={interactive ? (focusedIndex === 5 ? 0 : -1) : undefined}
          aria-label={`${t("sites.left_cheek")}: ${t(`site_states.${getRegionState("left_cheek")}`)}`}
          aria-pressed={selectedSite === "left_cheek"}
          onClick={() => interactive && onSelectSite?.("left_cheek")}
          onKeyDown={(e) => handleKeyDown(e, 5)}
          className="cursor-pointer transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-gentian"
        >
          <path
            d="M 226 62 Q 295 90 295 145 Q 295 195 226 218 L 216 175 Q 242 145 216 98 Z"
            {...getFillStyle(getRegionState("left_cheek"), selectedSite === "left_cheek")}
            className="transition-all duration-150"
          />
          <text
            x="256"
            y="150"
            textAnchor="middle"
            className="font-sans text-[10px] font-semibold fill-ink pointer-events-none"
          >
            {t("sites.left_cheek")}
          </text>
          {renderRegionIndicator(getRegionState("left_cheek"), 256, 130)}
        </g>

        {/* 7. RIGHT CHEEK (Patient Right / Viewer Left) */}
        <g
          ref={(el) => (regionRefs.current[6] = el)}
          role={interactive ? "button" : undefined}
          tabIndex={interactive ? (focusedIndex === 6 ? 0 : -1) : undefined}
          aria-label={`${t("sites.right_cheek")}: ${t(`site_states.${getRegionState("right_cheek")}`)}`}
          aria-pressed={selectedSite === "right_cheek"}
          onClick={() => interactive && onSelectSite?.("right_cheek")}
          onKeyDown={(e) => handleKeyDown(e, 6)}
          className="cursor-pointer transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-gentian"
        >
          <path
            d="M 94 62 Q 25 90 25 145 Q 25 195 94 218 L 104 175 Q 78 145 104 98 Z"
            {...getFillStyle(getRegionState("right_cheek"), selectedSite === "right_cheek")}
            className="transition-all duration-150"
          />
          <text
            x="64"
            y="150"
            textAnchor="middle"
            className="font-sans text-[10px] font-semibold fill-ink pointer-events-none"
          >
            {t("sites.right_cheek")}
          </text>
          {renderRegionIndicator(getRegionState("right_cheek"), 64, 130)}
        </g>
      </svg>

      {/* Screen reader & plain text alternative list */}
      {showListAlternative && (
        <div className="w-full mt-3 pt-3 border-t border-rule" aria-label="Oral site selection list">
          <p className="sr-only">Plain list alternative for selecting oral examination sites</p>
          <div className="grid grid-cols-1 gap-1.5 w-full">
            {ORDERED_SITES.map((site) => {
              const state = getRegionState(site);
              const isSelected = selectedSite === site;
              return (
                <button
                  key={site}
                  type="button"
                  onClick={() => interactive && onSelectSite?.(site)}
                  className={`w-full flex items-center justify-between px-3 py-2 text-xs text-left rounded-control border transition-colors ${
                    isSelected
                      ? "border-gentian bg-gentian/10 font-bold text-ink"
                      : "border-rule bg-white hover:bg-paper text-ink"
                  } focus-visible:outline-2 focus-visible:outline-gentian focus-visible:outline-offset-2`}
                  aria-pressed={isSelected}
                >
                  <span className="font-medium">{t(`sites.${site}`)}</span>
                  <span className="text-[11px] tabular-nums text-ink/80 flex items-center gap-1.5">
                    {state === "captured" && (
                      <span className="text-ink font-semibold flex items-center gap-1.5" title={t("site_states.captured")}>
                        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="#18242C" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                          <path d="M 2 6 L 5 9 L 10 3" />
                        </svg>
                        <span>{t("site_states.captured")}</span>
                      </span>
                    )}
                    {state === "rejected" && (
                      <span className="text-urgent font-bold flex items-center gap-1.5" title={t("site_states.rejected")}>
                        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="#B42318" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
                          <path d="M 2.5 2.5 L 9.5 9.5 M 9.5 2.5 L 2.5 9.5" />
                        </svg>
                        <span>{t("site_states.rejected")}</span>
                      </span>
                    )}
                    {state === "not_captured" && <span>{t("site_states.not_captured")}</span>}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};
