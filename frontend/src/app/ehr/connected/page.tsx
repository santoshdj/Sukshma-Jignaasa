"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useState, Suspense } from "react";

export const dynamic = "force-dynamic";

function EHRReturnContent() {
  const params = useSearchParams();
  const [status, setStatus] = useState<"loading" | "connected" | "syncing" | "done" | "error">("loading");
  const [syncCounts, setSyncCounts] = useState<Record<string, number>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const patient_id = params.get("patient_id");
    const patient_session_id = params.get("patient_session_id");

    if (!patient_id || !patient_session_id) {
      setError("Invalid return URL — missing patient_id or patient_session_id.");
      setStatus("error");
      return;
    }

    (async () => {
      try {
        // Verify session server-side
        const completeRes = await fetch("/api/ehr/connect/complete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ patient_id, patient_session_id }),
        });
        if (!completeRes.ok) throw new Error("Session verification failed");
        setStatus("syncing");

        // Trigger FHIR record sync
        const syncRes = await fetch("/api/ehr/sync", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ patient_id }),
        });
        if (!syncRes.ok) throw new Error("Record sync failed");
        const syncData = await syncRes.json() as { synced_counts: Record<string, number> };
        setSyncCounts(syncData.synced_counts);
        setStatus("done");
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : "Connection failed");
        setStatus("error");
      }
    })();
  }, [params]);

  const totalRecords = Object.values(syncCounts).reduce((a, b) => a + b, 0);

  return (
    <main className="max-w-lg mx-auto px-4 py-16 text-center space-y-6">
      {status === "loading" && (
        <>
          <div className="w-10 h-10 border-2 border-brand-500 border-t-transparent rounded-full animate-spin mx-auto" />
          <p className="text-slate-500 text-sm">Verifying your connection…</p>
        </>
      )}

      {status === "syncing" && (
        <>
          <div className="w-10 h-10 border-2 border-brand-500 border-t-transparent rounded-full animate-spin mx-auto" />
          <p className="text-slate-500 text-sm">Syncing your health records…</p>
        </>
      )}

      {status === "done" && (
        <>
          <div className="text-5xl">✓</div>
          <h1 className="text-xl font-bold text-slate-800">Health records connected</h1>
          <p className="text-sm text-slate-500">
            {totalRecords > 0 ? `${totalRecords} records synced.` : "Records will appear shortly."}
          </p>
          {Object.keys(syncCounts).length > 0 && (
            <div className="text-left bg-slate-50 rounded-xl p-4 text-sm text-slate-600 space-y-1">
              {Object.entries(syncCounts).filter(([, n]) => n > 0).map(([type, count]) => (
                <div key={type} className="flex justify-between">
                  <span>{type}</span>
                  <span className="font-medium">{count}</span>
                </div>
              ))}
            </div>
          )}
          <a href="/" className="inline-block bg-brand-600 text-white font-semibold px-6 py-3 rounded-xl text-sm">
            Back to app →
          </a>
        </>
      )}

      {status === "error" && (
        <>
          <div className="text-5xl">⚠️</div>
          <h1 className="text-xl font-bold text-slate-800">Connection issue</h1>
          <p className="text-sm text-red-600">{error}</p>
          <a href="/" className="inline-block text-brand-600 text-sm font-medium">Back to app</a>
        </>
      )}
    </main>
  );
}

export default function EHRReturnPage() {
  return (
    <Suspense fallback={
      <main className="max-w-lg mx-auto px-4 py-16 text-center">
        <div className="w-10 h-10 border-2 border-brand-500 border-t-transparent rounded-full animate-spin mx-auto" />
      </main>
    }>
      <EHRReturnContent />
    </Suspense>
  );
}
