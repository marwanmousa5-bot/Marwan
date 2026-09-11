"use client";

import type { ReactNode } from "react";

import { strings } from "@/lib/strings";

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  numeric?: boolean;
}

/**
 * The dense, quiet table used across the operations pages. Kept in one place
 * so every list in the product reads the same way.
 */
export function DataTable<T extends { id: string }>({
  columns,
  rows,
  loading,
  empty,
  minWidth = "44rem",
}: {
  columns: Column<T>[];
  rows: T[];
  loading?: boolean;
  empty?: string;
  minWidth?: string;
}) {
  if (loading) {
    return <p className="px-4 py-6 text-sm text-ink-400">{strings.common.loading}</p>;
  }
  if (rows.length === 0) {
    return (
      <p className="px-4 py-6 text-sm text-ink-400">{empty ?? strings.common.empty}</p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm" style={{ minWidth }}>
        <thead className="border-b border-ink-600/70 text-xs uppercase tracking-wide text-ink-400">
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={`px-4 py-2.5 font-medium ${column.numeric ? "text-right" : ""}`}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-ink-600/50">
          {rows.map((row) => (
            <tr key={row.id} className="hover:bg-ink-700/40">
              {columns.map((column) => (
                <td
                  key={column.key}
                  className={`px-4 py-3 ${
                    column.numeric ? "fb-numeric text-right text-ink-200" : "text-ink-200"
                  }`}
                >
                  {column.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
