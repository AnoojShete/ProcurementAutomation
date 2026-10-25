import { useMemo, useState, useRef, useEffect, type ReactNode } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { cn } from "@/lib/cn";
import { EmptyState } from "./EmptyState";
import { SkeletonTable } from "./Skeleton";

export interface TableSelection<T> {
  selectedKeys: Set<string>;
  onToggleRow: (key: string) => void;
  onToggleAll: () => void;
  isAllSelected: boolean;
  isIndeterminate: boolean;
  isRowSelectable?: (row: T) => boolean;
  disabledReason?: (row: T) => string | undefined;
}

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
  selectable,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  loading?: boolean;
  emptyTitle?: string;
  emptyDescription?: string;
  onRowClick?: (row: T) => void;
  selectable?: TableSelection<T>;
}) {
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null);
  const headerCheckboxRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (headerCheckboxRef.current) {
      headerCheckboxRef.current.indeterminate = selectable?.isIndeterminate ?? false;
    }
  }, [selectable?.isIndeterminate]);

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

  if (loading) return <SkeletonTable cols={columns.length + (selectable ? 1 : 0)} />;
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
              {selectable && (
                <th scope="col" className="h-9 w-9 px-3 text-13 font-medium text-ink-2">
                  <input
                    type="checkbox"
                    ref={headerCheckboxRef}
                    checked={selectable.isAllSelected}
                    onChange={selectable.onToggleAll}
                    aria-label="Select all"
                    className="size-4 rounded border-rule-strong text-accent focus:ring-accent cursor-pointer"
                  />
                </th>
              )}
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
            {sortedRows.map((row) => {
              const key = rowKey(row);
              const isSelected = selectable?.selectedKeys.has(key) ?? false;
              const isSelectable = selectable?.isRowSelectable ? selectable.isRowSelectable(row) : true;
              const disabledReason = !isSelectable && selectable?.disabledReason ? selectable.disabledReason(row) : undefined;

              return (
                <tr
                  key={key}
                  onClick={() => onRowClick?.(row)}
                  onKeyDown={onRowClick ? rowKeyDown(row) : undefined}
                  tabIndex={onRowClick ? 0 : undefined}
                  className={cn(
                    "border-b border-rule last:border-0",
                    isSelected && "bg-accent-tint/30",
                    onRowClick &&
                      "cursor-pointer transition-colors duration-1 hover:bg-sheet-sunk focus-visible:bg-accent-tint focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent focus-visible:ring-offset-0",
                  )}
                >
                  {selectable && (
                    <td
                      className="h-9 w-9 px-3 py-1.5 align-middle"
                      onClick={(e) => e.stopPropagation()}
                      onKeyDown={(e) => e.stopPropagation()}
                    >
                      <input
                        type="checkbox"
                        checked={isSelected}
                        disabled={!isSelectable}
                        title={disabledReason}
                        aria-label={`Select row ${key}`}
                        onChange={() => selectable.onToggleRow(key)}
                        className="size-4 rounded border-rule-strong text-accent focus:ring-accent disabled:opacity-40 cursor-pointer disabled:cursor-not-allowed"
                      />
                    </td>
                  )}
                  {columns.map((col) => (
                    <td key={col.key} className={cn("h-9 px-3 py-1.5 align-middle text-13 text-ink", col.className)}>
                      {col.render(row)}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Phones: a ruled list of label/value rows, no horizontal scroll. */}
      <ul className="flex flex-col divide-y divide-rule border-y border-rule sm:hidden">
        {sortedRows.map((row) => {
          const key = rowKey(row);
          const isSelected = selectable?.selectedKeys.has(key) ?? false;
          const isSelectable = selectable?.isRowSelectable ? selectable.isRowSelectable(row) : true;
          const disabledReason = !isSelectable && selectable?.disabledReason ? selectable.disabledReason(row) : undefined;

          return (
            <li
              key={key}
              onClick={() => onRowClick?.(row)}
              onKeyDown={onRowClick ? rowKeyDown(row) : undefined}
              tabIndex={onRowClick ? 0 : undefined}
              className={cn(
                "px-1 py-2.5",
                isSelected && "bg-accent-tint/30",
                onRowClick && "cursor-pointer active:bg-sheet-sunk focus-visible:bg-accent-tint",
              )}
            >
              {selectable && (
                <div
                  className="flex items-center justify-between pb-1.5 mb-1.5 border-b border-rule/50"
                  onClick={(e) => e.stopPropagation()}
                >
                  <span className="text-xs text-ink-3">Select</span>
                  <input
                    type="checkbox"
                    checked={isSelected}
                    disabled={!isSelectable}
                    title={disabledReason}
                    onChange={() => selectable.onToggleRow(key)}
                    className="size-4 rounded border-rule-strong text-accent focus:ring-accent disabled:opacity-40"
                  />
                </div>
              )}
              {columns
                .filter((c) => !c.hideOnMobile)
                .map((col) => (
                  <div key={col.key} className="flex min-h-7 items-center justify-between gap-3 text-sm">
                    <span className="shrink-0 text-ink-3">{col.header}</span>
                    <span className="min-w-0 text-right text-ink">{col.render(row)}</span>
                  </div>
                ))}
            </li>
          );
        })}
      </ul>
    </>
  );
}
