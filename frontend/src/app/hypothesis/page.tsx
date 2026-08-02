"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { EHRConnectionStatus } from "@/components/EHRConnectionStatus";
import { hypothesisApi } from "@/lib/api";

const PATIENT_ID = "patient-demo-001";
const MIN_OBS = 30;

type PageState = "idle" | "starting" | "error";

export default function HypothesisPage() {
  const router = useRouter();
  const [pageState, setPageState] = useState<PageState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [obsCount, setObsCount] = useState<number | null>(null);

  const startAnalysis = async () => {
    setPageState("starting");
    setError(null);
    try {
      const data = await hypothesisApi.start(PATIENT_ID);
      setObsCount(data.observations_available);
      // Redirect to the dedicated monitoring page immediately.
      // The analysis runs as a background task on the server; the new page polls /status.
      router.push(`/analysis/${data.session_id}`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Something went wrong";
      // Check for the 422 insufficient-data response embedded in the error message
      if (msg.includes("observations_available")) {
        try {
          const detail = JSON.parse(msg) as { observations_available: number };
          setObsCount(detail.observations_available);
        } catch {
          // ignore parse failure
        }
        setPageState("idle");
      } else {
        setError(msg);
        setPageState("error");
      }
    }
  };

  const insufficientData = obsCount !== null && obsCount < MIN_OBS;

  return (
    <main className="max-w-lg mx-auto px-4 py-8 space-y-6">
      <div>
        <a href="/" className="text-xs text-slate-400 hover:text-slate-600 mb-3 inline-block">← Home</a>
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-xl font-bold text-slate-800">Pattern analysis</h1>
            <p className="text-sm text-slate-500 mt-1">
              Compare your symptom pattern against rare disease profiles.
            </p>
          </div>
          <a
            href="/analyses"
            className="text-xs text-brand-600 hover:text-brand-700 font-medium mt-1 flex-shrink-0"
          >
            My analyses →
          </a>
        </div>
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

      {pageState === "starting" && (
        <div className="text-center py-8 text-slate-500 text-sm space-y-2">
          <div className="w-8 h-8 border-2 border-brand-500 border-t-transparent rounded-full animate-spin mx-auto" />
          <p>Starting your analysis…</p>
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
