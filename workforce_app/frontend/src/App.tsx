import React, { useState, useEffect, useCallback } from 'react';
import { Sidebar, NavTab } from './components/layout/Sidebar';
import { Overview } from './pages/Overview';
import { Data } from './pages/Data';
import { Trends } from './pages/Trends';
import { PlaceholderPage } from './pages/PlaceholderPage';
import { fetchSummary, uploadDataset } from './services/api';
import { DashboardResponse, ActiveFilters } from './types/workforce';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<NavTab>('overview');
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [activeFilters, setActiveFilters] = useState<ActiveFilters>({});
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [uploadError, setUploadError] = useState<string | null>(null);

  // Load initial session summary on mount
  const loadSummary = useCallback(async (filters?: ActiveFilters) => {
    setIsLoading(true);
    try {
      const summary = await fetchSummary(filters);
      setData(summary);
      if (summary.active_filters) {
        setActiveFilters(summary.active_filters);
      }
    } catch (err: any) {
      console.warn('Initial summary fetch error or no dataset loaded:', err.message);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSummary();
  }, [loadSummary]);

  // Handle file upload (supports single or multi-file)
  const handleFileUpload = async (fileOrFiles: File | File[]) => {
    setIsLoading(true);
    setUploadError(null);
    try {
      const result = await uploadDataset(fileOrFiles);
      setData(result);
      setActiveFilters({});
      setActiveTab('overview');
    } catch (err: any) {
      setUploadError(err.message || 'Failed to process file(s).');
    } finally {
      setIsLoading(false);
    }
  };

  // Handle dynamic filter change
  const handleFilterChange = async (key: keyof ActiveFilters, value: string) => {
    const updatedFilters = {
      ...activeFilters,
      [key]: value || undefined,
    };
    setActiveFilters(updatedFilters);
    await loadSummary(updatedFilters);
  };

  // Handle filter reset
  const handleResetFilters = async () => {
    setActiveFilters({});
    await loadSummary({});
  };

  // Render current view
  const renderContent = () => {
    switch (activeTab) {
      case 'overview':
        return (
          <Overview
            data={data}
            isLoading={isLoading}
            onFilterChange={handleFilterChange}
            onResetFilters={handleResetFilters}
            onNavigateToData={() => setActiveTab('data')}
            onUploadClick={() => setActiveTab('data')}
          />
        );

      case 'data':
        return (
          <Data
            data={data}
            isLoading={isLoading}
            onFileUpload={handleFileUpload}
            uploadError={uploadError}
          />
        );

      case 'trends':
        return (
          <Trends
            data={data}
            onNavigateToData={() => setActiveTab('data')}
          />
        );

      case 'patterns':
        return (
          <PlaceholderPage
            title="Patterns"
            subtitle="Discover recurring employee, team and manager behaviours."
          />
        );

      case 'anomalies':
        return (
          <PlaceholderPage
            title="Anomalies"
            subtitle="Identify unusual behaviour and deviations from expected patterns."
          />
        );

      case 'people':
        return (
          <PlaceholderPage
            title="People"
            subtitle="Investigate employee and manager process behaviour."
          />
        );

      default:
        return null;
    }
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-app-bg text-text-primary">
      {/* Collapsible Left Sidebar */}
      <Sidebar
        activeTab={activeTab}
        onTabChange={setActiveTab}
        datasetLoaded={Boolean(data?.loaded)}
      />

      {/* Main Analytical Content Workspace with overflow protection */}
      <main className="flex-1 min-w-0 overflow-y-auto overflow-x-hidden px-5 py-6 sm:px-7 sm:py-8 lg:px-9 lg:py-8 transition-all duration-200">
        {renderContent()}
      </main>
    </div>
  );
};

export default App;
