import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import App from "./App";

describe("Frontend Foundation Smoke Test", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() =>
        Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              status: "healthy",
              timestamp: "2026-10-25T12:00:00Z",
              services: {
                mongodb: { status: "connected", replica_set: "rs0" },
                gridfs: { status: "connected", bucket: "case_images" },
              },
            }),
        })
      )
    );
  });

  it("renders the intended-use notice, health check heading, and gridfs status", async () => {
    render(<App />);

    // Must show intended-use notice
    expect(screen.getByText(/ONCOLINK is a research and education prototype/i)).toBeDefined();

    // Must show foundation heading
    expect(screen.getByText(/ONCOLINK Foundation Health Check/i)).toBeDefined();

    // Must show action button
    expect(screen.getByRole("button", { name: /Refresh Health Status/i })).toBeDefined();

    // Wait for the async health fetch to complete
    await waitFor(() => {
      expect(screen.getByText(/SYSTEM STATUS:/i)).toBeDefined();
      expect(screen.getByText(/GridFS Storage/i)).toBeDefined();
    });
  });
});
