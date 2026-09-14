import React from 'react';
import { Filter, RotateCcw } from 'lucide-react';
import { FilterOptions, ActiveFilters } from '../../types/workforce';

interface FilterBarProps {
  options: FilterOptions;
  activeFilters: ActiveFilters;
  onFilterChange: (key: keyof ActiveFilters, value: string) => void;
  onReset: () => void;
  isLoading?: boolean;
}

export const FilterBar: React.FC<FilterBarProps> = ({
  options,
  activeFilters,
  onFilterChange,
  onReset,
  isLoading,
}) => {
  const hasActiveFilters = Object.values(activeFilters).some(Boolean);

  const filterFields: { key: keyof ActiveFilters; label: string; values: string[] }[] = [
    { key: 'business_unit', label: 'Business Unit', values: options.business_unit || [] },
    { key: 'department', label: 'Department', values: options.department || [] },
    { key: 'location', label: 'Location', values: options.location || [] },
    { key: 'reporting_manager', label: 'Reporting Manager', values: options.reporting_manager || [] },
  ];

  return (
    <div className="bg-white border border-app-border rounded-xl p-3 mb-6 flex flex-wrap items-center gap-2.5 shadow-subtle min-w-0 w-full">
      <div className="flex items-center gap-1.5 text-xs font-semibold text-text-secondary uppercase tracking-wider pl-1 mr-1 shrink-0">
        <Filter className="w-3.5 h-3.5 text-text-muted" />
        <span>Filters</span>
      </div>

      <div className="flex flex-wrap items-center gap-2 flex-1 min-w-0">
        {filterFields.map((field) => {
          const selectedVal = activeFilters[field.key] || '';
          return (
            <div key={field.key} className="min-w-[130px] flex-1 max-w-[240px]">
              <select
                value={selectedVal}
                onChange={(e) => onFilterChange(field.key, e.target.value)}
                disabled={isLoading || field.values.length === 0}
                title={selectedVal ? `${field.label}: ${selectedVal}` : `All ${field.label}s`}
                className="w-full text-xs bg-app-bg border border-app-border rounded-lg px-2.5 py-1.5 text-text-primary focus:outline-none focus:ring-1 focus:ring-brand-blue disabled:opacity-50 transition-colors truncate"
              >
                <option value="">All {field.label}s</option>
                {field.values.map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>
            </div>
          );
        })}
      </div>

      {hasActiveFilters && (
        <button
          onClick={onReset}
          disabled={isLoading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-text-secondary hover:text-brand-critical hover:bg-red-50 border border-transparent hover:border-red-100 transition-colors shrink-0"
        >
          <RotateCcw className="w-3.5 h-3.5" />
          <span>Reset</span>
        </button>
      )}
    </div>
  );
};
