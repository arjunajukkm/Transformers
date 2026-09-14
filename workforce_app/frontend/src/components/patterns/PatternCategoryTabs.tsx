import React from 'react';

interface PatternCategoryTabsProps {
  selectedCategory: string;
  onSelectCategory: (cat: string) => void;
  categoryCounts: Record<string, number>;
  totalPatterns: number;
}

const CATEGORIES = [
  { id: '', label: 'All Patterns' },
  { id: 'Attendance', label: 'Attendance' },
  { id: 'Leave', label: 'Leave' },
  { id: 'WFH', label: 'WFH' },
  { id: 'Approval', label: 'Approval' },
  { id: 'Calendar', label: 'Calendar' },
  { id: 'Sequence', label: 'Sequence' },
  { id: 'Process', label: 'Process' },
];

export const PatternCategoryTabs: React.FC<PatternCategoryTabsProps> = ({
  selectedCategory,
  onSelectCategory,
  categoryCounts,
  totalPatterns,
}) => {
  return (
    <div className="flex items-center gap-1.5 overflow-x-auto pb-1 scrollbar-thin border-b border-app-border">
      {CATEGORIES.map((cat) => {
        const isSelected = selectedCategory === cat.id;
        const count = cat.id === '' ? totalPatterns : categoryCounts[cat.id] || 0;

        return (
          <button
            key={cat.id}
            onClick={() => onSelectCategory(cat.id)}
            className={`flex items-center gap-2 px-3 py-2 text-xs font-semibold rounded-t-lg transition-all whitespace-nowrap border-b-2 -mb-[1px] ${
              isSelected
                ? 'border-brand-blue text-brand-blue bg-blue-50/50'
                : 'border-transparent text-app-text-secondary hover:text-app-text-primary hover:bg-slate-50'
            }`}
          >
            <span>{cat.label}</span>
            <span
              className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${
                isSelected
                  ? 'bg-blue-100 text-brand-blue'
                  : 'bg-slate-100 text-app-text-muted'
              }`}
            >
              {count}
            </span>
          </button>
        );
      })}
    </div>
  );
};
