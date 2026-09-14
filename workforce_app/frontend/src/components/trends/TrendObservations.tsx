import React from 'react';
import { Lightbulb, CheckCircle2 } from 'lucide-react';

interface TrendObservationsProps {
  observations: string[];
}

export const TrendObservations: React.FC<TrendObservationsProps> = ({ observations }) => {
  if (!observations || observations.length === 0) return null;

  return (
    <div className="bg-white border border-app-border rounded-2xl p-5 md:p-6 shadow-subtle min-w-0">
      <div className="flex items-center gap-2 mb-3">
        <Lightbulb className="w-4 h-4 text-brand-blue shrink-0" />
        <h3 className="text-sm font-bold text-text-primary tracking-tight">
          Trend Observations
        </h3>
        <span className="text-[11px] text-text-muted">
          · Deterministic rule-based analytical insights
        </span>
      </div>

      <div className="space-y-2.5">
        {observations.map((obs, idx) => (
          <div
            key={idx}
            className="flex items-start gap-2.5 p-3 rounded-xl bg-app-bg/60 border border-app-border/60 text-xs text-text-primary leading-relaxed"
          >
            <CheckCircle2 className="w-4 h-4 text-brand-blue shrink-0 mt-0.5" />
            <span>{obs}</span>
          </div>
        ))}
      </div>
    </div>
  );
};
