import React from 'react';
import { PageHeader } from '../components/layout/PageHeader';
import { FilterBar } from '../components/dashboard/FilterBar';
import { PrimaryKpiGrid } from '../components/dashboard/KpiCard';
import { MetricStrip } from '../components/dashboard/MetricStrip';
import { TrendChart } from '../components/dashboard/TrendChart';
import { ObservationsList } from '../components/dashboard/ObservationsList';
import { DataQualityCard } from '../components/dashboard/DataQualityCard';
import { EmptyState } from '../components/common/EmptyState';
import { LoadingState } from '../components/common/LoadingState';
import { DashboardResponse, ActiveFilters } from '../types/workforce';

interface OverviewProps {
  data: DashboardResponse | null;
  isLoading: boolean;
  onFilterChange: (key: keyof ActiveFilters, value: string) => void;
  onResetFilters: () => void;
  onNavigateToData: () => void;
  onUploadClick: () => void;
}

export const Overview: React.FC<OverviewProps> = ({
  data,
  isLoading,
  onFilterChange,
  onResetFilters,
  onNavigateToData,
  onUploadClick,
}) => {
  if (isLoading && !data) {
    return <LoadingState />;
  }

  if (!data || !data.loaded || !data.dataset || !data.metrics) {
    return <EmptyState onUploadClick={onUploadClick} />;
  }

  const { dataset, metrics, quality, trends, observations, filters, active_filters } = data;

  return (
    <div className="max-w-7xl mx-auto">
      {/* Top Header */}
      <PageHeader
        dataset={dataset}
        onUploadClick={onUploadClick}
        title="Workforce Process Health"
      />

      {/* Global Dimension Filter Bar */}
      {filters && (
        <FilterBar
          options={filters}
          activeFilters={active_filters || {}}
          onFilterChange={onFilterChange}
          onReset={onResetFilters}
          isLoading={isLoading}
        />
      )}

      {/* Primary 4 Governance KPI Cards */}
      <PrimaryKpiGrid
        metrics={metrics}
        policyPeriod={dataset.policy_period}
      />

      {/* Secondary Metrics Strip */}
      <MetricStrip
        metrics={metrics}
        quality={quality}
        dataset={dataset}
      />

      {/* Process Health Trend Chart */}
      <TrendChart
        data={trends || []}
        policyPeriod={dataset.policy_period}
      />

      {/* Two-Column Grid: Observations & Data Quality Summary */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <ObservationsList observations={observations || []} />
        <DataQualityCard quality={quality} onViewDetails={onNavigateToData} />
      </div>
    </div>
  );
};
