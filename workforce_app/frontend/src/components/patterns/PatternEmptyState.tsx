import React from 'react';
import { SearchX, Sparkles } from 'lucide-react';

interface PatternEmptyStateProps {
  hasFilters?: boolean;
  onResetFilters?: () => void;
}

export const PatternEmptyState: React.FC<PatternEmptyStateProps> = ({
  hasFilters,
  onResetFilters,
}) => {
  return (
    <div className="bg-white border border-app-border rounded-xl p-12 text-center shadow-subtle flex flex-col items-center justify-center max-w-lg mx-auto my-8">
      <div className="p-3.5 rounded-full bg-slate-100 text-slate-400 mb-4">
        {hasFilters ? (
          <SearchX className="w-8 h-8 text-slate-500" />
        ) : (
          <Sparkles className="w-8 h-8 text-brand-blue" />
        )}
      </div>

      <h3 className="text-base font-semibold text-app-text-primary mb-1.5">
        {hasFilters
          ? 'No patterns match current filters'
          : 'No recurring patterns detected yet.'}
      </h3>

      <p className="text-xs text-app-text-muted leading-relaxed mb-4 max-w-sm">
        {hasFilters
          ? 'Try adjusting your category, entity level, or search filters to view broader recurring behavioral patterns.'
          : 'More historical data or repeated events are required before recurring behaviour can be identified (minimum 3 supporting events).'}
      </p>

      {hasFilters && onResetFilters && (
        <button
          onClick={onResetFilters}
          className="px-4 py-2 bg-brand-blue hover:bg-blue-700 text-white rounded-lg text-xs font-semibold shadow-subtle transition-colors"
        >
          Reset All Filters
        </button>
      )}
    </div>
  );
};
