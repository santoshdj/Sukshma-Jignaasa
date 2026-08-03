"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { EHRConnectionStatus } from "@/components/EHRConnectionStatus";
import { hypothesisApi } from "@/lib/api";

const PATIENT_ID = "patient-demo-001";
const MIN_OBS = 30;

type PageState = "idle" | "starting" | "error" | "loading";

export default function HypothesisPage() {
  const router = useRouter();
  const [pageState, setPageState] = useState<PageState>("loading");
  const [error, setError] = useState<string | null>(null);
  const [checkInCount, setCheckInCount] = useState<number>(0);
  const [ehrCount, setEhrCount] = useState<number>(0);
  const [totalCount, setTotalCount] = useState<number>(0);

  useEffect(() => {
    const fetchCounts = async () => {
      try {
        const counts = await hypothesisApi.getObservationCounts(PATIENT_ID);
        setCheckInCount(counts.check_ins);
        setEhrCount(counts.ehr_observations);
        setTotalCount(counts.total_observations);
        setPageState("idle");
      } catch (err) {
        console.error("Failed to fetch observation counts:", err);
        setPageState("idle");
      }
    };
    void fetchCounts();
  }, []);

  const startAnalysis = async () => {
    setPageState("starting");
    setError(null);
    try {
      const data = await hypothesisApi.start(PATIENT_ID);
      setCheckInCount(data.check_ins_available);
      setTotalCount(data.observations_available);
      // Redirect to the dedicated monitoring page immediately.
      // The analysis runs as a background task on the server; the new page polls /status.
      router.push(`/analysis/${data.session_id}`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Something went wrong";
      // Check for the 422 insufficient-data response embedded in the error message
      if (msg.includes("check_ins_available")) {
        try {
          const detail = JSON.parse(msg) as { check_ins_available: number; observations_available: number };
          setCheckInCount(detail.check_ins_available);
          setTotalCount(detail.observations_available);
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

  const insufficientData = checkInCount < MIN_OBS;

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

      {pageState === "loading" && (
        <div className="text-center py-8 text-slate-500 text-sm">
          <div className="w-8 h-8 border-2 border-brand-500 border-t-transparent rounded-full animate-spin mx-auto" />
        </div>
      )}

      {pageState !== "loading" && (
        <div className="bg-slate-50 border border-slate-200 rounded-xl px-4 py-4 space-y-3">
          <p className="font-medium text-slate-700 text-sm">Your data summary</p>
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-white rounded-lg px-3 py-2 border border-slate-200">
              <p className="text-xs text-slate-500">Check-ins completed</p>
              <p className="text-2xl font-bold text-brand-600">{checkInCount}</p>
              <p className="text-xs text-slate-400 mt-1">Daily symptom logs</p>
            </div>
            <div className="bg-white rounded-lg px-3 py-2 border border-slate-200">
              <p className="text-xs text-slate-500">Health records</p>
              <p className="text-2xl font-bold text-slate-700">{ehrCount}</p>
              <p className="text-xs text-slate-400 mt-1">From EHR system</p>
            </div>
          </div>
          <div className="text-xs text-slate-500 pt-1">
            Total observations: <span className="font-medium text-slate-700">{totalCount}</span>
          </div>
        </div>
      )}

      {insufficientData && pageState !== "loading" && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-4 text-sm">
          <p className="font-medium text-amber-800 mb-1">More check-ins needed</p>
          <p className="text-amber-700">
            Pattern analysis requires {MIN_OBS} check-ins. You have completed{" "}
            <span className="font-bold">{checkInCount}</span> so far.
          </p>
          <div className="mt-3 bg-amber-100 rounded-full h-2">
            <div
              className="bg-amber-500 h-2 rounded-full transition-all"
              style={{ width: `${Math.min(100, (checkInCount / MIN_OBS) * 100)}%` }}
            />
          </div>
          <p className="text-xs text-amber-600 mt-2">
            Keep logging your daily symptoms to unlock pattern analysis.
          </p>
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
