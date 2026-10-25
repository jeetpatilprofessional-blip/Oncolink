import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import axe from "axe-core";
import { DevComponentsPage } from "./DevComponentsPage";

describe("DevComponentsPage Accessibility (Axe-core)", () => {
  it("passes axe accessibility checks without any violations", async () => {
    const { container } = render(<DevComponentsPage />);

    // Run axe accessibility audit on the rendered components page
    const results = await axe.run(container, {
      rules: {
        // In JSDOM, color-contrast can report false positives due to lack of real canvas rendering
        "color-contrast": { enabled: false },
      },
    });

    // Expect zero accessibility violations
    expect(results.violations).toEqual([]);
  });
});
