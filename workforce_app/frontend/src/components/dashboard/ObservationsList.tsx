import React from 'react';
import { Lightbulb, AlertCircle, ShieldAlert, CheckCircle2, Clock } from 'lucide-react';
import { Observation } from '../../types/workforce';

interface ObservationsListProps {
  observations: Observation[];
}

export const ObservationsList: React.FC<ObservationsListProps> = ({ observations }) => {
  const getIcon = (type: Observation['type']) => {
    switch (type) {
      case 'attendance':
        return <AlertCircle className="w-4 h-4 text-brand-warning shrink-0" />;
      case 'data_quality':
        return <ShieldAlert className="w-4 h-4 text-brand-critical shrink-0" />;
      case 'policy':
        return <CheckCircle2 className="w-4 h-4 text-brand-blue shrink-0" />;
      case 'approval':
        return <Clock className="w-4 h-4 text-brand-info shrink-0" />;
      default:
        return <Lightbulb className="w-4 h-4 text-brand-blue shrink-0" />;
    }
  };

  return (
    <div className="bg-white border border-app-border rounded-xl p-6 shadow-subtle mb-6">
      <div className="flex items-center gap-2 mb-4">
        <Lightbulb className="w-4 h-4 text-amber-500" />
        <h3 className="text-base font-bold text-text-primary tracking-tight">
          Key Observations
        </h3>
        <span className="text-xs text-text-muted">
          · Deterministic process signals
        </span>
      </div>

      {observations.length === 0 ? (
        <p className="text-xs text-text-muted">No observations generated for this selection.</p>
      ) : (
        <div className="space-y-3">
          {observations.map((obs, idx) => (
            <div
              key={idx}
              className="flex items-start gap-3 p-3.5 rounded-lg bg-app-bg/80 border border-app-border/70 hover:border-app-border transition-colors"
            >
              <div className="mt-0.5">{getIcon(obs.type)}</div>
              <p className="text-xs font-medium text-text-primary leading-relaxed">
                {obs.text}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
