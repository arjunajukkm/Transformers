import React from 'react';
import { ChevronRight, Calendar, User, Building, Clock, Layers } from 'lucide-react';
import { PatternResult } from '../../types/workforce';
import {
  PatternStrengthBadge,
  PatternSeverityBadge,
  PatternStatusBadge,
  PatternPersistenceBadge,
} from './PatternBadges';

interface PatternListItemProps {
  pattern: PatternResult;
  onViewEvidence: (pattern: PatternResult) => void;
}

export const PatternListItem: React.FC<PatternListItemProps> = ({
  pattern,
  onViewEvidence,
}) => {
  const getEntityIcon = (type: string) => {
    switch (type) {
      case 'EMPLOYEE':
        return <User className="w-3.5 h-3.5 text-slate-500 shrink-0" />;
      case 'REPORTING_MANAGER':
        return <User className="w-3.5 h-3.5 text-indigo-500 shrink-0" />;
      case 'DEPARTMENT':
      case 'BUSINESS_UNIT':
      default:
        return <Building className="w-3.5 h-3.5 text-slate-500 shrink-0" />;
    }
  };

  const getEntityLabel = (type: string) => {
    switch (type) {
      case 'EMPLOYEE':
        return 'Employee';
      case 'REPORTING_MANAGER':
        return 'Manager';
      case 'DEPARTMENT':
        return 'Department';
      case 'BUSINESS_UNIT':
        return 'Business Unit';
      case 'ORGANIZATION':
        return 'Organization';
      default:
        return type;
    }
  };

  return (
    <div className="bg-white border border-app-border rounded-xl p-4 shadow-subtle hover:shadow-md transition-all flex flex-col justify-between gap-3 min-w-0">
      {/* Top Header: Title, Category, Badges */}
      <div className="flex flex-wrap items-start justify-between gap-2.5">
        <div className="space-y-1 min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11px] font-semibold text-brand-blue uppercase tracking-wider bg-blue-50 px-2 py-0.5 rounded border border-blue-100">
              {pattern.pattern_category}
            </span>
            <h3 className="text-sm font-semibold text-app-text-primary tracking-tight truncate">
              {pattern.pattern_title}
            </h3>
          </div>

          {/* Entity Details */}
          <div className="flex flex-wrap items-center gap-2 text-xs text-app-text-secondary pt-0.5">
            <div className="flex items-center gap-1 font-medium text-slate-800">
              {getEntityIcon(pattern.entity_type)}
              <span>{pattern.entity_name}</span>
            </div>
            <span className="text-slate-300">•</span>
            <span className="text-app-text-muted text-[11px]">
              {getEntityLabel(pattern.entity_type)}
            </span>
            {pattern.entity_id && pattern.entity_id !== pattern.entity_name && (
              <>
                <span className="text-slate-300">•</span>
                <span className="font-mono text-[11px] text-slate-500 bg-slate-50 px-1.5 py-0.5 rounded">
                  {pattern.entity_id}
                </span>
              </>
            )}
          </div>
        </div>

        {/* Badges Cluster */}
        <div className="flex flex-wrap items-center gap-1.5 shrink-0">
          <PatternStrengthBadge strength={pattern.strength} />
          <PatternSeverityBadge severity={pattern.severity} />
          <PatternStatusBadge status={pattern.status} />
          <PatternPersistenceBadge persistence={pattern.persistence} />
        </div>
      </div>

      {/* Middle: Why detected / deterministic explanation */}
      <div className="bg-slate-50 border border-slate-100 rounded-lg p-3 text-xs text-app-text-secondary leading-relaxed">
        <div className="font-medium text-slate-700 mb-0.5">Why Detected:</div>
        <div>{pattern.why_detected}</div>
      </div>

      {/* Bottom Row: Metrics & View Evidence Action */}
      <div className="flex flex-wrap items-center justify-between gap-3 pt-1 border-t border-slate-100 text-xs">
        <div className="flex flex-wrap items-center gap-4 text-app-text-muted text-[11px]">
          <div className="flex items-center gap-1.5">
            <Layers className="w-3.5 h-3.5 text-slate-400" />
            <span className="font-semibold text-slate-700">{pattern.event_count}</span>
            <span>events</span>
            {pattern.opportunity_count && (
              <span>/ {pattern.opportunity_count} opps</span>
            )}
            {pattern.rate !== null && pattern.rate !== undefined && (
              <span className="font-medium text-brand-blue">
                ({(pattern.rate * 100).toFixed(1)}%)
              </span>
            )}
          </div>

          <div className="flex items-center gap-1.5">
            <Calendar className="w-3.5 h-3.5 text-slate-400" />
            <span>
              {pattern.distinct_months} {pattern.distinct_months === 1 ? 'month' : 'months'}
            </span>
            {pattern.months_active && pattern.months_active.length > 0 && (
              <span className="text-slate-400 hidden sm:inline">
                ({pattern.months_active.slice(0, 3).join(', ')}
                {pattern.months_active.length > 3 ? '...' : ''})
              </span>
            )}
          </div>

          {pattern.last_observed_date && (
            <div className="flex items-center gap-1.5">
              <Clock className="w-3.5 h-3.5 text-slate-400" />
              <span>Last: {pattern.last_observed_date}</span>
            </div>
          )}
        </div>

        <button
          onClick={() => onViewEvidence(pattern)}
          className="flex items-center gap-1 px-3 py-1.5 text-xs font-semibold text-brand-blue hover:text-blue-700 bg-blue-50/60 hover:bg-blue-100/70 border border-blue-200 rounded-lg transition-colors ml-auto"
        >
          <span>View Evidence</span>
          <ChevronRight className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );
};
