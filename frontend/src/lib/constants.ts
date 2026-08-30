// Real values read from services/approval-inventory-agent/config.yaml and
// the README (confidence threshold, spend tiers, SLA, utilisation). These
// govern actual backend behavior but aren't exposed through any API, so
// they're shipped here as read-only reference data for the Business Rules
// view — never presented as editable, never invented.

export const CONFIDENCE_REVIEW_THRESHOLD = 0.8;

export const APPROVER_ROLES = [
  { value: "dept_manager", label: "Department Manager (manager tier)" },
  { value: "finance_head", label: "Finance Head (manager+finance tier)" },
] as const;

export const SPEND_TIERS = [
  {
    name: "auto",
    label: "Auto-approved",
    range: "Up to ₹500",
    chain: [] as string[],
    description: "No human approval required.",
  },
  {
    name: "manager",
    label: "Manager approval",
    range: "₹500 – ₹5,000",
    chain: ["dept_manager"],
    description: "Routed to the requester's department manager.",
  },
  {
    name: "manager+finance",
    label: "Manager + Finance approval",
    range: "Above ₹5,000",
    chain: ["dept_manager", "finance_head"],
    description: "Routed to department manager, then finance head.",
  },
] as const;

export const SLA_APPROVAL_TIMEOUT_HOURS = 48;

export const UTILISATION_THRESHOLDS = {
  reclaim: 0.3,
  warning: 0.5,
  measurementPeriodsDays: [30, 60, 90],
};

export const CONTRACT_RENEWAL_ALERT_DAYS = [60, 30, 15];

export const CONTRACT_TEMPLATES: { value: string; label: string }[] = [
  { value: "hardware_purchase", label: "Hardware Purchase" },
  { value: "saas_subscription", label: "SaaS Subscription" },
  { value: "professional_services", label: "Professional Services" },
];

export const DEMO_ACCOUNTS: { role: string; email: string; password: string; label: string }[] = [
  { role: "requester", email: "requester@demo.example.com", password: "DemoPass123!", label: "Requester" },
  { role: "approver", email: "approver@demo.example.com", password: "DemoPass123!", label: "Approver" },
  { role: "finance", email: "finance@demo.example.com", password: "DemoPass123!", label: "Finance" },
  { role: "admin", email: "admin@demo.example.com", password: "DemoPass123!", label: "Admin" },
];

export const INFRA_LINKS = [
  { label: "Grafana", url: "http://localhost:3000", description: "Request rate, latency, error rate per service" },
  { label: "Prometheus", url: "http://localhost:9090", description: "Raw metrics scrape targets" },
  { label: "Temporal UI", url: "http://localhost:8088", description: "Approval & contract workflow executions" },
  { label: "MLflow", url: "http://localhost:5050", description: "Vendor risk model runs & drift metrics" },
  { label: "MinIO console", url: "http://localhost:9000", description: "Document object storage" },
  { label: "Mailpit", url: "http://localhost:8025", description: "Outbound notification emails" },
];

export const PLATFORM_SERVICES = [
  { name: "document-vendor-agent", owns: "Document ingestion, OCR/classification, vendor matching", port: 8001 },
  { name: "approval-inventory-agent", owns: "Approval routing, SLA escalation, inventory reservation", port: 8002 },
  { name: "contract-risk-agent", owns: "Contract generation, e-sign webhook, vendor risk scoring", port: 8003 },
  { name: "notification-agent", owns: "Email rendering & delivery, notification audit log", port: 8004 },
  { name: "auth-service", owns: "Login, JWT issuance & refresh", port: 8005 },
];
