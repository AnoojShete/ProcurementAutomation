import { api } from "./client";
import type { OrderSummary } from "@/types/api";

/** The order monitor's snapshots (approval-inventory-agent, hourly). */
export const ordersApi = {
  latestSummary: () => api.get<OrderSummary>("/orders/summary/latest"),
  runNow: () => api.post<OrderSummary>("/orders/summary/run"),
};
