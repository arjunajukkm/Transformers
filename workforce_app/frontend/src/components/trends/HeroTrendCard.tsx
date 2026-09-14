import React from 'react';
import {
  TrendingUp,
  TrendingDown,
  Minus,
  HelpCircle,
  AlertTriangle,
  Calendar,
} from 'lucide-react';
import { TrendResponse } from '../../types/workforce';

interface HeroTrendCardProps {
  trendData: TrendResponse;
}

export const HeroTrendCard: React.FC<HeroTrendCardProps> = ({ trendData }) => {
  const {
    metric,
    current_value_formatted,
    current_period_display,
    previous_value_formatted,
    mom_change,
    mom_change_pp,
    first_available_value_formatted,
    change_since_first,
    change_since_first_pp,
    trend_direction,
    time_series,
    volume_status,
    regression_detected,
  } = trendData;

  const getDirectionBadge = () => {
    switch (trend_direction) {
      case 'IMPROVING':
        return (
          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">
            <TrendingUp className="w-3.5 h-3.5 text-emerald-600" />
            Improving
          </span>
        );
      case 'DETERIORATING':
        return (
          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold bg-rose-50 text-brand-critical border border-rose-200">
            <TrendingDown className="w-3.5 h-3.5 text-brand-critical" />
            Deteriorating
          </span>
        );
      case 'STABLE':
        return (
          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold bg-slate-50 text-slate-700 border border-slate-200">
            <Minus className="w-3.5 h-3.5 text-slate-500" />
            Stable
          </span>
        );
      case 'INCREASING':
        return (
          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold bg-blue-50 text-blue-700 border border-blue-200">
            <TrendingUp className="w-3.5 h-3.5 text-blue-600" />
            Increasing
          </span>
        );
      case 'DECREASING':
        return (
          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold bg-indigo-50 text-indigo-700 border border-indigo-200">
            <TrendingDown className="w-3.5 h-3.5 text-indigo-600" />
            Decreasing
          </span>
        );
      case 'INSUFFICIENT_DATA':
      default:
        return (
          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold bg-slate-100 text-slate-600 border border-slate-200">
            <HelpCircle className="w-3.5 h-3.5 text-slate-400" />
            Insufficient data
          </span>
        );
    }
  };

  const prevMonthName = time_series.length >= 2 ? time_series[time_series.length - 2].period_display.split(' ')[0] : null;
  const firstMonthName = time_series.length >= 2 ? time_series[0].period_display.split(' ')[0] : null;

  return (
    <div className="bg-white border border-app-border rounded-2xl p-6 md:p-7 shadow-subtle min-w-0">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-5 border-b border-app-border/80">
        <div className="min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[11px] font-bold uppercase tracking-wider text-brand-blue">
              {metric?.category || 'Workforce Metric'}
            </span>
            {volume_status && (
              <span
                className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${
                  volume_status === 'LOW'
                    ? 'bg-amber-50 text-amber-800 border-amber-200'
                    : 'bg-slate-50 text-slate-600 border-slate-200'
                }`}
              >
                Volume: {volume_status.charAt(0) + volume_status.slice(1).toLowerCase()}
              </span>
            )}
            {regression_detected && (
              <span className="inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full bg-rose-50 text-brand-critical border border-rose-200">
                <AlertTriangle className="w-3 h-3" />
                Regression
              </span>
            )}
          </div>
          <h2 className="text-xl md:text-2xl font-bold text-text-primary tracking-tight truncate">
            {metric?.label}
          </h2>
        </div>

        <div className="flex items-center gap-3 shrink-0">
          {getDirectionBadge()}
        </div>
      </div>

      {/* Main Metric Value & Comparators */}
      <div className="pt-5 grid grid-cols-1 sm:grid-cols-3 gap-6 items-end min-w-0">
        {/* Primary Value with explicitly labeled Month */}
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-xs text-text-muted font-medium mb-1 truncate">
            <Calendar className="w-3.5 h-3.5 shrink-0 text-text-secondary" />
            <span className="font-semibold text-text-secondary truncate">
              {current_period_display || 'Latest Observation'}
            </span>
          </div>
          <div className="text-3xl sm:text-4xl font-extrabold text-text-primary tracking-tight">
            {current_value_formatted || '—'}
          </div>
        </div>

        {/* Previous Month comparison */}
        <div className="min-w-0">
          <div className="text-xs text-text-muted font-medium mb-1 truncate">
            vs Previous Month {prevMonthName ? `(${prevMonthName})` : ''}
          </div>
          {mom_change !== null && mom_change !== undefined ? (
            <div className="flex items-center gap-1.5 text-sm font-bold">
              {mom_change > 0 ? (
                <span className="text-text-primary">
                  ↑ {metric?.format === 'percentage' ? `${mom_change_pp?.toFixed(1)} pp` : mom_change.toFixed(1)}
                </span>
              ) : mom_change < 0 ? (
                <span className="text-text-primary">
                  ↓ {metric?.format === 'percentage' ? `${Math.abs(mom_change_pp || 0).toFixed(1)} pp` : Math.abs(mom_change).toFixed(1)}
                </span>
              ) : (
                <span className="text-text-muted">No change (0.0)</span>
              )}
              {previous_value_formatted && (
                <span className="text-xs font-normal text-text-muted truncate">
                  (was {previous_value_formatted})
                </span>
              )}
            </div>
          ) : (
            <div className="text-sm text-text-muted font-normal">
              No prior month
            </div>
          )}
        </div>

        {/* Change since earliest available month */}
        <div className="min-w-0">
          <div className="text-xs text-text-muted font-medium mb-1 truncate">
            Since First Month {firstMonthName ? `(${firstMonthName})` : ''}
          </div>
          {change_since_first !== null && change_since_first !== undefined ? (
            <div className="flex items-center gap-1.5 text-sm font-bold">
              {change_since_first > 0 ? (
                <span className="text-text-primary">
                  ↑ {metric?.format === 'percentage' ? `${change_since_first_pp?.toFixed(1)} pp` : change_since_first.toFixed(1)}
                </span>
              ) : change_since_first < 0 ? (
                <span className="text-text-primary">
                  ↓ {metric?.format === 'percentage' ? `${Math.abs(change_since_first_pp || 0).toFixed(1)} pp` : Math.abs(change_since_first).toFixed(1)}
                </span>
              ) : (
                <span className="text-text-muted">No net change (0.0)</span>
              )}
              {first_available_value_formatted && (
                <span className="text-xs font-normal text-text-muted truncate">
                  (start: {first_available_value_formatted})
                </span>
              )}
            </div>
          ) : (
            <div className="text-sm text-text-muted font-normal">
              Single month dataset
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
