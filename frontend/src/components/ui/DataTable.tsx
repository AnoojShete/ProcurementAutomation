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

  return (
    <>
      {/* Desktop / tablet: real table, horizontally scrollable if dense. */}
      <div className="hidden overflow-x-auto sm:block">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-surface-border text-left">
              {columns.map((col) => (
                <th key={col.key} className={cn("px-4 py-2.5 font-medium text-slate-500", col.className)}>
                  {col.sortValue ? (
                    <button
                      onClick={() => toggleSort(col)}
                      className="inline-flex items-center gap-1 hover:text-slate-800"
                    >
                      {col.header}
                      {sort?.key === col.key ? (
                        sort.dir === -1 ? <ArrowDown className="size-3" /> : <ArrowUp className="size-3" />
                      ) : (
                        <ArrowUpDown className="size-3 opacity-40" />
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
                className={cn(
                  "border-b border-surface-border last:border-0",
                  onRowClick && "cursor-pointer hover:bg-surface-subtle",
                )}
              >
                {columns.map((col) => (
                  <td key={col.key} className={cn("px-4 py-3 align-middle text-slate-700", col.className)}>
                    {col.render(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile: stacked cards so nothing needs a horizontal scroll to read. */}
      <div className="flex flex-col gap-2 sm:hidden">
        {sortedRows.map((row) => (
          <div
            key={rowKey(row)}
            onClick={() => onRowClick?.(row)}
            className={cn(
              "rounded-lg border border-surface-border p-3",
              onRowClick && "cursor-pointer active:bg-surface-subtle",
            )}
          >
            {columns
              .filter((c) => !c.hideOnMobile)
              .map((col) => (
                <div key={col.key} className="flex items-center justify-between gap-3 py-1 text-sm">
                  <span className="text-slate-500">{col.header}</span>
                  <span className="text-right text-slate-800">{col.render(row)}</span>
                </div>
              ))}
          </div>
        ))}
      </div>
    </>
  );
}
