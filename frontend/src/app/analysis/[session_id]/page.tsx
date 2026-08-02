"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { HypothesisCard } from "@/components/HypothesisCard";
import {
  hypothesisApi,
  downloadClinicalReport,
  type HypothesisReport,
} from "@/lib/api";

const PATIENT_ID = "patient-demo-001";
const POLL_INTERVAL_MS = 3000;

// ── Progress steps shown while the analysis runs in the background ───────────

const STEPS = [
  { label: "Fetching your symptom observations", ms: 0 },
  { label: "Building your symptom fingerprint", ms: 4000 },
  { label: "Matching against rare disease profiles", ms: 9000 },
  { label: "Generating your analysis report", ms: 16000 },
] as const;

function ProgressStep({
  label,
  done,
  active,
}: {
  label: string;
  done: boolean;
  active: boolean;
}) {
  return (
    <li className="flex items-center gap-3 text-sm">
      {done ? (
        <span className="w-5 h-5 rounded-full bg-emerald-500 flex items-center justify-center flex-shrink-0">
          <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
          </svg>
        </span>
      ) : active ? (
        <span className="w-5 h-5 flex-shrink-0 flex items-center justify-center">
          <span className="w-4 h-4 border-2 border-brand-500 border-t-transparent rounded-full animate-spin" />
        </span>
      ) : (
        <span className="w-5 h-5 rounded-full border-2 border-slate-200 flex-shrink-0" />
      )}
      <span className={done ? "text-slate-500 line-through" : active ? "text-slate-800 font-medium" : "text-slate-400"}>
        {label}
      </span>
    </li>
  );
}

// ── Match strength badge ──────────────────────────────────────────────────────

const STRENGTH_STYLES = {
  high: "bg-red-100 text-red-700 border-red-200",
  medium: "bg-amber-100 text-amber-700 border-amber-200",
  low: "bg-green-100 text-green-700 border-green-200",
};

// ── Page states ───────────────────────────────────────────────────────────────

type AnalysisPageState =
  | "polling"           // background task running — polling /status
  | "awaiting_review"   // analysis done — prompting patient to review
  | "reviewing"         // report loaded, patient reading
  | "approved"          // patient approved — ready to download PDF
  | "generating_pdf"    // PDF download in flight
  | "pdf_ready"         // PDF downloaded successfully
  | "failed";

