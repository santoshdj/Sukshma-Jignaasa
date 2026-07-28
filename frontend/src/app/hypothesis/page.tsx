"use client";

import { useState } from "react";
import { EHRConnectionStatus } from "@/components/EHRConnectionStatus";
import { HypothesisCard } from "@/components/HypothesisCard";

const PATIENT_ID = "patient-demo-001";
const MIN_OBS = 30;

interface HypothesisReport {
  patient_id: string;
  observation_count: number;
  ehr_records_included: boolean;
  hypotheses: Array<{
    condition_id: string;
    condition_name: string;
    match_strength: "high" | "medium" | "low";
    matching_symptoms: string[];
    missing_signals: string[];
    plain_language_explanation: string;
    specialist_type: string;
    confidence_note: string;
    discuss_with_specialist: true;
  }>;
  summary: string;
  guardrail_disclosure: string;
  human_approved: boolean;
}

type PageState = "idle" | "loading" | "awaiting_review" | "approved" | "error";

export default function HypothesisPage() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [report, setReport] = useState<HypothesisReport | null>(null);
  const [pageState, setPageState] = useState<PageState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [obsCount, setObsCount] = useState<number | null>(null);

  const startAnalysis = async () => {
    setPageState("loading");
    setError(null);
    try {
      const res = await fetch("/api/hypothesis/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ patient_id: PATIENT_ID }),
      });
      if (res.status === 422) {
        const body = await res.json() as { detail: { observations_available: number; min_observations_required: number } };
        setObsCount(body.detail.observations_available);
        setPageState("idle");
        return;
      }
      if (!res.ok) throw new Error("Analysis failed");
      const data = await res.json() as { session_id: string; observations_available: number };
      setSessionId(data.session_id);
      setObsCount(data.observations_available);
      setPageState("awaiting_review");

      // Fetch the report immediately (graph has paused at review_gate)
      const reportRes = await fetch(`/api/hypothesis/${data.session_id}/report`).catch(() => null);
      // Report not accessible until approved — show approve button
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      setPageState("error");
    }
  };

  const approveReport = async () => {
    if (!sessionId) return;
    try {
      await fetch(`/api/hypothesis/${sessionId}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision: "approve" }),
      });
      const res = await fetch(`/api/hypothesis/${sessionId}/report`);
      if (!res.ok) throw new Error("Failed to fetch report");
      const data = await res.json() as HypothesisReport;
      setReport(data);
      setPageState("approved");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      setPageState("error");
    }
  };

  const insufficientData = obsCount !== null && obsCount < MIN_OBS;

  return (
    <main className="max-w-lg mx-auto px-4 py-8 space-y-6">
      <div>
        <a href="/" className="text-xs text-slate-400 hover:text-slate-600 mb-3 inline-block">← Home</a>
        <h1 className="text-xl font-bold text-slate-800">Pattern analysis</h1>
        <p className="text-sm text-slate-500 mt-1">
          Compare your symptom pattern against rare disease profiles.
        </p>
      </div>

      <EHRConnectionStatus patientId={PATIENT_ID} />

      {insufficientData && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-4 text-sm">
          <p className="font-medium text-amber-800 mb-1">More data needed</p>
          <p className="text-amber-700">
            Pattern analysis unlocks after {MIN_OBS} check-ins. You have{" "}
            <span className="font-bold">{obsCount}</span> so far.
          </p>
          <div className="mt-3 bg-amber-100 rounded-full h-2">
            <div
              className="bg-amber-500 h-2 rounded-full transition-all"
              style={{ width: `${Math.min(100, ((obsCount ?? 0) / MIN_OBS) * 100)}%` }}
            />
          </div>
        </div>
      )}

      {pageState === "idle" && !insufficientData && (
        <button
          onClick={() => void startAnalysis()}
          className="w-full bg-brand-600 hover:bg-brand-700 text-white font-semibold py-3 rounded-xl transition-colors"
        >
          Analyse my pattern →
        </button>
      )}

      {pageState === "loading" && (
        <div className="text-center py-12 text-slate-500 text-sm space-y-2">
          <div className="w-8 h-8 border-2 border-brand-500 border-t-transparent rounded-full animate-spin mx-auto" />
          <p>Comparing your symptom pattern against rare disease profiles…</p>
        </div>
      )}

      {pageState === "awaiting_review" && (
        <div className="bg-brand-50 border border-brand-100 rounded-xl p-5 space-y-3">
          <p className="text-sm font-medium text-brand-800">Analysis complete</p>
          <p className="text-sm text-brand-700">
            Review the results before they are shown. Patterns are for discussion with your specialist only.
          </p>
          <button
            onClick={() => void approveReport()}
            className="w-full bg-brand-600 hover:bg-brand-700 text-white font-semibold py-3 rounded-xl transition-colors text-sm"
          >
            Show my pattern analysis →
          </button>
        </div>
      )}

      {pageState === "approved" && report && (
        <div className="space-y-5">
          <div className="text-sm text-slate-600 bg-slate-50 rounded-xl p-4">
            {report.summary}
          </div>

          <h2 className="text-base font-semibold text-slate-700">
            Pattern profiles ({report.hypotheses.length})
          </h2>

          {report.hypotheses.map((h) => (
            <HypothesisCard key={h.condition_id} profile={h} />
          ))}

          <div className="text-xs text-slate-400 italic border-t border-slate-100 pt-4">
            {report.guardrail_disclosure}
          </div>
        </div>
      )}

      {pageState === "error" && error && (
        <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}
    </main>
  );
}
