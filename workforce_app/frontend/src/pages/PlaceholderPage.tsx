import React from 'react';
import { Sparkles } from 'lucide-react';

interface PlaceholderPageProps {
  title: string;
  subtitle: string;
}

export const PlaceholderPage: React.FC<PlaceholderPageProps> = ({ title, subtitle }) => {
  return (
    <div className="max-w-7xl mx-auto">
      {/* Header */}
      <div className="pb-6 mb-8 border-b border-app-border">
        <div className="text-xs font-semibold uppercase tracking-wider text-brand-blue mb-1">
          Workforce Intelligence
        </div>
        <h1 className="text-2xl font-bold text-text-primary tracking-tight">
          {title}
        </h1>
        <p className="text-xs text-text-secondary mt-1">
          {subtitle}
        </p>
      </div>

      {/* Clean, calm coming soon placeholder card */}
      <div className="bg-white border border-app-border rounded-xl p-16 text-center shadow-subtle max-w-xl mx-auto my-12">
        <div className="w-12 h-12 rounded-2xl bg-blue-50 text-brand-blue flex items-center justify-center mx-auto mb-4 border border-blue-100">
          <Sparkles className="w-6 h-6" />
        </div>

        <h3 className="text-base font-bold text-text-primary mb-1">
          Coming in the next build
        </h3>

        <p className="text-xs text-text-secondary leading-relaxed max-w-sm mx-auto">
          {subtitle} Analytical models for this view will be activated in upcoming stages.
        </p>
      </div>
    </div>
  );
};
