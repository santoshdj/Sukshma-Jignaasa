/**
 * Check-in session state managed by Zustand.
 * Persists across the three-step flow: quick-log → chat → confirmation.
 */

import { create } from "zustand";

export interface QuickLogEntry {
  symptom_name: string;
  severity: number;
  duration_minutes?: number;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ConfirmationSummary {
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
}

export type SessionStatus =
  | "idle"
  | "in_progress"
  | "awaiting_confirmation"
  | "saved"
  | "error";

interface CheckInStore {
  // Session
  sessionId: string | null;
  patientId: string;
  status: SessionStatus;
  error: string | null;

  // Quick-log
  quickLogEntries: QuickLogEntry[];

  // Chat
  messages: ChatMessage[];
  isLoading: boolean;

  // Confirmation
  confirmationSummary: ConfirmationSummary | null;
  savedObservationIds: string[];

  // Actions
  setPatientId: (id: string) => void;
  addQuickLogEntry: (entry: QuickLogEntry) => void;
  removeQuickLogEntry: (name: string) => void;
  clearQuickLog: () => void;
  setSession: (sessionId: string, aiMessage: string) => void;
  addMessage: (msg: ChatMessage) => void;
  setLoading: (v: boolean) => void;
  setConfirmationSummary: (s: ConfirmationSummary) => void;
  setSaved: (ids: string[]) => void;
  setError: (msg: string) => void;
  reset: () => void;
}

const initial = {
  sessionId: null,
  patientId: "patient-demo-001",
  status: "idle" as SessionStatus,
  error: null,
  quickLogEntries: [],
  messages: [],
  isLoading: false,
  confirmationSummary: null,
  savedObservationIds: [],
};

export const useCheckInStore = create<CheckInStore>((set) => ({
  ...initial,

  setPatientId: (id) => set({ patientId: id }),

  addQuickLogEntry: (entry) =>
    set((s) => ({
      quickLogEntries: [
        ...s.quickLogEntries.filter((e) => e.symptom_name !== entry.symptom_name),
        entry,
      ],
    })),

  removeQuickLogEntry: (name) =>
    set((s) => ({
      quickLogEntries: s.quickLogEntries.filter((e) => e.symptom_name !== name),
    })),

  clearQuickLog: () => set({ quickLogEntries: [] }),

  setSession: (sessionId, aiMessage) =>
    set({
      sessionId,
      status: "in_progress",
      messages: [{ role: "assistant", content: aiMessage }],
    }),

  addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),

  setLoading: (v) => set({ isLoading: v }),

  setConfirmationSummary: (s) =>
    set({ confirmationSummary: s, status: "awaiting_confirmation" }),

  setSaved: (ids) =>
    set({ savedObservationIds: ids, status: "saved" }),

  setError: (msg) => set({ error: msg, status: "error" }),

  reset: () => set(initial),
}));
