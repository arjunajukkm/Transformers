import React from 'react';
import { Sparkles, Activity, Layers, Users } from 'lucide-react';
import { PatternSummary } from '../../types/workforce';

interface PatternSummaryCardsProps {
  summary: PatternSummary;
}

export const PatternSummaryCards: React.FC<PatternSummaryCardsProps> = ({ summary }) => {
  const cards = [
    {
      title: 'Patterns Detected',
      value: summary.total_patterns,
      subtitle: 'Deterministic behavioral patterns',
      icon: Sparkles,
      iconBg: 'bg-blue-50 text-brand-blue',
      borderColor: 'border-blue-100',
    },
    {
      title: 'Active Patterns',
      value: summary.active_patterns,
      subtitle: 'Observed within latest 30 days',
      icon: Activity,
      iconBg: 'bg-emerald-50 text-emerald-600',
      borderColor: 'border-emerald-100',
    },
    {
      title: 'High Recurrence',
      value: summary.high_strength_patterns,
      subtitle: 'Strong persistence across periods',
      icon: Layers,
      iconBg: 'bg-purple-50 text-purple-600',
      borderColor: 'border-purple-100',
    },
    {
      title: 'Entities Observed',
      value: summary.employees_with_patterns + summary.managers_with_patterns,
      subtitle: `${summary.employees_with_patterns} employees, ${summary.managers_with_patterns} managers/teams`,
      icon: Users,
      iconBg: 'bg-slate-100 text-slate-700',
      borderColor: 'border-slate-200',
    },
  ];

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      {cards.map((card, idx) => {
        const IconComponent = card.icon;
        return (
          <div
            key={idx}
            className={`bg-white rounded-xl p-4 border ${card.borderColor} shadow-subtle flex flex-col justify-between transition-all hover:shadow-md`}
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold text-app-text-secondary tracking-wide uppercase">
                {card.title}
              </span>
              <div className={`p-2 rounded-lg ${card.iconBg}`}>
                <IconComponent className="w-4 h-4" />
              </div>
            </div>
            <div>
              <div className="text-2xl font-bold text-app-text-primary tracking-tight">
                {card.value}
              </div>
              <div className="text-xs text-app-text-muted mt-1 truncate" title={card.subtitle}>
                {card.subtitle}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
};
