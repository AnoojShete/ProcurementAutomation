import { useMemo, useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { cn } from "@/lib/cn";
import { EmptyState } from "./EmptyState";
import { SkeletonTable } from "./Skeleton";

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  sortValue?: (row: T) => string | number | null;
  className?: string;
  hideOnMobile?: boolean;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  loading,
  emptyTitle = "No records yet",
  emptyDescription,
  onRowClick,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  loading?: boolean;
  emptyTitle?: string;
  emptyDescription?: string;
  onRowClick?: (row: T) => void;
}) {
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null);

  const sortedRows = useMemo(() => {
    if (!sort) return rows;
    const col = columns.find((c) => c.key === sort.key);
    if (!col?.sortValue) return rows;
    return [...rows].sort((a, b) => {
      const av = col.sortValue!(a);
      const bv = col.sortValue!(b);
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (av < bv) return -1 * sort.dir;
      if (av > bv) return 1 * sort.dir;
      return 0;
    });
  }, [rows, sort, columns]);

  if (loading) return <SkeletonTable cols={columns.length} />;
  if (!rows.length) return <EmptyState title={emptyTitle} description={emptyDescription} />;

  const toggleSort = (col: Column<T>) => {
    if (!col.sortValue) return;
    setSort((prev) => {
      if (prev?.key !== col.key) return { key: col.key, dir: -1 };
      return prev.dir === -1 ? { key: col.key, dir: 1 } : null;
    });
  };

  // Whole rows are links (GOV.UK task-list pattern): reachable with Tab,
  // opened with Enter, so keyboard users get what a click gives.
  const rowKeyDown = (row: T) => (e: React.KeyboardEvent) => {
    // Only the row itself: Enter on a link or button inside it is theirs.
    if (!onRowClick || e.target !== e.currentTarget) return;
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onRowClick(row);
    }
  };

  return (
    <>
      {/* Desktop / tablet: real table; scrolls inside its section if dense. */}
      <div className="hidden overflow-x-auto sm:block scrollbar-thin">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-ink/60 text-left">
              {columns.map((col) => (
                <th
                  key={col.key}
                  scope="col"
                  aria-sort={sort?.key === col.key ? (sort.dir === 1 ? "ascending" : "descending") : undefined}
                  className={cn("h-9 whitespace-nowrap px-3 text-13 font-medium text-ink-2", col.className)}
                >
                  {col.sortValue ? (
                    <button
                      onClick={() => toggleSort(col)}
                      className="-mx-1 inline-flex items-center gap-1 rounded-sm px-1 py-0.5 hover:bg-sheet-sunk hover:text-ink"
                    >
                      {col.header}
                      {sort?.key === col.key ? (
                        sort.dir === -1 ? <ArrowDown className="size-3" aria-hidden="true" /> : <ArrowUp className="size-3" aria-hidden="true" />
                      ) : (
                        <ArrowUpDown className="size-3 opacity-50" aria-hidden="true" />
                      )}
                    </button>
                  ) : (
                    col.header
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sortedRows.map((row) => (
              <tr
                key={rowKey(row)}
                onClick={() => onRowClick?.(row)}
                onKeyDown={onRowClick ? rowKeyDown(row) : undefined}
                tabIndex={onRowClick ? 0 : undefined}
                className={cn(
                  "border-b border-rule last:border-0",
                  onRowClick &&
                    "cursor-pointer transition-colors duration-1 hover:bg-sheet-sunk focus-visible:bg-accent-tint focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent focus-visible:ring-offset-0",
                )}
              >
                {columns.map((col) => (
                  <td key={col.key} className={cn("h-9 px-3 py-1.5 align-middle text-13 text-ink", col.className)}>
                    {col.render(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Phones: a ruled list of label/value rows, no horizontal scroll. */}
      <ul className="flex flex-col divide-y divide-rule border-y border-rule sm:hidden">
        {sortedRows.map((row) => (
          <li
            key={rowKey(row)}
            onClick={() => onRowClick?.(row)}
            onKeyDown={onRowClick ? rowKeyDown(row) : undefined}
            tabIndex={onRowClick ? 0 : undefined}
            className={cn("px-1 py-2.5", onRowClick && "cursor-pointer active:bg-sheet-sunk focus-visible:bg-accent-tint")}
          >
            {columns
              .filter((c) => !c.hideOnMobile)
              .map((col) => (
                <div key={col.key} className="flex min-h-7 items-center justify-between gap-3 text-sm">
                  <span className="shrink-0 text-ink-3">{col.header}</span>
                  <span className="min-w-0 text-right text-ink">{col.render(row)}</span>
                </div>
              ))}
          </li>
        ))}
      </ul>
    </>
  );
}
