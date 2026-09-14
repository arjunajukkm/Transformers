import React, { useState, useEffect, useCallback } from 'react';
import { Calendar, AlertCircle } from 'lucide-react';
import { MetricSelector } from '../components/trends/MetricSelector';
import { HeroTrendCard } from '../components/trends/HeroTrendCard';
import { TrendLineChart } from '../components/trends/TrendLineChart';
import { MonthlyDetailTable } from '../components/trends/MonthlyDetailTable';
import { TrendObservations } from '../components/trends/TrendObservations';
import { FilterBar } from '../components/dashboard/FilterBar';
import { LoadingState } from '../components/common/LoadingState';
import { EmptyState } from '../components/common/EmptyState';
import { fetchTrends, fetchTrendMetrics } from '../services/api';
import {
  TrendResponse,
  GroupedTrendMetrics,
  ActiveFilters,
  DashboardResponse,
} from '../types/workforce';

interface TrendsProps {
  data: DashboardResponse | null;
  onNavigateToData: () => void;
}

export const Trends: React.FC<TrendsProps> = ({ data, onNavigateToData }) => {
  const [selectedMetric, setSelectedMetric] = useState<string>('attendance_exception_rate');
  const [metricsCatalogue, setMetricsCatalogue] = useState<GroupedTrendMetrics>({});
  const [trendData, setTrendData] = useState<TrendResponse | null>(null);
  const [activeFilters, setActiveFilters] = useState<ActiveFilters>({});
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // 1. Fetch metric catalogue once on mount
  useEffect(() => {
    let mounted = true;
    fetchTrendMetrics()
      .then((catalogue) => {
        if (mounted) setMetricsCatalogue(catalogue);
      })
      .catch((err) => {
        console.error('Failed to load trend metrics catalogue:', err);
      });
    return () => {
      mounted = false;
    };
  }, []);

  // 2. Load trend time-series data
  const loadTrendData = useCallback(
    async (metricId: string, filters?: ActiveFilters) => {
      if (!data?.loaded) {
        setIsLoading(false);
        return;
      }

      setIsLoading(true);
      setError(null);
      try {
        const res = await fetchTrends(metricId, filters);
        setTrendData(res);
      } catch (err: any) {
        setError(err.message || 'Failed to load trend intelligence.');
      } finally {
        setIsLoading(false);
      }
    },
    [data?.loaded]
  );

  useEffect(() => {
    loadTrendData(selectedMetric, activeFilters);
  }, [selectedMetric, activeFilters, loadTrendData]);

  // Handle metric change
  const handleSelectMetric = (metricId: string) => {
    setSelectedMetric(metricId);
  };

  // Handle filter change
  const handleFilterChange = (key: keyof ActiveFilters, value: string) => {
    setActiveFilters((prev) => ({
      ...prev,
      [key]: value || undefined,
    }));
  };

  // Handle reset filters
  const handleResetFilters = () => {
    setActiveFilters({});
  };

  // If no dataset loaded in session
  if (!data?.loaded) {
    return (
      <div className="max-w-7xl mx-auto min-w-0">
        <EmptyState onUploadClick={onNavigateToData} />
      </div>
    );
  }

  // Current dataset date range from trendData or data
  const dateRangeDisplay =
    trendData?.date_range_display || data.dataset?.display_period || 'Dataset Active';

  return (
    <div className="max-w-7xl mx-auto min-w-0 space-y-6">
      {/* Trends Header */}
      <div className="pb-5 border-b border-app-border min-w-0 flex flex-col sm:flex-row sm:items-end justify-between gap-3">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-wider text-brand-blue mb-1">
            Workforce Intelligence
          </div>
          <h1 className="text-2xl lg:text-3xl font-bold text-text-primary tracking-tight">
            Trends
          </h1>
          <p className="text-xs text-text-secondary mt-1">
            Track workforce process behaviour over time.
          </p>
        </div>

        {/* Dataset date range display (No PRE_POLICY / POST_POLICY badges) */}
        <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-xl bg-white border border-app-border text-xs font-semibold text-text-primary shadow-subtle shrink-0">
          <Calendar className="w-3.5 h-3.5 text-brand-blue shrink-0" />
          <span>{dateRangeDisplay}</span>
        </div>
      </div>

      {/* Metric Selector Bar */}
      {Object.keys(metricsCatalogue).length > 0 && (
        <div className="bg-white border border-app-border rounded-xl p-3.5 shadow-subtle flex flex-wrap items-center justify-between gap-3 min-w-0">
          <MetricSelector
            selectedMetricId={selectedMetric}
            metricsCatalogue={metricsCatalogue}
            onSelectMetric={handleSelectMetric}
            isLoading={isLoading}
          />
        </div>
      )}

      {/* Global Filter Bar (reused from overview) */}
      {data.filters && (
        <FilterBar
          options={data.filters}
          activeFilters={activeFilters}
          onFilterChange={handleFilterChange}
          onReset={handleResetFilters}
          isLoading={isLoading}
        />
      )}

      {/* Loading state */}
      {isLoading && (
        <LoadingState
          message="Calculating time-series trends..."
          subMessage="Evaluating monthly facts, governance denominators, and deterministic trajectories."
        />
      )}

      {/* Error state */}
      {error && !isLoading && (
        <div className="p-4 rounded-xl bg-rose-50 border border-rose-200 text-brand-critical text-xs flex items-start gap-2.5">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <div>
            <div className="font-semibold mb-0.5">Unable to load trends</div>
            <div>{error}</div>
          </div>
        </div>
      )}

      {/* Loaded Trend Dashboard */}
      {!isLoading && trendData && trendData.loaded && (
        <div className="space-y-6 min-w-0">
          {/* 1. Hero Trend Summary Card */}
          <HeroTrendCard trendData={trendData} />

          {/* 2. Primary Line Chart */}
          <TrendLineChart
            timeSeries={trendData.time_series}
            metric={trendData.metric}
            policyEffectiveDate={trendData.policy_effective_date}
          />

          {/* 3. Monthly Detail Table */}
          <MonthlyDetailTable
            timeSeries={trendData.time_series}
            metric={trendData.metric}
          />

          {/* 4. Trend Observations */}
          <TrendObservations observations={trendData.observations} />
        </div>
      )}
    </div>
  );
};