export default function AnalysisPage() {
  const params = useParams();
  const sessionId = Array.isArray(params.session_id)
    ? params.session_id[0]
    : (params.session_id as string);

  const [state, setState] = useState<AnalysisPageState>("polling");
  const [report, setReport] = useState<HypothesisReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pdfFilename, setPdfFilename] = useState<string | null>(null);

  // Track elapsed ms for the fake progress steps
  const [elapsedMs, setElapsedMs] = useState(0);
  const startedAt = useRef<number>(Date.now());
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const elapsedRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Polling logic ─────────────────────────────────────────────────────────

  const stopPolling = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current);
    if (elapsedRef.current) clearInterval(elapsedRef.current);
    pollRef.current = null;
    elapsedRef.current = null;
  }, []);

  const checkStatus = useCallback(async () => {
    if (!sessionId) return;
    try {
      const status = await hypothesisApi.getStatus(sessionId);
      if (status.status === "awaiting_review") {
        stopPolling();
        setState("awaiting_review");
      } else if (status.status === "failed") {
        stopPolling();
        setError("Pattern analysis failed. Please go back and try again.");
        setState("failed");
      }
      // status === "running" → keep polling
    } catch {
      // Transient network error — keep polling, don't fail yet
    }
  }, [sessionId, stopPolling]);

  useEffect(() => {
    if (!sessionId) return;

    // Elapsed-time ticker for the fake progress steps
    elapsedRef.current = setInterval(() => {
      setElapsedMs(Date.now() - startedAt.current);
    }, 500);

    // Status poll
    void checkStatus(); // immediate first check
    pollRef.current = setInterval(() => void checkStatus(), POLL_INTERVAL_MS);

    return stopPolling;
  }, [sessionId, checkStatus, stopPolling]);

  // ── User actions ──────────────────────────────────────────────────────────

  const reviewReport = async () => {
    if (!sessionId) return;
    try {
      await hypothesisApi.approve(sessionId, "approve");
      const data = await hypothesisApi.getReport(sessionId);
      setReport(data);
      setState("reviewing");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load report");
      setState("failed");
    }
  };

  const approveReport = () => {
    setState("approved");
  };

  const downloadReport = async () => {
    if (!sessionId) return;
    setState("generating_pdf");
    try {
      const filename = await downloadClinicalReport({
        patientId: PATIENT_ID,
        hypothesisSessionId: sessionId,
      });
      setPdfFilename(filename);
      setState("pdf_ready");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to generate report");
      setState("approved"); // let them retry
    }
  };

  // ── Derived progress step index ───────────────────────────────────────────

  const activeStep = STEPS.findLastIndex((s) => elapsedMs >= s.ms);

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <main className="max-w-lg mx-auto px-4 py-8 space-y-6">
      {/* Header */}
      <div>
        <a href="/hypothesis" className="text-xs text-slate-400 hover:text-slate-600 mb-3 inline-block">
          ← Pattern analysis
        </a>
        <h1 className="text-xl font-bold text-slate-800">Your pattern analysis</h1>
        <p className="text-sm text-slate-500 mt-1">
          Comparing your symptom history against rare disease profiles.
        </p>
      </div>

      {/* ── POLLING: analysis running ── */}
      {state === "polling" && (
        <div className="bg-white border border-slate-200 rounded-2xl p-6 space-y-5 shadow-sm">
          <div className="flex items-center gap-3">
            <span className="w-8 h-8 border-2 border-brand-500 border-t-transparent rounded-full animate-spin flex-shrink-0" />
            <div>
              <p className="font-semibold text-slate-800 text-sm">Analysis in progress</p>
              <p className="text-xs text-slate-400">This takes around 20–40 seconds</p>
            </div>
          </div>

          <ul className="space-y-3 pl-1">
            {STEPS.map((step, i) => (
              <ProgressStep
                key={step.label}
                label={step.label}
                done={i < activeStep}
                active={i === activeStep}
              />
            ))}
          </ul>

          <p className="text-xs text-slate-400 text-center">
            You can{" "}
            <a href="/analyses" className="underline underline-offset-2 hover:text-slate-600">
              leave this page and come back
            </a>{" "}
            — the analysis continues in the background.
          </p>
        </div>
      )}

      {/* ── AWAITING REVIEW: analysis complete, patient hasn't read yet ── */}
      {state === "awaiting_review" && (
        <div className="bg-emerald-50 border border-emerald-200 rounded-2xl p-6 space-y-4">
          <div className="flex items-start gap-3">
            <span className="w-8 h-8 rounded-full bg-emerald-500 flex items-center justify-center flex-shrink-0">
              <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </span>
            <div>
              <p className="font-semibold text-emerald-900">Analysis complete</p>
              <p className="text-sm text-emerald-700 mt-0.5">
                We&apos;ve found pattern profiles to discuss with your specialist.
              </p>
            </div>
          </div>

          <div className="bg-emerald-100/60 rounded-xl p-4 text-sm text-emerald-800 space-y-1">
            <p className="font-medium">Before you read the results</p>
            <p>
              These profiles show <strong>pattern similarities only</strong> — they are not a diagnosis.
              Review them at your own pace, then share them with a specialist who can assess your full history.
            </p>
          </div>

          <button
            onClick={() => void reviewReport()}
            className="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-semibold py-3 rounded-xl transition-colors text-sm"
          >
            Review my analysis →
          </button>
        </div>
      )}

      {/* ── REVIEWING: report loaded, patient reading ── */}
      {(state === "reviewing" || state === "approved" || state === "generating_pdf" || state === "pdf_ready") && report && (
        <div className="space-y-6">
          {/* Summary */}
          <div className="text-sm text-slate-600 bg-slate-50 rounded-xl p-4 leading-relaxed">
            {report.summary}
          </div>

          {/* Profile cards */}
          <div>
            <h2 className="text-base font-semibold text-slate-700 mb-3">
              Pattern profiles ({report.hypotheses.length})
            </h2>
            <div className="space-y-4">
              {report.hypotheses.map((h) => (
                <HypothesisCard key={h.condition_id} profile={h} />
              ))}
            </div>
          </div>

          {/* Guardrail */}
          <p className="text-xs text-slate-400 italic border-t border-slate-100 pt-4">
            {report.guardrail_disclosure}
          </p>

          {/* Approval + PDF section */}
          {state === "reviewing" && (
            <div className="bg-slate-50 border border-slate-200 rounded-2xl p-5 space-y-3">
              <p className="text-sm font-medium text-slate-700">Ready to share with your specialist?</p>
              <p className="text-xs text-slate-500">
                Confirm you&apos;ve reviewed these profiles, then generate a PDF clinical report to bring to your appointment.
              </p>
              <button
                onClick={approveReport}
                className="w-full bg-brand-600 hover:bg-brand-700 text-white font-semibold py-3 rounded-xl transition-colors text-sm"
              >
                I&apos;ve reviewed — generate my report →
              </button>
            </div>
          )}

          {(state === "approved" || state === "generating_pdf") && (
            <div className="bg-brand-50 border border-brand-100 rounded-2xl p-5 space-y-3">
              <p className="text-sm font-medium text-brand-800">Generate your clinical report</p>
              <p className="text-xs text-brand-700">
                A formatted PDF including your symptom profiles and this pattern analysis — ready to hand to a specialist.
              </p>
              <button
                onClick={() => void downloadReport()}
                disabled={state === "generating_pdf"}
                className="w-full bg-brand-600 hover:bg-brand-700 disabled:opacity-60 text-white font-semibold py-3 rounded-xl transition-colors text-sm flex items-center justify-center gap-2"
              >
                {state === "generating_pdf" ? (
                  <>
                    <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                    Generating PDF…
                  </>
                ) : (
                  <>
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M12 10v6m0 0l-3-3m3 3l3-3M3 17V7a2 2 0 012-2h6l2 2h6a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z" />
                    </svg>
                    Download clinical report PDF
                  </>
                )}
              </button>
            </div>
          )}

          {state === "pdf_ready" && pdfFilename && (
            <div className="bg-emerald-50 border border-emerald-200 rounded-2xl p-5 space-y-3">
              <div className="flex items-center gap-2 text-emerald-700">
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <p className="font-medium text-sm">Your report is ready</p>
              </div>
              <p className="text-xs text-emerald-600">
                <strong>{pdfFilename}</strong> has been downloaded to your device.
              </p>
              <button
                onClick={() => void downloadReport()}
                className="text-xs text-emerald-700 underline underline-offset-2"
              >
                Download again
              </button>
            </div>
          )}
        </div>
      )}

      {/* ── FAILED ── */}
      {state === "failed" && (
        <div className="bg-red-50 border border-red-200 rounded-2xl px-5 py-4 space-y-3">
          <p className="text-sm font-medium text-red-800">Analysis failed</p>
          <p className="text-sm text-red-700">{error ?? "Something went wrong. Please try again."}</p>
          <a
            href="/hypothesis"
            className="inline-block text-sm text-red-700 underline underline-offset-2"
          >
            ← Go back and try again
          </a>
        </div>
      )}
    </main>
  );
}
