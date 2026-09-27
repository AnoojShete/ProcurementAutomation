import { Link } from "react-router-dom";
import { AlertTriangle, BookOpenCheck, Lock, ShieldAlert } from "lucide-react";
import { formatCurrency } from "@/lib/format";

type Json = Record<string, any>;

function Row({ icon: Icon, tone, title, children }: { icon: typeof Lock; tone: "warn" | "danger" | "info" | "ok"; title: string; children: React.ReactNode }) {
  const tones = {
    warn: "border-warning-500/40 bg-warning-50 [&_svg]:text-warning-600",
    danger: "border-danger-500/30 bg-danger-50 [&_svg]:text-danger-600",
    info: "border-surface-border bg-surface-subtle [&_svg]:text-slate-500",
    ok: "border-success-500/30 bg-success-50 [&_svg]:text-success-600",
  };
  return (
    <div className={`flex items-start gap-2.5 rounded-md border px-3 py-2.5 text-13 text-slate-800 ${tones[tone]}`}>
      <Icon className="mt-0.5 size-4 shrink-0" />
      <div className="min-w-0">
        <p className="font-medium">{title}</p>
        <div className="mt-0.5 text-slate-700">{children}</div>
      </div>
    </div>
  );
}

/** Findings from the payment, matching and learning controls, as stored
 * on the document by the pipeline. Renders nothing for a clean document. */
export function DocumentControls({ extracted }: { extracted: Json }) {
  const match: Json | undefined = extracted.invoice_match;
  const lookalike: Json | undefined = extracted.lookalike_vendor;
  const learned: Json[] = extracted.learned_fields ?? [];
  const threshold: Json | undefined = extracted.review_threshold;
  const reviewLearning: Json | undefined = extracted.review_learning;
  const items: React.ReactNode[] = [];

  if (extracted.payment_hold) {
    items.push(
      <Row key="hold" icon={Lock} tone="warn" title="Payment hold">
        {extracted.payment_hold_reason}. The invoice can't be paid until finance verifies the vendor's bank details
        through a channel already on file.
      </Row>,
    );
  } else if (extracted.payment_hold_released_at) {
    items.push(
      <Row key="released" icon={Lock} tone="ok" title="Payment hold released">
        Vendor bank details were verified; this invoice is payable.
      </Row>,
    );
  }
  if (lookalike) {
    items.push(
      <Row key="lookalike" icon={ShieldAlert} tone="danger" title="Possible impersonation">
        This vendor's name is {Math.round(lookalike.similarity * 100)}% similar to existing vendor{" "}
        <Link to={`/app/vendors/${lookalike.vendor_id}`} className="font-medium text-brand-700 hover:underline">
          {lookalike.vendor_name}
        </Link>
        {lookalike.bank_details_differ ? ", with different bank details" : ""}. It was not merged into that vendor.
      </Row>,
    );
  }
  if (match) {
    const reqLink = match.purchase_request_id ? (
      <Link to={`/app/requests/${match.purchase_request_id}`} className="font-medium text-brand-700 hover:underline">
        PR-{String(match.purchase_request_id).slice(0, 8)}
      </Link>
    ) : null;
    if (match.status === "matched" || match.status === "partial") {
      items.push(
        <Row key="match" icon={BookOpenCheck} tone="ok" title={match.status === "matched" ? "Matched — request fully invoiced" : "Matched — partial invoice"}>
          Booked against {reqLink}.{" "}
          {match.remaining_after != null && match.status === "partial" && <>Still to invoice: {formatCurrency(match.remaining_after)}.</>}
        </Row>,
      );
    } else if (match.status === "variance") {
      items.push(
        <Row key="match" icon={AlertTriangle} tone="danger" title="Doesn't fit the purchase request">
          Closest request {reqLink}; not booked:
          <ul className="mt-1 list-disc pl-4">
            {(match.issues ?? []).map((i: string) => <li key={i}>{i}</li>)}
          </ul>
        </Row>,
      );
    } else if (match.status === "ambiguous") {
      items.push(
        <Row key="match" icon={AlertTriangle} tone="warn" title="More than one request could take this invoice">
          A reviewer needs to pick the purchase request.
        </Row>,
      );
    } else {
      items.push(
        <Row key="match" icon={AlertTriangle} tone="warn" title="No purchase request to match">
          {(match.issues ?? [])[0] ?? "No open purchase request for this vendor has a balance that fits."}
        </Row>,
      );
    }
  }
  if (learned.length > 0) {
    items.push(
      <Row key="learned" icon={BookOpenCheck} tone="info" title="Applied what reviewers taught for this vendor">
        <ul className="list-disc pl-4">
          {learned.map((l) => (
            <li key={l.field}>
              <span className="font-medium">{l.field.replace(/_/g, " ")}</span>{" "}
              {l.action === "corrected" ? <>read as {String(l.value)} (extraction said {String(l.previous ?? "nothing")})</> : "confirmed"}{" "}
              from the “{l.label}” label, seen in {l.support} earlier reviews
            </li>
          ))}
        </ul>
      </Row>,
    );
  }
  if (threshold && threshold.mode !== "default") {
    items.push(
      <Row key="threshold" icon={BookOpenCheck} tone="info" title={`Review threshold ${threshold.mode === "relaxed" ? "relaxed" : "tightened"} for this vendor`}>
        {threshold.clean} of this vendor's last {threshold.reviews} reviewed documents needed no corrections, so documents
        below {Math.round(threshold.threshold * 100)}% confidence go to review.
      </Row>,
    );
  }
  if (reviewLearning?.learned?.length) {
    items.push(
      <Row key="taught" icon={BookOpenCheck} tone="info" title="This review taught the extractor">
        {reviewLearning.learned.map((l: Json) => `${l.field.replace(/_/g, " ")} → “${l.label}”`).join(", ")}. After two
        agreeing reviews, future documents from this vendor are read this way automatically.
      </Row>,
    );
  }
  if (!items.length) return null;
  return <div className="flex flex-col gap-2">{items}</div>;
}
