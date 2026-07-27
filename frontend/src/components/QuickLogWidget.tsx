"use client";

/**
 * QuickLogWidget — Step 1 of the check-in flow.
 * Patient taps known symptoms from their saved list,
 * adjusts severity with a slider, then proceeds to the AI chat.
 */

import { useState } from "react";
import { useCheckInStore, type QuickLogEntry } from "@/store/checkInStore";

const SAVED_SYMPTOMS = [
  "Fatigue",
  "Joint pain",
  "Brain fog",
  "Dizziness",
  "Nausea",
  "Headache",
  "Palpitations",
  "Muscle pain",
];

interface Props {
  onContinue: () => void;
}

export function QuickLogWidget({ onContinue }: Props) {
  const { quickLogEntries, addQuickLogEntry, removeQuickLogEntry } = useCheckInStore();
  const [activeSeverity, setActiveSeverity] = useState<Record<string, number>>({});

  const isSelected = (name: string) =>
    quickLogEntries.some((e) => e.symptom_name === name);

  const toggleSymptom = (name: string) => {
    if (isSelected(name)) {
      removeQuickLogEntry(name);
      setActiveSeverity((prev) => {
        const next = { ...prev };
        delete next[name];
        return next;
      });
    } else {
      const severity = activeSeverity[name] ?? 5;
      addQuickLogEntry({ symptom_name: name, severity });
      setActiveSeverity((prev) => ({ ...prev, [name]: severity }));
    }
  };

  const updateSeverity = (name: string, value: number) => {
    setActiveSeverity((prev) => ({ ...prev, [name]: value }));
    if (isSelected(name)) {
      addQuickLogEntry({ symptom_name: name, severity: value });
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-slate-800 mb-1">Quick log</h2>
        <p className="text-sm text-slate-500">Tap any symptoms you've had today. Skip if feeling fine.</p>
      </div>

      <div className="grid grid-cols-2 gap-2">
        {SAVED_SYMPTOMS.map((name) => {
          const selected = isSelected(name);
          return (
            <button
              key={name}
              onClick={() => toggleSymptom(name)}
              className={`rounded-xl px-4 py-3 text-sm font-medium text-left transition-all border ${
                selected
                  ? "bg-brand-600 text-white border-brand-600"
                  : "bg-white text-slate-700 border-slate-200 hover:border-brand-500"
              }`}
            >
              {name}
            </button>
          );
        })}
      </div>

      {quickLogEntries.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-sm font-semibold text-slate-600 uppercase tracking-wide">
            Set severity
          </h3>
          {quickLogEntries.map((entry) => (
            <div key={entry.symptom_name} className="bg-white rounded-xl p-4 border border-slate-200">
              <div className="flex justify-between items-center mb-2">
                <span className="text-sm font-medium text-slate-700">{entry.symptom_name}</span>
                <span className="text-sm font-bold text-brand-600">
                  {activeSeverity[entry.symptom_name] ?? entry.severity}/10
                </span>
              </div>
              <input
                type="range"
                min={1}
                max={10}
                value={activeSeverity[entry.symptom_name] ?? entry.severity}
                onChange={(e) => updateSeverity(entry.symptom_name, Number(e.target.value))}
                className="w-full accent-brand-600"
              />
            </div>
          ))}
        </div>
      )}

      <div className="flex gap-3 pt-2">
        <button
          onClick={onContinue}
          className="flex-1 bg-brand-600 hover:bg-brand-700 text-white font-semibold py-3 rounded-xl transition-colors"
        >
          {quickLogEntries.length > 0 ? "Continue to check-in →" : "Nothing today — start check-in →"}
        </button>
      </div>
    </div>
  );
}
