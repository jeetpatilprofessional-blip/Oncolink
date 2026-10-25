import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusMarker } from "./StatusMarker";

describe("StatusMarker Component", () => {
  it("shows the filled triangle and the word Urgent for urgent urgency", () => {
    const { container } = render(<StatusMarker urgency="urgent" />);
    expect(screen.getByText("Urgent")).toBeDefined();
    expect(screen.getByRole("status")).toBeDefined();

    // Verify SVG triangle exists with urgent fill #B42318
    const svg = container.querySelector("svg");
    expect(svg).not.toBeNull();
    expect(svg?.getAttribute("fill")).toBe("#B42318");
    const path = container.querySelector("path");
    expect(path?.getAttribute("d")).toBe("M8 2l6 12H2z");
  });

  it("shows the filled diamond and the word Soon for soon urgency", () => {
    const { container } = render(<StatusMarker urgency="soon" />);
    expect(screen.getByText("Soon")).toBeDefined();
    expect(screen.getByRole("status")).toBeDefined();

    const svg = container.querySelector("svg");
    expect(svg?.getAttribute("fill")).toBe("#B7791F");
    const path = container.querySelector("path");
    expect(path?.getAttribute("d")).toBe("M8 1l7 7-7 7-7-7z");
  });

  it("shows the filled circle and the word Routine for routine urgency", () => {
    const { container } = render(<StatusMarker urgency="routine" />);
    expect(screen.getByText("Routine")).toBeDefined();
    expect(screen.getByRole("status")).toBeDefined();

    const svg = container.querySelector("svg");
    expect(svg?.getAttribute("fill")).toBe("#2F7D57");
    const circle = container.querySelector("circle");
    expect(circle).not.toBeNull();
  });

  it("shows the hollow square and the word Uncertain for uncertain urgency", () => {
    const { container } = render(<StatusMarker urgency="uncertain" />);
    expect(screen.getByText("Uncertain")).toBeDefined();
    expect(screen.getByRole("status")).toBeDefined();

    const svg = container.querySelector("svg");
    expect(svg?.getAttribute("fill")).toBe("none");
    expect(svg?.classList.contains("stroke-[#52627A]")).toBe(true);
    const rect = container.querySelector("rect");
    expect(rect).not.toBeNull();
  });
});
