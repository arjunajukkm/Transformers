import React from 'react';
import {
  PatternStrengthType,
  PatternSeverityType,
  PatternStatusType,
  PatternPersistenceType,
} from '../../types/workforce';

export const PatternStrengthBadge: React.FC<{ strength: PatternStrengthType }> = ({ strength }) => {
  switch (strength) {
    case 'HIGH':
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold bg-purple-50 text-purple-700 border border-purple-200">
          High Recurrence
        </span>
      );
    case 'MODERATE':
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-blue-50 text-blue-700 border border-blue-200">
          Moderate
        </span>
      );
    case 'LOW':
    default:
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-slate-100 text-slate-600 border border-slate-200">
          Low
        </span>
      );
  }
};

export const PatternSeverityBadge: React.FC<{ severity: PatternSeverityType }> = ({ severity }) => {
  switch (severity) {
    case 'PRIORITY':
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold bg-rose-50 text-rose-700 border border-rose-200">
          Priority
        </span>
      );
    case 'ATTENTION':
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-amber-50 text-amber-700 border border-amber-200">
          Attention
        </span>
      );
    case 'INFO':
    default:
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-sky-50 text-sky-700 border border-sky-200">
          Info
        </span>
      );
  }
};

export const PatternStatusBadge: React.FC<{ status: PatternStatusType }> = ({ status }) => {
  switch (status) {
    case 'ACTIVE':
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
          Active
        </span>
      );
    case 'RECENT':
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium bg-amber-50 text-amber-700 border border-amber-200">
          <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
          Recent
        </span>
      );
    case 'HISTORICAL':
    default:
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium bg-slate-100 text-slate-500 border border-slate-200">
          <span className="w-1.5 h-1.5 rounded-full bg-slate-400" />
          Historical
        </span>
      );
  }
};

export const PatternPersistenceBadge: React.FC<{ persistence: PatternPersistenceType }> = ({ persistence }) => {
  switch (persistence) {
    case 'PERSISTENT':
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-indigo-50 text-indigo-700 border border-indigo-200">
          Persistent (3+ mo)
        </span>
      );
    case 'MULTI_MONTH':
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-sky-50 text-sky-700 border border-sky-200">
          Multi-Month (2 mo)
        </span>
      );
    case 'SINGLE_PERIOD':
    default:
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-slate-50 text-slate-600 border border-slate-200">
          Single Period
        </span>
      );
  }
};
