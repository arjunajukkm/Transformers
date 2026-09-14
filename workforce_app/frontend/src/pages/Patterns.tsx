import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Sparkles, Calendar, AlertCircle } from 'lucide-react';
import { PatternSummaryCards } from '../components/patterns/PatternSummaryCards';
import { PatternCategoryTabs } from '../components/patterns/PatternCategoryTabs';
import { PatternFilterBar } from '../components/patterns/PatternFilterBar';
import { PatternList } from '../components/patterns/PatternList';
import { PatternEvidenceDrawer } from '../components/patterns/PatternEvidenceDrawer';
import { PatternEmptyState } from '../components/patterns/PatternEmptyState';
import { LoadingState } from '../components/common/LoadingState';
import { EmptyState } from '../components/common/EmptyState';
import { fetchPatterns } from '../services/api';
import {
  DashboardResponse,
  PatternResponse,
  PatternResult,
  PatternFilters,
} from '../types/workforce';

interface PatternsProps {
  data: DashboardResponse | null;
  onNavigateToData: () => void;
}

export const Patterns: React.FC<PatternsProps> = ({ data, onNavigateToData }) => {
  const [patternData, setPatternData] = useState<PatternResponse | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<string>('');
  const [filters, setFilters] = useState<PatternFilters>({});
  const [selectedPattern, setSelectedPattern] = useState<PatternResult | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Load patterns with active filters
  const loadPatterns = useCallback(async (activeFilters: PatternFilters) => {
    if (!data?.loaded) {
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    setError(null);
    try {
      const res = await fetchPatterns(activeFilters);
      setPatternData(res);
    } catch (err: any) {
      console.error('Failed to load patterns:', err);
      setError(err.message || 'Failed to calculate pattern intelligence.');
    } finally {
      setIsLoading(false);
    }
  }, [data?.loaded]);

  // Initial load on data ready or when filters/category changes
  useEffect(() => {
    if (data?.loaded) {
      const combinedFilters: PatternFilters = {
        ...filters,
        category: selectedCategory || undefined,
      };
      loadPatterns(combinedFilters);
    }
  }, [data?.loaded, selectedCategory, filters, loadPatterns]);

  // Handle Category tab switch
  const handleSelectCategory = (cat: string) => {
    setSelectedCategory(cat);
  };

  // Handle Filter bar change
  const handleFilterChange = (newFilters: PatternFilters) => {
    setFilters(newFilters);
  };

  // Handle Reset filters
  const handleResetFilters = () => {
    setSelectedCategory('');
    setFilters({});
  };

  // Check if any filter is active
  const hasActiveFilters = useMemo(() => {
    return Boolean(
      selectedCategory ||
      Object.values(filters).some((v) => v !== undefined && v !== '' && v !== null)
    );
  }, [selectedCategory, filters]);

  // Client-side search filtering if applied
  const filteredPatterns = useMemo(() => {
    if (!patternData?.patterns) return [];
    let list = [...patternData.patterns];

    if (filters.search) {
      const q = filters.search.toLowerCase().trim();
      list = list.filter(
        (p) =>
          p.pattern_title.toLowerCase().includes(q) ||
          p.entity_name.toLowerCase().includes(q) ||
          (p.entity_id && p.entity_id.toLowerCase().includes(q)) ||
          p.why_detected.toLowerCase().includes(q)
      );
    }

    return list;
  }, [patternData?.patterns, filters.search]);

  // If no dataset is loaded at all
  if (!data?.loaded) {
    return (
      <EmptyState
        onUploadClick={onNavigateToData}
      />
    );
  }

  const dateRangeDisplay = data.dataset?.display_period || 'Historical Period';


  return (
    <div className="space-y-6 min-w-0">
      {/* Header Section */}
      <div className="flex flex-wrap items-start justify-between gap-4 pb-2 border-b border-app-border">
        <div className="space-y-1 min-w-0">
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold text-app-text-primary tracking-tight">
              Patterns
            </h1>
            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-50 text-brand-blue border border-blue-200">
              <Sparkles className="w-3 h-3" />
              <span>Pattern Intelligence</span>
            </span>
          </div>
          <p className="text-xs text-app-text-secondary">
            Discover recurring workforce and process behaviours across attendance, leave, WFH, and approvals.
          </p>
        </div>

        {/* Dataset Period Badge */}
        <div className="flex items-center gap-2 px-3 py-1.5 bg-white border border-app-border rounded-lg text-xs font-medium text-app-text-primary shadow-subtle shrink-0">
          <Calendar className="w-3.5 h-3.5 text-brand-blue shrink-0" />
          <span>{dateRangeDisplay}</span>
        </div>
      </div>

      {/* Summary Cards */}
      {patternData?.summary && (
        <PatternSummaryCards summary={patternData.summary} />
      )}

      {/* Category Tabs */}
      {patternData?.summary && (
        <PatternCategoryTabs
          selectedCategory={selectedCategory}
          onSelectCategory={handleSelectCategory}
          categoryCounts={patternData.summary.category_counts}
          totalPatterns={patternData.summary.total_patterns}
        />
      )}

      {/* Filter Bar */}
      {data.filters && (
        <PatternFilterBar
          options={data.filters}
          filters={filters}
          onFilterChange={handleFilterChange}
          onReset={handleResetFilters}
          isLoading={isLoading}
        />
      )}

      {/* Error Notice */}
      {error && !isLoading && (
        <div className="p-4 rounded-xl bg-rose-50 border border-rose-200 text-brand-critical text-xs flex items-start gap-2.5">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <div>
            <div className="font-semibold mb-0.5">Unable to load patterns</div>
            <div>{error}</div>
          </div>
        </div>
      )}

      {/* Loading State */}
      {isLoading && (
        <LoadingState
          message="Evaluating workforce behavioural patterns..."
          subMessage="Evaluating recurrence, support thresholds, persistence, and evidence across governed analytical records."
        />
      )}

      {/* Pattern List or Empty State */}
      {!isLoading && patternData && (
        <>
          {filteredPatterns.length === 0 ? (
            <PatternEmptyState
              hasFilters={hasActiveFilters}
              onResetFilters={handleResetFilters}
            />
          ) : (
            <div className="space-y-3">
              <div className="flex items-center justify-between text-xs text-app-text-muted px-1">
                <span>
                  Showing <strong className="text-slate-700">{filteredPatterns.length}</strong> patterns
                </span>
                <span>Sorted by Active Status &amp; Pattern Strength</span>
              </div>

              <PatternList
                patterns={filteredPatterns}
                onViewEvidence={(p) => setSelectedPattern(p)}
              />
            </div>
          )}
        </>
      )}

      {/* Evidence Detail Drawer */}
      <PatternEvidenceDrawer
        pattern={selectedPattern}
        onClose={() => setSelectedPattern(null)}
      />
    </div>
  );
};
