import type { InboxItem } from "@/types/api";

/** Where a pending approval opens — the same page from every list that shows
 * it: a license's own page for reclaim/license requests (it has the decision
 * panel), otherwise the request with its lifecycle Approval step open. */
export function approvalItemPath(item: Pick<InboxItem, "request_id" | "license_id">): string {
  return item.license_id ? `/app/licenses/${item.license_id}` : `/app/requests/${item.request_id}?step=approval`;
}
