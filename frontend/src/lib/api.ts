/**
 * API client for the check-in endpoints.
 * All calls go through the Next.js /api/* rewrite → FastAPI backend.
 */

const BASE = "/api/check-in";

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
    throw new Error(err.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export interface StartResponse {
  session_id: string;
  ai_message: string;
  status: string;
}

export interface MessageResponse {
  ai_message: string;
  status: string;
  confirmation_summary: {
    symptoms: Array<{
      text: string;
      hpo_labels: string[];
      severity: number | null;
      body_system: string | null;
      trigger: string | null;
    }>;
    context: Record<string, unknown>;
    is_no_symptom_day: boolean;
    message: string;
  } | null;
}

export interface ConfirmResponse {
  status: string;
  fhir_observation_ids: string[];
}

export const checkInApi = {
  start: (patientId: string, quickLogEntries: unknown[]) =>
    post<StartResponse>("/start", {
      patient_id: patientId,
      quick_log_entries: quickLogEntries,
    }),

  message: (sessionId: string, patientMessage: string) =>
    post<MessageResponse>("/message", {
      session_id: sessionId,
      patient_message: patientMessage,
    }),

  confirm: (sessionId: string, decision: "confirm" | "edit", editNotes?: string) =>
    post<ConfirmResponse>("/confirm", {
      session_id: sessionId,
      decision,
      edit_notes: editNotes ?? "",
    }),
};

// ---------------------------------------------------------------------------
// Hypothesis (pattern analysis) API
// ---------------------------------------------------------------------------

const HYPO_BASE = "/api/hypothesis";

async function hypoGet<T>(path: string): Promise<T> {
  const res = await fetch(`${HYPO_BASE}${path}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
    throw new Error(typeof err.detail === "string" ? err.detail : JSON.stringify(err.detail));
  }
  return res.json() as Promise<T>;
}

async function hypoPost<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${HYPO_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
    throw new Error(typeof err.detail === "string" ? err.detail : JSON.stringify(err.detail));
  }
  return res.json() as Promise<T>;
}

export interface HypothesisStartResponse {
  session_id: string;
  patient_id: string;
  status: string;
  observations_available: number;
  min_observations_required: number;
}

export interface HypothesisStatusResponse {
  session_id: string;
  patient_id: string;
  status: string;
}

export interface HypothesisProfile {
  condition_id: string;
  condition_name: string;
  match_strength: "high" | "medium" | "low";
  matching_symptoms: string[];
  missing_signals: string[];
  plain_language_explanation: string;
  specialist_type: string;
  confidence_note: string;
  discuss_with_specialist: true;
}

export interface HypothesisReport {
  patient_id: string;
  observation_count: number;
  ehr_records_included: boolean;
  hypotheses: HypothesisProfile[];
  summary: string;
  guardrail_disclosure: string;
  human_approved: boolean;
}

export interface HypothesisSessionSummary {
  session_id: string;
  status: string;
  created_at: string | null;
  updated_at: string | null;
  observation_count: number;
  hypothesis_count: number;
  human_approved: boolean;
}

export const hypothesisApi = {
  start: (patientId: string) =>
    hypoPost<HypothesisStartResponse>("/start", { patient_id: patientId }),

  getStatus: (sessionId: string) =>
    hypoGet<HypothesisStatusResponse>(`/${sessionId}/status`),

  approve: (sessionId: string, decision: "approve" | "regenerate" = "approve", feedback = "") =>
    hypoPost<HypothesisStatusResponse>(`/${sessionId}/approve`, { decision, feedback }),

  getReport: (sessionId: string) =>
    hypoGet<HypothesisReport>(`/${sessionId}/report`),

  listSessions: (patientId: string) =>
    hypoGet<HypothesisSessionSummary[]>(`/patient/${patientId}/sessions`),
};

// ---------------------------------------------------------------------------
// Clinical report (PDF download)
// ---------------------------------------------------------------------------

/**
 * Fetch the clinical report PDF, create a blob URL, and trigger a download.
 * Returns the generated filename.
 */
export async function downloadClinicalReport(opts: {
  patientId: string;
  prepSessionId?: string;
  hypothesisSessionId?: string;
}): Promise<string> {
  const res = await fetch("/api/clinical-report/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      patient_id: opts.patientId,
      prep_session_id: opts.prepSessionId ?? null,
      hypothesis_session_id: opts.hypothesisSessionId ?? null,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
    throw new Error(typeof err.detail === "string" ? err.detail : "Failed to generate report");
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const cd = res.headers.get("content-disposition") ?? "";
  const match = cd.match(/filename="([^"]+)"/);
  const filename = match?.[1] ?? "clinical-report.pdf";

  // Trigger browser download
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);

  return filename;
}
