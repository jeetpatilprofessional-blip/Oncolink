import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AuthProvider } from "../context";
import { CapturePage } from "../pages/CapturePage";

describe("CapturePage Component", () => {
  it("falls back to file input with capture=environment when getUserMedia is unavailable", async () => {
    // In test jsdom environment, navigator.mediaDevices.getUserMedia is not defined
    render(
      <AuthProvider>
        <MemoryRouter initialEntries={["/cases/case-test-123/capture"]}>
          <Routes>
            <Route path="/cases/:id/capture" element={<CapturePage />} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    );

    // Camera unavailable fallback text and file input are rendered
    expect(
      await screen.findByText(/Camera feed is unavailable. You can choose a photo file directly./i)
    ).toBeInTheDocument();

    const fileInputs = screen.getAllByLabelText(/Choose photo file fallback|Upload oral photograph/i);
    expect(fileInputs.length).toBeGreaterThanOrEqual(1);
    expect(fileInputs[0]).toHaveAttribute("capture", "environment");
  });
});
