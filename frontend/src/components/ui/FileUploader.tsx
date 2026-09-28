import { useCallback, useRef, useState } from "react";
import { FileText, Upload } from "lucide-react";
import { cn } from "@/lib/cn";

/** Drop zone. Single-file by default (`onFileSelected`); with `multiple`,
 * every picked/dropped file is passed to `onFilesSelected` and the caller
 * owns the list. */
export function FileUploader({
  onFileSelected,
  onFilesSelected,
  multiple,
  accept,
  disabled,
  hint = "PDF, PNG or JPG — purchase orders, invoices, vendor quotes",
}: {
  onFileSelected?: (file: File) => void;
  onFilesSelected?: (files: File[]) => void;
  multiple?: boolean;
  accept?: string;
  disabled?: boolean;
  hint?: string;
}) {
  const [dragging, setDragging] = useState(false);
  const [fileName, setFileName] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFiles = useCallback(
    (list: FileList | null | undefined) => {
      const files = Array.from(list ?? []);
      if (!files.length) return;
      if (multiple) {
        onFilesSelected?.(files);
      } else {
        setFileName(files[0].name);
        onFileSelected?.(files[0]);
      }
      // Allow re-picking the same file after it's removed from the list.
      if (inputRef.current) inputRef.current.value = "";
    },
    [multiple, onFileSelected, onFilesSelected],
  );

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        if (!disabled) handleFiles(e.dataTransfer.files);
      }}
      onClick={() => !disabled && inputRef.current?.click()}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && inputRef.current?.click()}
      aria-label={multiple ? "Choose documents to upload" : "Choose a document to upload"}
      className={cn(
        "flex cursor-pointer items-center gap-3 rounded-md border border-dashed px-4 py-5 transition-colors",
        dragging ? "border-brand-500 bg-brand-50" : "border-slate-300 bg-surface-subtle hover:border-slate-400",
        disabled && "cursor-not-allowed opacity-60",
      )}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        multiple={multiple}
        disabled={disabled}
        className="hidden"
        onChange={(e) => handleFiles(e.target.files)}
      />
      {fileName && !multiple ? (
        <FileText className="size-5 shrink-0 text-slate-500" strokeWidth={1.75} />
      ) : (
        <Upload className="size-5 shrink-0 text-slate-500" strokeWidth={1.75} />
      )}
      <div className="min-w-0 text-sm">
        {fileName && !multiple ? (
          <>
            <p className="truncate font-medium text-slate-900">{fileName}</p>
            <p className="text-xs text-slate-500">Click or drop another file to replace it</p>
          </>
        ) : (
          <>
            <p className="text-slate-700">
              Drag {multiple ? "files" : "a file"} here or <span className="font-medium text-brand-700">browse</span>
            </p>
            <p className="text-xs text-slate-500">{hint}</p>
          </>
        )}
      </div>
    </div>
  );
}
