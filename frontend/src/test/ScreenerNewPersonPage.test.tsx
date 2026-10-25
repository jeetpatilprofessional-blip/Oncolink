import { fireEvent, render, screen } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import * as clientModule from "../api/client";
import { AuthProvider } from "../context";
import { ScreenerNewPersonPage } from "../pages/ScreenerNewPersonPage";

describe("ScreenerNewPersonPage Component", () => {
  it("rejects under-18 participant client-side without calling createPatient API", async () => {
    const createPatientSpy = vi.spyOn(clientModule, "createPatient");

    render(
      <BrowserRouter>
        <AuthProvider>
          <ScreenerNewPersonPage />
        </AuthProvider>
      </BrowserRouter>
    );

    // Set DOB to 10 years ago (a minor)
    const tenYearsAgo = new Date();
    tenYearsAgo.setFullYear(tenYearsAgo.getFullYear() - 10);
    const dobString = tenYearsAgo.toISOString().split("T")[0];

    const dobInput = screen.getByLabelText(/Date of birth/i);
    fireEvent.change(dobInput, { target: { value: dobString } });

    const submitBtn = screen.getByRole("button", { name: /Save and continue to consent/i });
    fireEvent.click(submitBtn);

    // Under-18 error message shown
    expect(await screen.findByText("You must be 18 or older.")).toBeInTheDocument();

    // API was NOT called
    expect(createPatientSpy).not.toHaveBeenCalled();

    createPatientSpy.mockRestore();
  });
});
