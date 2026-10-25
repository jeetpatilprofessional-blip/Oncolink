import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Field } from "./Field";

describe("Field Component", () => {
  it("links label with input using htmlFor and id", () => {
    render(<Field label="Patient Reference" id="patient-ref" />);

    const label = screen.getByText("Patient Reference");
    const input = screen.getByLabelText("Patient Reference");

    expect(label.getAttribute("for")).toBe("patient-ref");
    expect(input.getAttribute("id")).toBe("patient-ref");
    expect(input.getAttribute("aria-invalid")).toBe("false");
  });

  it("links error message correctly using aria-describedby and sets aria-invalid='true'", () => {
    render(
      <Field
        label="Consult Notes"
        id="consult-notes"
        error="This field is required. Enter a valid value to continue."
        hint="Doctor notes for referral"
      />
    );

    const input = screen.getByLabelText("Consult Notes");
    const errorAlert = screen.getByRole("alert");
    const hint = screen.getByText("Doctor notes for referral");

    expect(errorAlert.getAttribute("id")).toBe("consult-notes-error");
    expect(hint.getAttribute("id")).toBe("consult-notes-hint");

    const describedBy = input.getAttribute("aria-describedby");
    expect(describedBy).toContain("consult-notes-error");
    expect(describedBy).toContain("consult-notes-hint");
    expect(input.getAttribute("aria-invalid")).toBe("true");
  });
});
