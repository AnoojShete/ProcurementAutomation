import { useCallback, useRef, useState } from "react";
import { FileText, FolderUp, Upload } from "lucide-react";
import { cn } from "@/lib/cn";

export interface FileWithPath {
  file: File;
  relativePath: string;
}

/**
 * Recursively reads directory entries using webkitGetAsEntry.
 * Looping readEntries until empty handles the Chromium 100-entry batch cap.
 */
async function traverseFileTree(entry: any, currentPath = ""): Promise<FileWithPath[]> {
  const results: FileWithPath[] = [];
  if (!entry) return results;

  if (entry.isFile) {
    const file: File = await new Promise((resolve, reject) => {
      entry.file(resolve, reject);
    });
    const relPath = currentPath ? `${currentPath}/${file.name}` : file.name;
    results.push({ file, relativePath: relPath });
  } else if (entry.isDirectory) {
    const dirReader = entry.createReader();
    const dirPath = currentPath ? `${currentPath}/${entry.name}` : entry.name;

    const readAllEntries = async (): Promise<any[]> => {
      const entries: any[] = [];
      let batch: any[] = [];
      do {
        batch = await new Promise((resolve, reject) => {
          dirReader.readEntries(resolve, reject);
        });
        entries.push(...batch);
      } while (batch.length > 0);
      return entries;
    };

    try {
      const entries = await readAllEntries();
      for (const childEntry of entries) {
        const nested = await traverseFileTree(childEntry, dirPath);
        results.push(...nested);
      }
    } catch (err) {
      console.warn("Failed to read directory entries", err);
    }
  }
  return results;
}

export function FileUploader({
  onFileSelected,
  onFilesSelected,
  onFilesWithPathSelected,
  multiple = true,
  allowFolder = true,
  accept,
  disabled,
  hint = "PDF, PNG, JPG, TIFF or WebP — purchase orders, invoices, vendor quotes",
}: {
  onFileSelected?: (file: File) => void;
  onFilesSelected?: (files: File[]) => void;
  onFilesWithPathSelected?: (items: FileWithPath[]) => void;
  multiple?: boolean;
  allowFolder?: boolean;
  accept?: string;
  disabled?: boolean;
  hint?: string;
}) {
  const [dragging, setDragging] = useState(false);
  const [fileName, setFileName] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);

  const handleFileList = useCallback(
    (list: FileList | null | undefined) => {
      const files = Array.from(list ?? []);
      if (!files.length) return;

      const items: FileWithPath[] = files.map((f) => ({
        file: f,
        relativePath: f.webkitRelativePath || f.name,
      }));

      if (onFilesWithPathSelected) {
        onFilesWithPathSelected(items);
      } else if (onFilesSelected) {
        onFilesSelected(files);
      } else if (onFileSelected) {
        setFileName(files.length > 1 ? `${files.length} files selected` : files[0].name);
        files.forEach((f) => onFileSelected(f));
      }

      if (fileInputRef.current) fileInputRef.current.value = "";
      if (folderInputRef.current) folderInputRef.current.value = "";
    },
    [onFileSelected, onFilesSelected, onFilesWithPathSelected],
  );

  const handleDrop = useCallback(
    async (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      if (disabled) return;

      const items = e.dataTransfer.items;
      if (items && items.length > 0 && "webkitGetAsEntry" in items[0]) {
        const collected: FileWithPath[] = [];
        for (let i = 0; i < items.length; i++) {
          const entry = items[i].webkitGetAsEntry();
          if (entry) {
            const nested = await traverseFileTree(entry);
            collected.push(...nested);
          }
        }
        if (collected.length > 0) {
          if (onFilesWithPathSelected) {
            onFilesWithPathSelected(collected);
          } else if (onFilesSelected) {
            onFilesSelected(collected.map((c) => c.file));
          } else if (onFileSelected) {
            setFileName(collected.length > 1 ? `${collected.length} files selected` : collected[0].file.name);
            collected.forEach((c) => onFileSelected(c.file));
          }
          return;
        }
      }

      handleFileList(e.dataTransfer.files);
    },
    [disabled, handleFileList, onFileSelected, onFilesSelected, onFilesWithPathSelected],
  );

  return (
    <div className="space-y-2">
      <div
        onClick={() => {
          if (!disabled) fileInputRef.current?.click();
        }}
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        role="region"
        aria-label={multiple ? "Choose documents to upload" : "Choose a document to upload"}
        className={cn(
          "flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-6 text-center transition-colors cursor-pointer",
          dragging ? "border-brand-500 bg-brand-50" : "border-slate-300 bg-surface-subtle hover:border-brand-400 hover:bg-slate-50/50",
          disabled && "cursor-not-allowed opacity-60",
        )}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept={accept}
          multiple={multiple}
          disabled={disabled}
          className="hidden"
          onChange={(e) => handleFileList(e.target.files)}
        />
        {allowFolder && (
          <input
            ref={folderInputRef}
            type="file"
            // @ts-expect-error webkitdirectory is standard in browser engines but not in standard HTML input types
            webkitdirectory=""
            directory=""
            multiple
            disabled={disabled}
            className="hidden"
            onChange={(e) => handleFileList(e.target.files)}
          />
        )}

        <div className="mb-3 flex items-center justify-center rounded-full bg-slate-100 p-3 text-slate-600">
          {fileName && !multiple ? <FileText className="size-6 text-brand-600" /> : <Upload className="size-6" />}
        </div>

        <div className="space-y-1">
          {fileName && !multiple ? (
            <>
              <p className="font-medium text-slate-900">{fileName}</p>
              <p className="text-xs text-slate-500">Click or drop another file to replace</p>
            </>
          ) : (
            <>
              <p className="text-sm text-slate-700">
                Drag and drop files or folders here, or click to browse
              </p>
              <div className="flex items-center justify-center gap-2 pt-1">
                <button
                  type="button"
                  disabled={disabled}
                  onClick={(e) => {
                    e.stopPropagation();
                    fileInputRef.current?.click();
                  }}
                  className="inline-flex items-center gap-1.5 rounded-md bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-sm ring-1 ring-inset ring-slate-300 hover:bg-slate-50"
                >
                  <Upload className="size-3.5 text-slate-500" />
                  Browse Files (Multi-Select)
                </button>
                {allowFolder && (
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={(e) => {
                      e.stopPropagation();
                      folderInputRef.current?.click();
                    }}
                    className="inline-flex items-center gap-1.5 rounded-md bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-sm ring-1 ring-inset ring-slate-300 hover:bg-slate-50"
                  >
                    <FolderUp className="size-3.5 text-slate-500" />
                    Upload Folder
                  </button>
                )}
              </div>
              <p className="pt-2 text-xs text-slate-500">{hint}</p>
            </>
          )}
        </div>
      </div>

      {allowFolder && (
        <p className="text-center text-[11px] text-slate-400">
          Hold Shift or Ctrl to select multiple files. Folder upload is supported on desktop Chromium, Firefox, and Edge browsers.
        </p>
      )}
    </div>
  );
}
