import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { DataTable, type Column } from "./DataTable";

interface TestRow extends Record<string, unknown> {
  id: string;
  name: string;
  age: number;
}

describe("DataTable Component", () => {
  const columns: Column<TestRow>[] = [
    { key: "name", header: "Name", sortable: true },
    { key: "age", header: "Age", sortable: true, align: "right" },
  ];

  const data: TestRow[] = [
    { id: "1", name: "Sunita Rao", age: 52 },
    { id: "2", name: "Aarav Patel", age: 34 },
    { id: "3", name: "Deepak Shinde", age: 61 },
  ];

  it("renders tabular numerals and sticky header with rows", () => {
    const { container } = render(<DataTable columns={columns} data={data} caption="Test table" />);

    const table = container.querySelector("table");
    expect(table?.classList.contains("tabular-nums")).toBe(true);
    expect(screen.getByText("Sunita Rao")).toBeDefined();
    expect(screen.getByText("Aarav Patel")).toBeDefined();
  });

  it("sorts with the keyboard using Enter and Space keys", () => {
    render(<DataTable columns={columns} data={data} />);

    const ageHeader = screen.getByRole("columnheader", { name: /Age/i });
    expect(ageHeader.getAttribute("aria-sort")).toBe("none");

    // 1. Press Enter to sort ascending
    fireEvent.keyDown(ageHeader, { key: "Enter", code: "Enter" });
    expect(ageHeader.getAttribute("aria-sort")).toBe("ascending");

    // First row should now be Aarav (age 34)
    const rows = screen.getAllByRole("row");
    // Row 0 is header, Row 1 is first data row
    expect(rows[1]?.textContent).toContain("Aarav Patel");
    expect(rows[1]?.textContent).toContain("34");

    // 2. Press Space to sort descending
    fireEvent.keyDown(ageHeader, { key: " ", code: "Space" });
    expect(ageHeader.getAttribute("aria-sort")).toBe("descending");

    // First row should now be Deepak (age 61)
    const descRows = screen.getAllByRole("row");
    expect(descRows[1]?.textContent).toContain("Deepak Shinde");
    expect(descRows[1]?.textContent).toContain("61");
  });
});
