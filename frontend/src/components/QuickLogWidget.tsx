"use client";

/**
 * QuickLogWidget — Step 1 of the check-in flow.
 * Patient taps known symptoms from their saved list,
 * adjusts severity with a slider, then proceeds to the AI chat.
 * They can also add a custom symptom via the "+ Add symptom" button.
 */

import { useRef, useState } from "react";
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

  // Custom-symptom input state
  const [showAddForm, setShowAddForm] = useState(false);
  const [customInput, setCustomInput] = useState("");
  const [customError, setCustomError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

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

  const openAddForm = () => {
    setShowAddForm(true);
    setCustomInput("");
    setCustomError("");
    // Focus the input on the next paint
    setTimeout(() => inputRef.current?.focus(), 50);
  };

  const cancelAdd = () => {
    setShowAddForm(false);
    setCustomInput("");
    setCustomError("");
  };

  const submitCustomSymptom = () => {
    const name = customInput.trim();
    if (!name) {
      setCustomError("Please enter a symptom name.");
      return;
    }
    if (name.length > 60) {
      setCustomError("Name must be 60 characters or fewer.");
      return;
    }
    const normalised = name.charAt(0).toUpperCase() + name.slice(1);
    if (isSelected(normalised)) {
      setCustomError("That symptom is already on your list.");
      return;
    }
    addQuickLogEntry({ symptom_name: normalised, severity: 5 });
    setActiveSeverity((prev) => ({ ...prev, [normalised]: 5 }));
    setCustomInput("");
    setCustomError("");
    setShowAddForm(false);
  };

  // All symptom names currently selected (preset + custom)
  const presetSet = new Set(SAVED_SYMPTOMS);
  const customSelected = quickLogEntries
    .map((e) => e.symptom_name)
    .filter((n) => !presetSet.has(n));

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-slate-800 mb-1">Quick log</h2>
        <p className="text-sm text-slate-500">Tap any symptoms you&apos;ve had today. Skip if feeling fine.</p>
      </div>

      {/* Preset symptom grid */}
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

      {/* Custom symptoms already added */}
      {customSelected.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {customSelected.map((name) => (
            <span
              key={name}
              className="inline-flex items-center gap-1.5 bg-brand-600 text-white text-sm font-medium px-3 py-2 rounded-xl"
            >
              {name}
              <button
                onClick={() => {
                  removeQuickLogEntry(name);
                  setActiveSeverity((prev) => {
                    const next = { ...prev };
                    delete next[name];
                    return next;
                  });
                }}
                className="ml-0.5 hover:opacity-75 transition-opacity"
                aria-label={`Remove ${name}`}
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Add symptom inline form */}
      {showAddForm ? (
        <div className="border border-brand-200 bg-brand-50 rounded-xl p-4 space-y-3">
          <p className="text-sm font-medium text-brand-800">Add a symptom</p>
          <div className="flex gap-2">
            <input
              ref={inputRef}
              type="text"
              value={customInput}
              onChange={(e) => {
                setCustomInput(e.target.value);
                setCustomError("");
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") submitCustomSymptom();
                if (e.key === "Escape") cancelAdd();
              }}
              placeholder="e.g. Chest tightness"
              maxLength={60}
              className="flex-1 border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-brand-500 bg-white"
            />
            <button
              onClick={submitCustomSymptom}
              className="bg-brand-600 hover:bg-brand-700 text-white text-sm font-semibold px-4 py-2 rounded-lg transition-colors"
            >
              Add
            </button>
            <button
              onClick={cancelAdd}
              className="text-slate-500 hover:text-slate-700 text-sm px-3 py-2 rounded-lg transition-colors"
            >
              Cancel
            </button>
          </div>
          {customError && (
            <p className="text-xs text-red-600">{customError}</p>
          )}
        </div>
      ) : (
        <button
          onClick={openAddForm}
          className="flex items-center gap-2 text-sm text-brand-600 hover:text-brand-700 font-medium transition-colors"
        >
          <span className="w-6 h-6 rounded-full border-2 border-brand-500 flex items-center justify-center flex-shrink-0">
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
          </span>
          Add a symptom not in the list
        </button>
      )}

      {/* Severity sliders for all selected symptoms */}
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
