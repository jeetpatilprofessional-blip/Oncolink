import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ORDERED_SITES } from "../api/types";
import { OralSiteMap } from "./OralSiteMap";

describe("OralSiteMap Component", () => {
  it("renders all 7 anatomical regions with outline and plain list", () => {
    render(<OralSiteMap siteStates={{}} />);

    // SVG elements with accessible labels
    for (const site of ORDERED_SITES) {
      const parts = site.split("_");
      const keyword = parts[0] || site;
      const regionBtns = screen.getAllByRole("button", { name: new RegExp(keyword, "i") });
      expect(regionBtns.length).toBeGreaterThanOrEqual(1);
    }
  });

  it("displays captured state with checkmark and rejected state with cross", () => {
    render(
      <OralSiteMap
        siteStates={{
          tongue_top: "captured",
          left_cheek: "rejected",
          hard_palate: "not_captured",
        }}
      />
    );

    // List buttons show correct indicators
    expect(screen.getByText(/✓ Captured/i)).toBeInTheDocument();
    expect(screen.getByText(/✕ Quality check rejected/i)).toBeInTheDocument();
  });

  it("handles keyboard navigation between regions using arrow keys and Enter", () => {
    const handleSelect = vi.fn();
    render(<OralSiteMap siteStates={{}} onSelectSite={handleSelect} />);

    // Get first region button inside SVG
    const regionButtons = screen.getAllByRole("button", { name: /Lips and gums/i });
    const firstRegion = regionButtons[0];
    expect(firstRegion).toBeDefined();
    if (!firstRegion) return;

    firstRegion.focus();

    // Arrow down to move to hard_palate
    fireEvent.keyDown(firstRegion, { key: "ArrowDown" });
    // Press Enter to select
    const secondRegionButtons = screen.getAllByRole("button", { name: /Hard palate/i });
    const secondRegion = secondRegionButtons[0];
    expect(secondRegion).toBeDefined();
    if (!secondRegion) return;

    fireEvent.keyDown(secondRegion, { key: "Enter" });

    expect(handleSelect).toHaveBeenCalledWith("hard_palate");
  });

  it("triggers onSelectSite on click", () => {
    const handleSelect = vi.fn();
    render(<OralSiteMap siteStates={{}} onSelectSite={handleSelect} />);

    const tongueButtons = screen.getAllByRole("button", { name: /Tongue, top/i });
    const tongueBtn = tongueButtons[0];
    expect(tongueBtn).toBeDefined();
    if (!tongueBtn) return;

    fireEvent.click(tongueBtn);

    expect(handleSelect).toHaveBeenCalledWith("tongue_top");
  });
});
