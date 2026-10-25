import React, { useState } from "react";

export type SortDirection = "asc" | "desc" | null;

export interface Column<T extends object = Record<string, unknown>> {
  key: keyof T | string;
  header: string;
  sortable?: boolean;
  align?: "left" | "right" | "center";
  render?: (row: T, index: number) => React.ReactNode;
}

export interface DataTableProps<T extends object = Record<string, unknown>> {
  columns: Column<T>[];
  data: T[];
  density?: "dense" | "touch";
  caption?: string;
  className?: string;
  onRowClick?: (row: T) => void;
  initialSortKey?: string;
  initialSortDirection?: SortDirection;
}

/**
 * DataTable Component adhering to DESIGN.md section 8:
 * - 36px dense rows for staff screens, 44px on touch screens
 * - Sticky header with ruled lines
 * - Sortable columns operable via keyboard (Enter/Space)
 * - Tabular numerals on all data cells
 */
export function DataTable<T extends object>({
  columns,
  data,
  density = "dense",
  caption,
  className = "",
  onRowClick,
  initialSortKey,
  initialSortDirection = null,
}: DataTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(initialSortKey ?? null);
  const [sortDirection, setSortDirection] = useState<SortDirection>(initialSortDirection);

  const handleSort = (key: string) => {
    if (sortKey === key) {
      if (sortDirection === "asc") {
        setSortDirection("desc");
      } else if (sortDirection === "desc") {
        setSortDirection(null);
        setSortKey(null);
      } else {
        setSortDirection("asc");
      }
    } else {
      setSortKey(key);
      setSortDirection("asc");
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent, key: string) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      handleSort(key);
    }
  };

  // Sort data if active
  const sortedData = React.useMemo(() => {
    if (!sortKey || !sortDirection) {
      return data;
    }
    return [...data].sort((a, b) => {
      const valA = (a as Record<string, unknown>)[sortKey];
      const valB = (b as Record<string, unknown>)[sortKey];

      if (valA === valB) return 0;
      if (valA === undefined || valA === null) return 1;
      if (valB === undefined || valB === null) return -1;

      if (typeof valA === "number" && typeof valB === "number") {
        return sortDirection === "asc" ? valA - valB : valB - valA;
      }
      const strA = String(valA).toLowerCase();
      const strB = String(valB).toLowerCase();
      return sortDirection === "asc" ? strA.localeCompare(strB) : strB.localeCompare(strA);
    });
  }, [data, sortKey, sortDirection]);

  const rowHeightClass = density === "dense" ? "h-[36px]" : "min-h-[44px]";

  return (
    <div className={`overflow-x-auto border border-[#D5DAD8] bg-white ${className}`.trim()}>
      <table className="w-full text-left font-sans text-sm border-collapse tabular-nums">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead className="sticky top-0 bg-[#F5F7F6] border-b border-[#D5DAD8] z-10">
          <tr>
            {columns.map((col) => {
              const colKey = String(col.key);
              const isSorted = sortKey === colKey;
              const ariaSort = !col.sortable
                ? undefined
                : isSorted
                  ? sortDirection === "asc"
                    ? "ascending"
                    : sortDirection === "desc"
                      ? "descending"
                      : "none"
                  : "none";

              return (
                <th
                  key={colKey}
                  scope="col"
                  aria-sort={ariaSort}
                  tabIndex={col.sortable ? 0 : undefined}
                  role={col.sortable ? "columnheader" : undefined}
                  onClick={() => col.sortable && handleSort(colKey)}
                  onKeyDown={(e) => col.sortable && handleKeyDown(e, colKey)}
                  className={`px-3 py-2 text-xs font-semibold uppercase tracking-wider text-[#18242C] select-none border-r border-[#D5DAD8] last:border-r-0 ${
                    col.sortable
                      ? "cursor-pointer hover:bg-[#D5DAD8]/30 focus-visible:outline-2 focus-visible:outline-[#4B2E83] focus-visible:outline-offset-[-2px]"
                      : ""
                  } ${col.align === "right" ? "text-right" : col.align === "center" ? "text-center" : "text-left"}`}
                >
                  <div className="inline-flex items-center gap-1">
                    <span>{col.header}</span>
                    {col.sortable && (
                      <span aria-hidden="true" className="text-[10px] text-[#18242C]/70">
                        {isSorted
                          ? sortDirection === "asc"
                            ? "▲"
                            : sortDirection === "desc"
                              ? "▼"
                              : "⇅"
                          : "⇅"}
                      </span>
                    )}
                  </div>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody className="divide-y divide-[#D5DAD8]">
          {sortedData.length === 0 ? (
            <tr>
              <td
                colSpan={columns.length}
                className="px-3 py-6 text-center text-sm text-[#18242C]/70"
              >
                No entries available.
              </td>
            </tr>
          ) : (
            sortedData.map((row, rowIndex) => (
              <tr
                key={rowIndex}
                onClick={() => onRowClick?.(row)}
                className={`${rowHeightClass} hover:bg-[#F5F7F6]/60 transition-colors ${
                  onRowClick ? "cursor-pointer" : ""
                }`}
              >
                {columns.map((col) => {
                  const colKey = String(col.key);
                  const cellValue = (row as Record<string, unknown>)[colKey];
                  return (
                    <td
                      key={colKey}
                      className={`px-3 py-1.5 border-r border-[#D5DAD8] last:border-r-0 text-[#18242C] ${
                        col.align === "right"
                          ? "text-right"
                          : col.align === "center"
                            ? "text-center"
                            : "text-left"
                      }`}
                    >
                      {col.render ? col.render(row, rowIndex) : String(cellValue ?? "")}
                    </td>
                  );
                })}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
