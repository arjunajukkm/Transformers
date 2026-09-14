import React, { useState, useEffect } from 'react';
import {
  LayoutDashboard,
  TrendingUp,
  Network,
  AlertTriangle,
  Users,
  Database,
  PanelLeftClose,
  PanelLeftOpen,
} from 'lucide-react';

export type NavTab = 'overview' | 'trends' | 'patterns' | 'anomalies' | 'people' | 'data';

interface SidebarProps {
  activeTab: NavTab;
  onTabChange: (tab: NavTab) => void;
  datasetLoaded: boolean;
  isCollapsed?: boolean;
  onToggleCollapse?: () => void;
}

interface NavItemConfig {
  id: NavTab;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}

const NAV_ITEMS: NavItemConfig[] = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'trends', label: 'Trends', icon: TrendingUp },
  { id: 'patterns', label: 'Patterns', icon: Network },
  { id: 'anomalies', label: 'Anomalies', icon: AlertTriangle },
  { id: 'people', label: 'People', icon: Users },
  { id: 'data', label: 'Data', icon: Database },
];

export const Sidebar: React.FC<SidebarProps> = ({
  activeTab,
  onTabChange,
  datasetLoaded,
  isCollapsed: controlledCollapsed,
  onToggleCollapse: controlledToggle,
}) => {
  const [internalCollapsed, setInternalCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem('workforce_sidebar_collapsed') === 'true';
    } catch {
      return false;
    }
  });

  const isCollapsed = controlledCollapsed !== undefined ? controlledCollapsed : internalCollapsed;

  const handleToggle = () => {
    if (controlledToggle) {
      controlledToggle();
    } else {
      const next = !isCollapsed;
      setInternalCollapsed(next);
      try {
        localStorage.setItem('workforce_sidebar_collapsed', String(next));
      } catch {
        // ignore
      }
    }
  };

  useEffect(() => {
    try {
      localStorage.setItem('workforce_sidebar_collapsed', String(isCollapsed));
    } catch {
      // ignore
    }
  }, [isCollapsed]);

  return (
    <aside
      className={`${
        isCollapsed ? 'w-16' : 'w-60'
      } bg-white border-r border-app-border flex flex-col h-screen select-none shrink-0 transition-all duration-200 ease-in-out z-20`}
    >
      {/* Brand Header */}
      <div className={`p-4 border-b border-app-border/60 flex items-center ${isCollapsed ? 'justify-center' : 'justify-between'}`}>
        {!isCollapsed && (
          <div className="flex items-center gap-2.5 min-w-0 overflow-hidden">
            <div className="w-8 h-8 rounded-lg bg-brand-blue flex items-center justify-center text-white font-semibold text-sm shadow-sm shrink-0">
              T
            </div>
            <div className="min-w-0 truncate">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-text-muted truncate">
                Transformers
              </div>
              <div className="text-xs font-bold text-text-primary tracking-tight truncate">
                Workforce Intelligence
              </div>
            </div>
          </div>
        )}

        {isCollapsed && (
          <div className="w-8 h-8 rounded-lg bg-brand-blue flex items-center justify-center text-white font-semibold text-sm shadow-sm">
            T
          </div>
        )}

        {/* Subtle Toggle Button */}
        <button
          onClick={handleToggle}
          title={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          className={`p-1.5 rounded-lg text-text-secondary hover:text-text-primary hover:bg-app-bg transition-colors ${
            isCollapsed ? 'mt-2' : ''
          }`}
          aria-label={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {isCollapsed ? (
            <PanelLeftOpen className="w-4 h-4 text-text-muted hover:text-brand-blue" />
          ) : (
            <PanelLeftClose className="w-4 h-4 text-text-muted hover:text-brand-blue" />
          )}
        </button>
      </div>

      {/* Navigation List */}
      <nav className={`flex-1 ${isCollapsed ? 'px-2' : 'px-3'} py-5 space-y-1.5 overflow-y-auto overflow-x-hidden`}>
        {!isCollapsed && (
          <div className="px-3 pb-2 text-[10px] font-semibold text-text-muted uppercase tracking-wider">
            Workspace
          </div>
        )}
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const isActive = activeTab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onTabChange(item.id)}
              title={isCollapsed ? item.label : undefined}
              className={`w-full flex items-center ${
                isCollapsed ? 'justify-center px-0 py-2.5' : 'gap-3 px-3 py-2'
              } rounded-lg text-sm font-medium transition-all duration-150 relative group ${
                isActive
                  ? 'bg-brand-blue/10 text-brand-blue font-semibold'
                  : 'text-text-secondary hover:bg-app-bg hover:text-text-primary'
              }`}
            >
              {/* Active bar indicator for collapsed mode */}
              {isCollapsed && isActive && (
                <span className="absolute left-0 top-1.5 bottom-1.5 w-1 rounded-r bg-brand-blue" />
              )}

              <Icon
                className={`w-4 h-4 shrink-0 transition-colors ${
                  isActive ? 'text-brand-blue' : 'text-text-muted group-hover:text-text-primary'
                }`}
              />

              {!isCollapsed && (
                <span className="flex-1 text-left truncate text-xs font-medium">
                  {item.label}
                </span>
              )}

              {item.id === 'data' && datasetLoaded && (
                <span
                  className={`w-2 h-2 rounded-full bg-brand-positive shrink-0 ${
                    isCollapsed ? 'absolute top-1.5 right-1.5' : ''
                  }`}
                />
              )}
            </button>
          );
        })}
      </nav>

      {/* Subtle Footer */}
      <div className="p-3 border-t border-app-border/60 text-[11px] text-text-muted overflow-hidden">
        {isCollapsed ? (
          <div className="flex justify-center" title="Local Active">
            <span className="w-2 h-2 rounded-full bg-brand-positive"></span>
          </div>
        ) : (
          <div className="flex items-center justify-between truncate">
            <span className="truncate">Engine v2.1</span>
            <span className="inline-flex items-center gap-1.5 shrink-0">
              <span className="w-1.5 h-1.5 rounded-full bg-brand-positive"></span>
              Active
            </span>
          </div>
        )}
      </div>
    </aside>
  );
};
