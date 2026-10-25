import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import App from "./App";

describe("Frontend Health Page (Restyled with Design System)", () => {
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
                gridfs: { status: "connected", bucket: "case_images", file_count: 0 },
              },
            }),
        })
      )
    );
  });

  it("renders the intended-use notice banner and restyled design components", async () => {
    render(<App />);

    // 1. Intended-use banner
    expect(screen.getByText(/Intended Use Statement/i)).toBeDefined();
    expect(screen.getByText(/ONCOLINK is a research and education prototype/i)).toBeDefined();

    // 2. Health check heading
    expect(screen.getByText(/ONCOLINK Foundation Health Check/i)).toBeDefined();

    // 3. Wait for health check fetch and action button (primary)
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Refresh health status/i })).toBeDefined();
    });

    // 4. Wait for services to display in DataTable
    await waitFor(() => {
      expect(screen.getByText(/MongoDB Database/i)).toBeDefined();
      expect(screen.getByText(/GridFS Storage/i)).toBeDefined();
      expect(screen.getByText(/System Status/i)).toBeDefined();
    });

    // 5. Audit line at bottom
    expect(screen.getByText(/Viewed by System Health Sentinel/i)).toBeDefined();
  });
});
