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
