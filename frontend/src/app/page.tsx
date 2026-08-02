"use client";

import { EHRConnectionStatus } from "@/components/EHRConnectionStatus";

const PATIENT_ID = "patient-demo-001";

export default function HomePage() {
  return (
    <main className="max-w-lg mx-auto px-4 py-12 space-y-6">
      <div className="text-center pt-4 pb-2">
        <h1 className="text-3xl font-bold text-slate-800 mb-1">सूक्ष्म जिज्ञासा</h1>
        <p className="text-xs font-medium text-slate-400 tracking-widest uppercase mb-3">
          Sukshma Jijñāsā &nbsp;·&nbsp; The Subtle Inquiry
        </p>
        <p className="text-slate-500 text-sm">Your AI companion for rare disease pattern tracking.</p>
      </div>

      {/* EHR connection — triggers redirect to Medblocks OAuth */}
      <EHRConnectionStatus patientId={PATIENT_ID} />

      {/* Navigation */}
      <div className="flex flex-col gap-3 pt-2">
        <a
          href="/check-in"
          className="block text-center bg-brand-600 hover:bg-brand-700 text-white font-semibold px-6 py-3 rounded-xl transition-colors"
        >
          Log today →
        </a>
        <a
          href="/hypothesis"
          className="block text-center bg-white border border-slate-200 hover:border-brand-400 text-slate-700 font-semibold px-6 py-3 rounded-xl transition-colors"
        >
          View pattern analysis →
        </a>
      </div>
    </main>
  );
}
