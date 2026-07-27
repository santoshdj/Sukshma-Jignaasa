"use client";

/**
 * Check-in page — orchestrates the three-step flow:
 *   1. QuickLogWidget  (tap known symptoms)
 *   2. CheckInChat     (AI conversation)
 *   3. ConfirmationCard (review + confirm)
 *   4. Saved state
 *
 * The session is started (POST /check-in/start) when the patient
 * taps "Continue" from the quick-log step, before the first message.
 */

import { useState } from "react";
import { QuickLogWidget } from "@/components/QuickLogWidget";
import { CheckInChat } from "@/components/CheckInChat";
import { ConfirmationCard } from "@/components/ConfirmationCard";
import { useCheckInStore, type ConfirmationSummary } from "@/store/checkInStore";
import { checkInApi } from "@/lib/api";

type Step = "quick-log" | "chat" | "confirm" | "saved";

export default function CheckInPage() {
  const {
    patientId,
    quickLogEntries,
    confirmationSummary,
    savedObservationIds,
    setSession,
    setError,
    reset,
  } = useCheckInStore();

  const [step, setStep] = useState<Step>("quick-log");
  const [isStarting, setIsStarting] = useState(false);
  const [pendingSummary, setPendingSummary] = useState<ConfirmationSummary | null>(null);

  const handleQuickLogContinue = async () => {
    setIsStarting(true);
    try {
      const res = await checkInApi.start(patientId, quickLogEntries);
      setSession(res.session_id, res.ai_message);
      setStep("chat");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to start session");
    } finally {
      setIsStarting(false);
    }
  };

  const handleConfirmationReady = (summary: ConfirmationSummary) => {
    setPendingSummary(summary);
    setStep("confirm");
  };

  const handleSaved = (ids: string[]) => {
    void ids;
    setStep("saved");
  };

  const handleEditBack = () => {
    setStep("chat");
    setPendingSummary(null);
  };

  const handleStartAgain = () => {
    reset();
    setPendingSummary(null);
    setStep("quick-log");
  };

  return (
    <main className="max-w-lg mx-auto px-4 py-8 min-h-screen flex flex-col">
      {/* Header */}
      <div className="mb-6">
        <a href="/" className="text-xs text-slate-400 hover:text-slate-600 mb-3 inline-block">
          ← Home
        </a>
        <h1 className="text-xl font-bold text-slate-800">Daily check-in</h1>
        <p className="text-sm text-slate-500 mt-1">
          {step === "quick-log" && "Start by tapping any symptoms you've noticed today."}
          {step === "chat" && "Tell the AI how you're feeling in your own words."}
          {step === "confirm" && "Review what was captured before saving."}
          {step === "saved" && "Logged successfully."}
        </p>
      </div>

      {/* Step indicator */}
      <div className="flex gap-1.5 mb-6">
        {(["quick-log", "chat", "confirm", "saved"] as Step[]).map((s, i) => (
          <div
            key={s}
            className={`h-1.5 flex-1 rounded-full transition-colors ${
              s === step
                ? "bg-brand-600"
                : i < (["quick-log", "chat", "confirm", "saved"] as Step[]).indexOf(step)
                ? "bg-brand-200"
                : "bg-slate-200"
            }`}
          />
        ))}
      </div>

      {/* Step content */}
      <div className="flex-1 flex flex-col">
        {step === "quick-log" && (
          <QuickLogWidget
            onContinue={() => void handleQuickLogContinue()}
          />
        )}

        {isStarting && (
          <div className="text-center text-slate-400 text-sm py-8">Starting check-in…</div>
        )}

        {step === "chat" && !isStarting && (
          <div className="flex-1 flex flex-col" style={{ minHeight: "400px" }}>
            <CheckInChat onConfirmationReady={handleConfirmationReady} />
          </div>
        )}

        {step === "confirm" && (pendingSummary ?? confirmationSummary) && (
          <ConfirmationCard
            summary={(pendingSummary ?? confirmationSummary)!}
            onSaved={handleSaved}
            onEdit={handleEditBack}
          />
        )}

        {step === "saved" && (
          <div className="text-center space-y-4 py-8">
            <div className="text-5xl">✓</div>
            <h2 className="text-xl font-semibold text-slate-800">Logged</h2>
            <p className="text-slate-500 text-sm">
              {savedObservationIds.length > 0
                ? `${savedObservationIds.length} observation${savedObservationIds.length > 1 ? "s" : ""} saved to your health record.`
                : "Your check-in has been saved."}
            </p>
            <button
              onClick={handleStartAgain}
              className="mt-4 text-brand-600 hover:text-brand-700 text-sm font-medium underline underline-offset-2"
            >
              Log another day
            </button>
          </div>
        )}
      </div>
    </main>
  );
}
