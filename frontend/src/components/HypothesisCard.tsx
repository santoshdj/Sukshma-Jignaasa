"use client";

interface HypothesisProfile {
  condition_id: string;
  condition_name: string;
  match_strength: "high" | "medium" | "low";
  matching_symptoms: string[];
  missing_signals: string[];
  plain_language_explanation: string;
  specialist_type: string;
  confidence_note: string;
  discuss_with_specialist: true;
}

const strengthConfig = {
  high: { label: "Strong pattern overlap", bg: "bg-brand-50", border: "border-brand-200", badge: "bg-brand-100 text-brand-700" },
  medium: { label: "Moderate pattern overlap", bg: "bg-amber-50", border: "border-amber-200", badge: "bg-amber-100 text-amber-700" },
  low: { label: "Some shared features", bg: "bg-slate-50", border: "border-slate-200", badge: "bg-slate-100 text-slate-600" },
};

interface Props {
  profile: HypothesisProfile;
}

export function HypothesisCard({ profile }: Props) {
  const cfg = strengthConfig[profile.match_strength];

  return (
    <div className={`rounded-xl border p-5 space-y-4 ${cfg.bg} ${cfg.border}`}>
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <h3 className="font-semibold text-slate-800 text-base leading-snug">
          {profile.condition_name}
        </h3>
        <span className={`text-xs font-semibold px-2.5 py-1 rounded-full whitespace-nowrap ${cfg.badge}`}>
          {cfg.label}
        </span>
      </div>

      {/* Plain language explanation */}
      <p className="text-sm text-slate-700 leading-relaxed">{profile.plain_language_explanation}</p>

      {/* Matching symptoms */}
      {profile.matching_symptoms.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1.5">
            Patterns in common
          </p>
          <div className="flex flex-wrap gap-1.5">
            {profile.matching_symptoms.map((s) => (
              <span key={s} className="text-xs bg-white border border-slate-200 text-slate-600 px-2 py-0.5 rounded-full">
                {s}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Missing signals */}
      {profile.missing_signals.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1.5">
            Ask your specialist about
          </p>
          <ul className="text-xs text-slate-600 space-y-1 list-disc list-inside">
            {profile.missing_signals.slice(0, 3).map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Confidence note */}
      <p className="text-xs text-slate-400 italic border-t border-slate-200 pt-3">
        {profile.confidence_note}
      </p>

      {/* Specialist CTA */}
      <div className="text-xs text-slate-500">
        <span className="font-medium">Who to see:</span> {profile.specialist_type}
      </div>
    </div>
  );
}
