import React from 'react';
import { Loader2 } from 'lucide-react';

interface LoadingStateProps {
  message?: string;
  subMessage?: string;
}

export const LoadingState: React.FC<LoadingStateProps> = ({
  message = 'Analysing workforce data...',
  subMessage = 'Evaluating policies, constructing employee facts, and calculating governed metrics.',
}) => {
  return (
    <div className="bg-white border border-app-border rounded-xl p-12 text-center shadow-subtle max-w-md mx-auto my-12">
      <div className="w-12 h-12 rounded-xl bg-blue-50 text-brand-blue flex items-center justify-center mx-auto mb-4">
        <Loader2 className="w-6 h-6 animate-spin" />
      </div>

      <h3 className="text-base font-bold text-text-primary tracking-tight mb-1.5">
        {message}
      </h3>

      <p className="text-xs text-text-secondary leading-relaxed">
        {subMessage}
      </p>
    </div>
  );
};
