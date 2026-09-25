import { useEffect, useRef, useState } from "react";
import { CheckCircle2, Eraser, FileSignature, Lock, PenTool, Type } from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { InlineError } from "@/components/ui/ErrorState";
import { contractsApi } from "@/api/contracts";
import { ApiError } from "@/api/client";
import type { Contract } from "@/types/api";

interface DigitalSignatureModalProps {
  open: boolean;
  onClose: () => void;
  contract: Contract;
  onSuccess: (updatedContract: Contract) => void;
  defaultSignerEmail?: string;
  defaultSignerName?: string;
}

export function DigitalSignatureModal({
  open,
  onClose,
  contract,
  onSuccess,
  defaultSignerEmail = "",
  defaultSignerName = "",
}: DigitalSignatureModalProps) {
  const [signerName, setSignerName] = useState(defaultSignerName);
  const [signerEmail, setSignerEmail] = useState(defaultSignerEmail);
  const [signMode, setSignMode] = useState<"draw" | "type">("draw");
  const [typedFont, setTypedFont] = useState<"serif" | "cursive" | "mono">("cursive");
  const [legalConsent, setLegalConsent] = useState(false);
  const [signing, setSigning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Canvas drawing state
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [isDrawing, setIsDrawing] = useState(false);
  const [hasDrawn, setHasDrawn] = useState(false);

  useEffect(() => {
    if (open) {
      setSignerName(defaultSignerName || "");
      setSignerEmail(defaultSignerEmail || "");
      setLegalConsent(false);
      setError(null);
      setHasDrawn(false);
      setTimeout(() => clearCanvas(), 50);
    }
  }, [open, defaultSignerName, defaultSignerEmail]);

  const clearCanvas = () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    setHasDrawn(false);
  };

  const getCanvasCoordinates = (e: React.MouseEvent<HTMLCanvasElement> | React.TouchEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;

    if ("touches" in e) {
      const touch = e.touches[0];
      return {
        x: (touch.clientX - rect.left) * scaleX,
        y: (touch.clientY - rect.top) * scaleY,
      };
    }
    return {
      x: (e.clientX - rect.left) * scaleX,
      y: (e.clientY - rect.top) * scaleY,
    };
  };

  const startDrawing = (e: React.MouseEvent<HTMLCanvasElement> | React.TouchEvent<HTMLCanvasElement>) => {
    e.preventDefault();
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const { x, y } = getCanvasCoordinates(e);
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineWidth = 2.5;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.strokeStyle = "#0f172a";
    setIsDrawing(true);
    setHasDrawn(true);
  };

  const draw = (e: React.MouseEvent<HTMLCanvasElement> | React.TouchEvent<HTMLCanvasElement>) => {
    if (!isDrawing) return;
    e.preventDefault();
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const { x, y } = getCanvasCoordinates(e);
    ctx.lineTo(x, y);
    ctx.stroke();
  };

  const stopDrawing = () => {
    setIsDrawing(false);
  };

  // Convert typed text into a high-res image data URL
  const generateTypedSignatureImage = (): string => {
    const offscreen = document.createElement("canvas");
    offscreen.width = 500;
    offscreen.height = 150;
    const ctx = offscreen.getContext("2d");
    if (!ctx) return "";

    ctx.fillStyle = "transparent";
    ctx.fillRect(0, 0, offscreen.width, offscreen.height);

    ctx.fillStyle = "#0f172a";
    if (typedFont === "cursive") {
      ctx.font = "italic 44px 'Brush Script MT', 'Dancing Script', 'Caveat', cursive, Georgia";
    } else if (typedFont === "serif") {
      ctx.font = "italic 36px 'Playfair Display', Georgia, serif";
    } else {
      ctx.font = "italic 32px 'Courier New', monospace";
    }

    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(signerName.trim() || "Authorized Signature", 250, 75);

    // Decorative underline
    ctx.beginPath();
    ctx.moveTo(80, 110);
    ctx.lineTo(420, 110);
    ctx.strokeStyle = "#94a3b8";
    ctx.lineWidth = 1;
    ctx.stroke();

    return offscreen.toDataURL("image/png");
  };

  const handleExecuteSign = async () => {
    if (!signerName.trim()) {
      setError("Please provide your legal full name.");
      return;
    }
    if (!signerEmail.trim()) {
      setError("Please provide your authorized signer email address.");
      return;
    }
    if (!legalConsent) {
      setError("You must acknowledge the legal electronic signature disclosure.");
      return;
    }

    let signatureData: string | undefined = undefined;
    if (signMode === "draw") {
      if (!hasDrawn || !canvasRef.current) {
        setError("Please draw your signature on the pad provided.");
        return;
      }
      signatureData = canvasRef.current.toDataURL("image/png");
    } else {
      signatureData = generateTypedSignatureImage();
    }

    setSigning(true);
    setError(null);

    try {
      const response = await contractsApi.signContract(contract.id, {
        signer_name: signerName.trim(),
        signer_email: signerEmail.trim(),
        signature_data: signatureData,
        legal_consent: true,
      });

      onSuccess(response.data);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to execute electronic signature.");
    } finally {
      setSigning(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Legally Execute & Sign Contract"
      size="lg"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={signing}>
            Cancel
          </Button>
          <Button
            onClick={handleExecuteSign}
            loading={signing}
            disabled={!signerName.trim() || !signerEmail.trim() || !legalConsent}
            icon={<FileSignature className="size-4" />}
          >
            Sign & Execute Contract
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4 text-sm">
        {error && <InlineError message={error} />}

        {/* Contract Summary Banner */}
        <div className="rounded-lg border border-slate-200 bg-slate-50/70 p-3.5">
          <div className="flex items-center justify-between">
            <div>
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">Document to Sign</span>
              <h3 className="font-medium text-slate-900">{contract.template_used?.replace(/_/g, " ").toUpperCase()}</h3>
            </div>
            <div className="text-right">
              <span className="text-xs text-slate-500">Contract ID</span>
              <p className="font-mono text-xs font-medium text-slate-700">{contract.id.slice(0, 13)}...</p>
            </div>
          </div>
        </div>

        {/* Signer Identity Fields */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-700">
              Legal Full Name <span className="text-rose-500">*</span>
            </label>
            <input
              type="text"
              value={signerName}
              onChange={(e) => setSignerName(e.target.value)}
              placeholder="e.g. Jane Doe"
              className="w-full rounded-lg border border-surface-border px-3 py-2 text-sm focus:border-brand-500 focus:outline-none"
            />
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-slate-700">
              Authorized Signer Email <span className="text-rose-500">*</span>
            </label>
            <input
              type="email"
              value={signerEmail}
              onChange={(e) => setSignerEmail(e.target.value)}
              placeholder="signer@company.com"
              className="w-full rounded-lg border border-surface-border px-3 py-2 text-sm focus:border-brand-500 focus:outline-none"
            />
          </div>
        </div>

        {/* Signature Mode Selection */}
        <div>
          <div className="mb-2 flex items-center justify-between">
            <label className="text-xs font-medium text-slate-700">Electronic Signature</label>
            <div className="inline-flex rounded-lg border border-slate-200 bg-slate-100 p-0.5 text-xs">
              <button
                type="button"
                onClick={() => setSignMode("draw")}
                className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 font-medium transition-colors ${
                  signMode === "draw" ? "bg-white text-slate-900 shadow-sm" : "text-slate-600 hover:text-slate-900"
                }`}
              >
                <PenTool className="size-3.5" />
                Draw
              </button>
              <button
                type="button"
                onClick={() => setSignMode("type")}
                className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 font-medium transition-colors ${
                  signMode === "type" ? "bg-white text-slate-900 shadow-sm" : "text-slate-600 hover:text-slate-900"
                }`}
              >
                <Type className="size-3.5" />
                Type
              </button>
            </div>
          </div>

          {signMode === "draw" ? (
            <div className="relative rounded-xl border border-surface-border bg-slate-50/50 p-2">
              <canvas
                ref={canvasRef}
                width={500}
                height={150}
                onMouseDown={startDrawing}
                onMouseMove={draw}
                onMouseUp={stopDrawing}
                onMouseLeave={stopDrawing}
                onTouchStart={startDrawing}
                onTouchMove={draw}
                onTouchEnd={stopDrawing}
                className="h-36 w-full cursor-crosshair rounded-lg border border-dashed border-slate-300 bg-white shadow-inner touch-none"
              />
              <div className="mt-1 flex items-center justify-between px-1 text-xs text-slate-400">
                <span>Sign above using mouse, trackpad, or touch</span>
                <button
                  type="button"
                  onClick={clearCanvas}
                  className="flex items-center gap-1 text-slate-500 hover:text-slate-700"
                >
                  <Eraser className="size-3.5" />
                  Clear Pad
                </button>
              </div>
            </div>
          ) : (
            <div className="flex flex-col gap-2 rounded-xl border border-surface-border bg-slate-50/50 p-3">
              <div className="flex items-center justify-between text-xs text-slate-500">
                <span>Font Style:</span>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => setTypedFont("cursive")}
                    className={`rounded px-2 py-0.5 ${
                      typedFont === "cursive" ? "bg-brand-100 font-semibold text-brand-700" : "text-slate-600"
                    }`}
                  >
                    Script
                  </button>
                  <button
                    type="button"
                    onClick={() => setTypedFont("serif")}
                    className={`rounded px-2 py-0.5 ${
                      typedFont === "serif" ? "bg-brand-100 font-semibold text-brand-700" : "text-slate-600"
                    }`}
                  >
                    Classic Serif
                  </button>
                  <button
                    type="button"
                    onClick={() => setTypedFont("mono")}
                    className={`rounded px-2 py-0.5 ${
                      typedFont === "mono" ? "bg-brand-100 font-semibold text-brand-700" : "text-slate-600"
                    }`}
                  >
                    Formal Mono
                  </button>
                </div>
              </div>

              <div className="flex h-24 items-center justify-center rounded-lg border border-slate-200 bg-white p-4 shadow-inner">
                <span
                  className={
                    typedFont === "cursive"
                      ? "font-serif italic text-3xl text-slate-900 tracking-wide"
                      : typedFont === "serif"
                      ? "font-serif italic text-2xl text-slate-900"
                      : "font-mono italic text-xl text-slate-900"
                  }
                >
                  {signerName.trim() || "Your Legal Name"}
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Legal Consent and ESIGN Disclosure */}
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-3.5">
          <label className="flex items-start gap-2.5 cursor-pointer">
            <input
              type="checkbox"
              checked={legalConsent}
              onChange={(e) => setLegalConsent(e.target.checked)}
              className="mt-0.5 size-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
            />
            <span className="text-xs leading-relaxed text-slate-600">
              <strong className="text-slate-900">Legal Electronic Signature Consent: </strong>
              I agree that my electronic signature and records are legally binding under the Electronic Signatures in
              Global and National Commerce Act (E-SIGN Act, 15 U.S.C. § 7001) and the Uniform Electronic Transactions
              Act (UETA). I certify that I am authorized to execute this agreement.
            </span>
          </label>
        </div>

        {/* Security & Cryptographic Guarantee */}
        <div className="flex items-center gap-2 text-[11px] text-slate-400">
          <Lock className="size-3.5 text-slate-400 shrink-0" />
          <span>Tamper-evident SHA-256 seal & verifiable audit certificate generated upon completion.</span>
        </div>
      </div>
    </Modal>
  );
}
