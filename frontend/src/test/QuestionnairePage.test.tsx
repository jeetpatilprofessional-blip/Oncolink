import { fireEvent, render, screen } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AuthProvider } from "../context";
import { QuestionnairePage } from "../pages/QuestionnairePage";

describe("QuestionnairePage Component", () => {
  it("does not show the emergency banner initially", () => {
    render(
      <BrowserRouter>
        <AuthProvider>
          <QuestionnairePage />
        </AuthProvider>
      </BrowserRouter>
    );

    expect(screen.queryByText(/Seek in-person medical care now/i)).not.toBeInTheDocument();
  });

  it("immediately displays emergency banner when a red-flag question is answered yes", () => {
    render(
      <BrowserRouter>
        <AuthProvider>
          <QuestionnairePage />
        </AuthProvider>
      </BrowserRouter>
    );

    // Answer heavy bleeding -> Yes
    const heavyBleedingYes = screen.getAllByLabelText(/Yes/i)[0];
    expect(heavyBleedingYes).toBeDefined();
    if (heavyBleedingYes) {
      fireEvent.click(heavyBleedingYes);
    }

    expect(screen.getByText(/Seek in-person medical care now/i)).toBeInTheDocument();
    expect(screen.getByText(/You reported emergency red-flag symptoms/i)).toBeInTheDocument();
  });
});
