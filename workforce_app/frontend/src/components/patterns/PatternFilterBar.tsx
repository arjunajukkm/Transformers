import React from 'react';
import { Filter, Search, RotateCcw } from 'lucide-react';
import { FilterOptions, PatternFilters } from '../../types/workforce';

interface PatternFilterBarProps {
  options: FilterOptions;
  filters: PatternFilters;
  onFilterChange: (filters: PatternFilters) => void;
  onReset: () => void;
  isLoading?: boolean;
}

export const PatternFilterBar: React.FC<PatternFilterBarProps> = ({
  options,
  filters,
  onFilterChange,
  onReset,
  isLoading = false,
}) => {
  const handleChange = (key: keyof PatternFilters, value: string) => {
    onFilterChange({
      ...filters,
      [key]: value || undefined,
    });
  };

  const hasActiveFilters = Object.values(filters).some(
    (v) => v !== undefined && v !== '' && v !== null
  );

  return (
    <div className="bg-white border border-app-border rounded-xl p-3.5 shadow-subtle flex flex-col gap-3 min-w-0">
      <div className="flex flex-wrap items-center justify-between gap-2.5">
        <div className="flex items-center gap-2 text-xs font-semibold text-app-text-primary">
          <Filter className="w-3.5 h-3.5 text-brand-blue shrink-0" />
          <span>Pattern Filters</span>
        </div>

        {hasActiveFilters && (
          <button
            onClick={onReset}
            disabled={isLoading}
            className="flex items-center gap-1.5 text-xs text-brand-blue hover:text-blue-700 font-medium px-2.5 py-1 rounded-md hover:bg-blue-50 transition-colors"
          >
            <RotateCcw className="w-3 h-3" />
            <span>Reset Filters</span>
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 lg:grid-cols-4 xl:grid-cols-8 gap-2.5">
        {/* Search */}
        <div className="relative min-w-0">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            placeholder="Search pattern/entity..."
            value={filters.search || ''}
            onChange={(e) => handleChange('search', e.target.value)}
            disabled={isLoading}
            className="w-full pl-8 pr-2.5 py-1.5 text-xs bg-slate-50 border border-app-border rounded-lg text-app-text-primary placeholder:text-slate-400 focus:outline-none focus:ring-1 focus:ring-brand-blue focus:bg-white transition-all"
          />
        </div>

        {/* Entity Level */}
        <div className="min-w-0">
          <select
            value={filters.entity_type || ''}
            onChange={(e) => handleChange('entity_type', e.target.value)}
            disabled={isLoading}
            className="w-full px-2.5 py-1.5 text-xs bg-slate-50 border border-app-border rounded-lg text-app-text-primary focus:outline-none focus:ring-1 focus:ring-brand-blue focus:bg-white transition-all cursor-pointer"
          >
            <option value="">All Entity Levels</option>
            <option value="EMPLOYEE">Employee</option>
            <option value="REPORTING_MANAGER">Reporting Manager</option>
            <option value="DEPARTMENT">Department</option>
            <option value="BUSINESS_UNIT">Business Unit</option>
          </select>
        </div>

        {/* Business Unit */}
        <div className="min-w-0">
          <select
            value={filters.business_unit || ''}
            onChange={(e) => handleChange('business_unit', e.target.value)}
            disabled={isLoading || (options.business_unit?.length || 0) === 0}
            className="w-full px-2.5 py-1.5 text-xs bg-slate-50 border border-app-border rounded-lg text-app-text-primary focus:outline-none focus:ring-1 focus:ring-brand-blue focus:bg-white transition-all cursor-pointer truncate"
          >
            <option value="">All Business Units</option>
            {options.business_unit?.map((bu) => (
              <option key={bu} value={bu}>
                {bu}
              </option>
            ))}
          </select>
        </div>

        {/* Department */}
        <div className="min-w-0">
          <select
            value={filters.department || ''}
            onChange={(e) => handleChange('department', e.target.value)}
            disabled={isLoading || (options.department?.length || 0) === 0}
            className="w-full px-2.5 py-1.5 text-xs bg-slate-50 border border-app-border rounded-lg text-app-text-primary focus:outline-none focus:ring-1 focus:ring-brand-blue focus:bg-white transition-all cursor-pointer truncate"
          >
            <option value="">All Departments</option>
            {options.department?.map((dept) => (
              <option key={dept} value={dept}>
                {dept}
              </option>
            ))}
          </select>
        </div>

        {/* Location */}
        <div className="min-w-0">
          <select
            value={filters.location || ''}
            onChange={(e) => handleChange('location', e.target.value)}
            disabled={isLoading || (options.location?.length || 0) === 0}
            className="w-full px-2.5 py-1.5 text-xs bg-slate-50 border border-app-border rounded-lg text-app-text-primary focus:outline-none focus:ring-1 focus:ring-brand-blue focus:bg-white transition-all cursor-pointer truncate"
          >
            <option value="">All Locations</option>
            {options.location?.map((loc) => (
              <option key={loc} value={loc}>
                {loc}
              </option>
            ))}
          </select>
        </div>

        {/* Reporting Manager */}
        <div className="min-w-0">
          <select
            value={filters.reporting_manager || ''}
            onChange={(e) => handleChange('reporting_manager', e.target.value)}
            disabled={isLoading || (options.reporting_manager?.length || 0) === 0}
            className="w-full px-2.5 py-1.5 text-xs bg-slate-50 border border-app-border rounded-lg text-app-text-primary focus:outline-none focus:ring-1 focus:ring-brand-blue focus:bg-white transition-all cursor-pointer truncate"
          >
            <option value="">All Managers</option>
            {options.reporting_manager?.map((mgr) => (
              <option key={mgr} value={mgr}>
                {mgr}
              </option>
            ))}
          </select>
        </div>

        {/* Strength */}
        <div className="min-w-0">
          <select
            value={filters.strength || ''}
            onChange={(e) => handleChange('strength', e.target.value)}
            disabled={isLoading}
            className="w-full px-2.5 py-1.5 text-xs bg-slate-50 border border-app-border rounded-lg text-app-text-primary focus:outline-none focus:ring-1 focus:ring-brand-blue focus:bg-white transition-all cursor-pointer"
          >
            <option value="">All Strengths</option>
            <option value="HIGH">High Recurrence</option>
            <option value="MODERATE">Moderate</option>
            <option value="LOW">Low</option>
          </select>
        </div>

        {/* Status */}
        <div className="min-w-0">
          <select
            value={filters.status || ''}
            onChange={(e) => handleChange('status', e.target.value)}
            disabled={isLoading}
            className="w-full px-2.5 py-1.5 text-xs bg-slate-50 border border-app-border rounded-lg text-app-text-primary focus:outline-none focus:ring-1 focus:ring-brand-blue focus:bg-white transition-all cursor-pointer"
          >
            <option value="">All Statuses</option>
            <option value="ACTIVE">Active (≤30d)</option>
            <option value="RECENT">Recent (31-90d)</option>
            <option value="HISTORICAL">Historical (&gt;90d)</option>
          </select>
        </div>
      </div>
    </div>
  );
};

