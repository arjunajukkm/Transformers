import React from 'react';
import { PatternResult } from '../../types/workforce';
import { PatternListItem } from './PatternListItem';

interface PatternListProps {
  patterns: PatternResult[];
  onViewEvidence: (pattern: PatternResult) => void;
}

export const PatternList: React.FC<PatternListProps> = ({
  patterns,
  onViewEvidence,
}) => {
  return (
    <div className="space-y-3.5 min-w-0">
      {patterns.map((pattern) => (
        <PatternListItem
          key={pattern.pattern_id}
          pattern={pattern}
          onViewEvidence={onViewEvidence}
        />
      ))}
    </div>
  );
};
