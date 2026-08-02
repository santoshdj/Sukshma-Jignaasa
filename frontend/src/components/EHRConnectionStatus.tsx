"use client";

import { useEffect, useState } from "react";

interface EHRStatus {
  patient_id: string;
  connection_status: "not_connected" | "pending" | "active" | "failed";
  connected_at: string | null;
  fhir_resource_counts: Record<string, number>;
  last_synced_at: string | null;
}

interface Props {
  patientId: string;
}

export function EHRConnectionStatus({ patientId }: Props) {
  const [status, setStatus] = useState<EHRStatus | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`/api/ehr/status?patient_id=${encodeURIComponent(patientId)}`)
      .then((r) => r.json())
      .then(setStatus)
      .catch(() => null);
  }, [patientId]);

  const handleConnect = async () => {
    setConnecting(true);
    setConnectError(null);
    try {
      const returnUrl = `${window.location.origin}/ehr/connected?patient_id=${encodeURIComponent(patientId)}`;
      const res = await fetch("/api/ehr/connect/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ patient_id: patientId, return_url: returnUrl }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        throw new Error(typeof err.detail === "string" ? err.detail : JSON.stringify(err.detail));
      }
      const data = await res.json() as { auth_url: string };
      if (!data.auth_url) throw new Error("No auth_url returned from server");
      window.location.href = data.auth_url;
    } catch (err: unknown) {
      setConnectError(err instanceof Error ? err.message : "Connection failed");
      setConnecting(false);
    }
  };

  const totalRecords = status
    ? Object.values(status.fhir_resource_counts).reduce((a, b) => a + b, 0)
    : 0;

  if (!status || status.connection_status === "not_connected") {
    return (
      <div className="space-y-2">
        <div className="bg-slate-50 border border-slate-200 rounded-xl px-4 py-3 flex items-center justify-between gap-3">
          <div>
            <p className="text-sm font-medium text-slate-700">Health records not connected</p>
            <p className="text-xs text-slate-500">Connecting your EHR improves pattern analysis</p>
          </div>
          <button
            onClick={() => void handleConnect()}
            disabled={connecting}
            className="text-sm font-semibold text-brand-600 hover:text-brand-700 disabled:opacity-50 whitespace-nowrap"
          >
            {connecting ? "Redirecting…" : "Connect →"}
          </button>
        </div>
        {connectError && (
          <p className="text-xs text-red-600 px-1">{connectError}</p>
        )}
      </div>
    );
  }

  if (status.connection_status === "pending") {
    return (
      <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 text-sm text-amber-700">
        ⏳ Health records syncing — check back in a few minutes
      </div>
    );
  }

  if (status.connection_status === "active") {
    return (
      <div className="bg-brand-50 border border-brand-100 rounded-xl px-4 py-3 text-sm text-brand-700">
        ✓ {totalRecords > 0 ? `${totalRecords} health records connected` : "Health records connected — syncing…"}
      </div>
    );
  }

  return (
    <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 flex items-center justify-between">
      <span className="text-sm text-red-700">Connection failed</span>
      <button onClick={() => void handleConnect()} className="text-sm text-red-600 font-medium">
        Retry →
      </button>
    </div>
  );
}
