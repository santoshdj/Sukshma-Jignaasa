"use client";

import { useEffect, useState } from "react";
import { hypothesisApi, type HypothesisSessionSummary } from "@/lib/api";

const PATIENT_ID = "patient-demo-001";

// ── Status badge ─────────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<
  string,
  { label: string; dot: string; badge: string }
> = {
  running:          { label: "In progress",      dot: "bg-brand-500 animate-pulse", badge: "bg-brand-50 text-brand-700 border-brand-200" },
  awaiting_review:  { label: "Ready to review",  dot: "bg-amber-500",               badge: "bg-amber-50 text-amber-700 border-amber-200" },
  approved:         { label: "Reviewed",          dot: "bg-emerald-500",             badge: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  failed:           { label: "Failed",            dot: "bg-red-400",                 badge: "bg-red-50 text-red-700 border-red-200" },
  regenerate:       { label: "Regenerating",      dot: "bg-brand-500 animate-pulse", badge: "bg-brand-50 text-brand-700 border-brand-200" },
};

function StatusBadge({ status }: { status: string }) {
  const cfg = STATUS_CONFIG[status] ?? {
    label: status,
    dot: "bg-slate-400",
    badge: "bg-slate-50 text-slate-600 border-slate-200",
  };
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-medium ${cfg.badge}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${cfg.dot}`} />
      {cfg.label}
    </span>
  );
}

// ── Relative date ─────────────────────────────────────────────────────────────

function relativeDate(isoString: string | null): string {
  if (!isoString) return "Unknown date";
  const diff = Date.now() - new Date(isoString).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(isoString).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

// ── Session card ──────────────────────────────────────────────────────────────

function SessionCard({ session }: { session: HypothesisSessionSummary }) {
  const canResume = ["running", "awaiting_review", "regenerate"].includes(session.status);
  const isComplete = session.status === "approved";
  const isFailed   = session.status === "failed";

  return (
    <a
      href={`/analysis/${session.session_id}`}
      className="block bg-white border border-slate-200 rounded-2xl p-5 hover:border-brand-300 hover:shadow-sm transition-all group"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1 min-w-0">
          <p className="text-sm font-medium text-slate-800 truncate">
            Analysis · {relativeDate(session.created_at)}
          </p>
          <p className="text-xs text-slate-400">
            {session.observation_count} observations used
            {isComplete && session.hypothesis_count > 0 && (
              <> · <span className="text-emerald-600">{session.hypothesis_count} pattern profile{session.hypothesis_count !== 1 ? "s" : ""}</span></>
            )}
          </p>
        </div>
        <StatusBadge status={session.status} />
      </div>

      <div className="mt-4 flex items-center justify-between">
        <div className="text-xs text-slate-400">
          {session.updated_at && session.updated_at !== session.created_at
            ? `Updated ${relativeDate(session.updated_at)}`
            : ""}
        </div>
        <span className={`text-xs font-medium flex items-center gap-1 transition-colors ${
          isFailed ? "text-red-500" : "text-brand-600 group-hover:text-brand-700"
        }`}>
          {canResume && "Continue →"}
          {isComplete && "View report →"}
          {isFailed && "View details →"}
        </span>
      </div>
    </a>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

type LoadState = "loading" | "loaded" | "error";

export default function AnalysesPage() {
  const [sessions, setSessions] = useState<HypothesisSessionSummary[]>([]);
  const [loadState, setLoadState] = useState<LoadState>("loading");

  useEffect(() => {
    hypothesisApi
      .listSessions(PATIENT_ID)
      .then((data) => {
        setSessions(data);
        setLoadState("loaded");
      })
      .catch(() => setLoadState("error"));
  }, []);

  const inProgress  = sessions.filter((s) => ["running", "regenerate"].includes(s.status));
  const readyToView = sessions.filter((s) => s.status === "awaiting_review");
  const completed   = sessions.filter((s) => s.status === "approved");
  const failed      = sessions.filter((s) => s.status === "failed");

  return (
    <main className="max-w-lg mx-auto px-4 py-8 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <a href="/" className="text-xs text-slate-400 hover:text-slate-600 mb-3 inline-block">← Home</a>
          <h1 className="text-xl font-bold text-slate-800">My pattern analyses</h1>
          <p className="text-sm text-slate-500 mt-1">
            All your symptom pattern analyses, past and present.
          </p>
        </div>
        <a
          href="/hypothesis"
          className="mt-6 flex-shrink-0 bg-brand-600 hover:bg-brand-700 text-white text-sm font-semibold px-4 py-2 rounded-xl transition-colors"
        >
          New analysis
        </a>
      </div>

      {/* Loading */}
      {loadState === "loading" && (
        <div className="text-center py-12 text-slate-400 text-sm space-y-2">
          <div className="w-7 h-7 border-2 border-brand-400 border-t-transparent rounded-full animate-spin mx-auto" />
          <p>Loading your analyses…</p>
        </div>
      )}

      {/* Error */}
      {loadState === "error" && (
        <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-sm text-red-700">
          Couldn&apos;t load your analyses. Check your connection and refresh.
        </div>
      )}

      {/* Empty state */}
      {loadState === "loaded" && sessions.length === 0 && (
        <div className="text-center py-12 space-y-3">
          <p className="text-slate-500 text-sm">No analyses yet.</p>
          <a
            href="/hypothesis"
            className="inline-block bg-brand-600 hover:bg-brand-700 text-white text-sm font-semibold px-5 py-2.5 rounded-xl transition-colors"
          >
            Start your first analysis →
          </a>
        </div>
      )}

      {/* In progress */}
      {inProgress.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-400">In progress</h2>
          {inProgress.map((s) => <SessionCard key={s.session_id} session={s} />)}
        </section>
      )}

      {/* Ready to review */}
      {readyToView.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-amber-500">Ready to review</h2>
          {readyToView.map((s) => <SessionCard key={s.session_id} session={s} />)}
        </section>
      )}

      {/* Completed */}
      {completed.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Completed</h2>
          {completed.map((s) => <SessionCard key={s.session_id} session={s} />)}
        </section>
      )}

      {/* Failed */}
      {failed.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-red-400">Failed</h2>
          {failed.map((s) => <SessionCard key={s.session_id} session={s} />)}
        </section>
      )}
    </main>
  );
}
