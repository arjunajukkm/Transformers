import React from 'react';
import { ChevronDown } from 'lucide-react';
import { GroupedTrendMetrics, TrendMetricMeta } from '../../types/workforce';

interface MetricSelectorProps {
  selectedMetricId: string;
  metricsCatalogue: GroupedTrendMetrics;
  onSelectMetric: (metricId: string) => void;
  isLoading?: boolean;
}

export const MetricSelector: React.FC<MetricSelectorProps> = ({
  selectedMetricId,
  metricsCatalogue,
  onSelectMetric,
  isLoading,
}) => {
  const categories = Object.keys(metricsCatalogue);

  // Find currently selected metric
  let currentMetric: TrendMetricMeta | undefined;
  for (const cat of categories) {
    const found = metricsCatalogue[cat].find((m) => m.id === selectedMetricId);
    if (found) {
      currentMetric = found;
      break;
    }
  }

  return (
    <div className="flex flex-col sm:flex-row sm:items-center gap-2 min-w-0">
      <label htmlFor="trend-metric-select" className="text-xs font-semibold text-text-secondary uppercase tracking-wider shrink-0">
        Metric:
      </label>

      <div className="relative inline-block min-w-[240px] max-w-md w-full">
        <select
          id="trend-metric-select"
          value={selectedMetricId}
          onChange={(e) => onSelectMetric(e.target.value)}
          disabled={isLoading}
          className="w-full appearance-none bg-white border border-app-border rounded-xl px-3.5 py-2 pr-9 text-xs font-bold text-text-primary shadow-subtle focus:outline-none focus:ring-2 focus:ring-brand-blue/20 focus:border-brand-blue cursor-pointer transition-all truncate"
        >
          {categories.map((cat) => (
            <optgroup key={cat} label={cat} className="font-bold text-text-primary">
              {metricsCatalogue[cat].map((m) => (
                <option key={m.id} value={m.id} className="font-normal text-text-primary py-1">
                  {m.label}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
        <ChevronDown className="w-4 h-4 text-text-muted absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none" />
      </div>

      {currentMetric && (
        <span className="text-[11px] text-text-muted hidden md:inline truncate max-w-xs" title={currentMetric.description}>
          {currentMetric.description}
        </span>
      )}
    </div>
  );
};
