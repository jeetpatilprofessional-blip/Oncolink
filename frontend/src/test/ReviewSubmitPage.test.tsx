import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import * as clientModule from "../api/client";
import { ApiError } from "../api/client";
import { AuthProvider } from "../context";
import { ReviewSubmitPage } from "../pages/ReviewSubmitPage";

describe("ReviewSubmitPage Component", () => {
  it("renders checklist matching submission preconditions and shows missing warnings on 422 response", async () => {
    // Mock getCase to return a draft case with no images
    vi.spyOn(clientModule, "getCase").mockResolvedValue({
      id: "case-test-123",
      reference: "CASE-0412-17",
      status: "draft",
      patient_id: "patient-123",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      images: [],
    });

    // Mock submitCase to throw 422 with missing items
    vi.spyOn(clientModule, "submitCase").mockRejectedValue(
      new ApiError(422, "Submission preconditions failed", {
        message: "Submission preconditions failed",
        missing_items: ["active_consent", "case_history", "lesion_closeup_image", "context_images"],
      })
    );

    render(
      <AuthProvider>
        <MemoryRouter initialEntries={["/cases/case-test-123/review"]}>
          <Routes>
            <Route path="/cases/:id/review" element={<ReviewSubmitPage />} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    );

    // Initial checklist items
    expect(await screen.findByText(/Submission Requirements/i)).toBeInTheDocument();
    expect(screen.getByText(/Active informed consent recorded/i)).toBeInTheDocument();
    expect(screen.getByText(/Health history questionnaire completed/i)).toBeInTheDocument();
    expect(screen.getByText(/At least one lesion close-up photo accepted/i)).toBeInTheDocument();
    expect(screen.getByText(/At least two context photos accepted/i)).toBeInTheDocument();

    // Trigger Submit
    const submitBtn = screen.getByRole("button", { name: /Submit screening/i });
    fireEvent.click(submitBtn);

    // After 422, missing item labels appear
    expect(await screen.findByText("Active informed consent is missing.")).toBeInTheDocument();
    expect(screen.getByText("Questionnaire history is incomplete.")).toBeInTheDocument();
  });
});
