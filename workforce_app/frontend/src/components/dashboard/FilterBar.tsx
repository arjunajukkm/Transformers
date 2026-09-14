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
    <div className="bg-white border border-app-border rounded-xl p-3.5 mb-6 flex flex-wrap items-center gap-3 shadow-subtle">
      <div className="flex items-center gap-1.5 text-xs font-semibold text-text-secondary uppercase tracking-wider pl-1 mr-1">
        <Filter className="w-3.5 h-3.5 text-text-muted" />
        <span>Filters</span>
      </div>

      <div className="flex flex-wrap items-center gap-2.5 flex-1">
        {filterFields.map((field) => (
          <div key={field.key} className="min-w-[170px] flex-1 max-w-[240px]">
            <select
              value={activeFilters[field.key] || ''}
              onChange={(e) => onFilterChange(field.key, e.target.value)}
              disabled={isLoading || field.values.length === 0}
              className="w-full text-xs bg-app-bg border border-app-border rounded-lg px-2.5 py-1.5 text-text-primary focus:outline-none focus:ring-1 focus:ring-brand-blue disabled:opacity-50 transition-colors"
            >
              <option value="">All {field.label}s</option>
              {field.values.map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </div>
        ))}
      </div>

      {hasActiveFilters && (
        <button
          onClick={onReset}
          disabled={isLoading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-text-secondary hover:text-brand-critical hover:bg-red-50 border border-transparent hover:border-red-100 transition-colors"
        >
          <RotateCcw className="w-3.5 h-3.5" />
          Reset Filters
        </button>
      )}
    </div>
  );
};
