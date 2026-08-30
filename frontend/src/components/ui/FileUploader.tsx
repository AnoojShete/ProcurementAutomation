import { useCallback, useRef, useState } from "react";
import { FileText, UploadCloud } from "lucide-react";
import { cn } from "@/lib/cn";

export function FileUploader({
  onFileSelected,
  accept,
  disabled,
}: {
  onFileSelected: (file: File) => void;
  accept?: string;
  disabled?: boolean;
}) {
  const [dragging, setDragging] = useState(false);
  const [fileName, setFileName] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback(
    (file: File | undefined | null) => {
      if (!file) return;
      setFileName(file.name);
      onFileSelected(file);
    },
    [onFileSelected],
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
        if (!disabled) handleFile(e.dataTransfer.files?.[0]);
      }}
      onClick={() => !disabled && inputRef.current?.click()}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && inputRef.current?.click()}
      aria-label="Upload a document"
      className={cn(
        "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors",
        dragging ? "border-brand-400 bg-brand-50" : "border-surface-border bg-surface-subtle hover:border-brand-300",
        disabled && "cursor-not-allowed opacity-60",
      )}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        disabled={disabled}
        className="hidden"
        onChange={(e) => handleFile(e.target.files?.[0])}
      />
      {fileName ? (
        <>
          <FileText className="size-7 text-brand-600" />
          <p className="text-sm font-medium text-slate-800">{fileName}</p>
          <p className="text-xs text-slate-500">Click or drop another file to replace it</p>
        </>
      ) : (
        <>
          <UploadCloud className="size-7 text-slate-400" />
          <p className="text-sm font-medium text-slate-700">Drag & drop a file, or click to browse</p>
          <p className="text-xs text-slate-500">Purchase order, invoice, or vendor quote — PDF or image</p>
        </>
      )}
    </div>
  );
}
