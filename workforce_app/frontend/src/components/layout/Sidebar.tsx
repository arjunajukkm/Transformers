import React from 'react';
import {
  LayoutDashboard,
  TrendingUp,
  Network,
  AlertTriangle,
  Users,
  Database,
} from 'lucide-react';

export type NavTab = 'overview' | 'trends' | 'patterns' | 'anomalies' | 'people' | 'data';

interface SidebarProps {
  activeTab: NavTab;
  onTabChange: (tab: NavTab) => void;
  datasetLoaded: boolean;
}

interface NavItemConfig {
  id: NavTab;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  badge?: string;
}

const NAV_ITEMS: NavItemConfig[] = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'trends', label: 'Trends', icon: TrendingUp },
  { id: 'patterns', label: 'Patterns', icon: Network },
  { id: 'anomalies', label: 'Anomalies', icon: AlertTriangle },
  { id: 'people', label: 'People', icon: Users },
  { id: 'data', label: 'Data', icon: Database },
];

export const Sidebar: React.FC<SidebarProps> = ({ activeTab, onTabChange, datasetLoaded }) => {
  return (
    <aside className="w-64 bg-white border-r border-app-border flex flex-col h-screen select-none shrink-0">
      {/* Brand Header */}
      <div className="p-6 pb-5 border-b border-app-border/60">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-brand-blue flex items-center justify-center text-white font-semibold text-sm shadow-sm">
            T
          </div>
          <div>
            <div className="text-xs font-semibold uppercase tracking-wider text-text-muted">
              Transformers
            </div>
            <div className="text-sm font-bold text-text-primary tracking-tight">
              Workforce Intelligence
            </div>
          </div>
        </div>
      </div>

      {/* Navigation List */}
      <nav className="flex-1 px-3 py-5 space-y-1.5 overflow-y-auto">
        <div className="px-3 pb-2 text-[11px] font-semibold text-text-muted uppercase tracking-wider">
          Workspace
        </div>
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const isActive = activeTab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onTabChange(item.id)}
              className={`w-full flex items-center gap-3 px-3.5 py-2.5 rounded-lg text-sm font-medium transition-all duration-150 text-left ${
                isActive
                  ? 'bg-brand-blue/10 text-brand-blue font-semibold'
                  : 'text-text-secondary hover:bg-app-bg hover:text-text-primary'
              }`}
            >
              <Icon
                className={`w-4 h-4 transition-colors ${
                  isActive ? 'text-brand-blue' : 'text-text-muted'
                }`}
              />
              <span className="flex-1">{item.label}</span>
              {item.id === 'data' && datasetLoaded && (
                <span className="w-2 h-2 rounded-full bg-brand-positive"></span>
              )}
            </button>
          );
        })}
      </nav>

      {/* Subtle Footer */}
      <div className="p-4 border-t border-app-border/60 text-xs text-text-muted">
        <div className="flex items-center justify-between">
          <span>Engine v2.1</span>
          <span className="inline-flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-brand-positive"></span>
            Local Active
          </span>
        </div>
      </div>
    </aside>
  );
};
