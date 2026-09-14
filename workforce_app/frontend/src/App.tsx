import React, { useState, useEffect, useCallback } from 'react';
import { Sidebar, NavTab } from './components/layout/Sidebar';
import { Overview } from './pages/Overview';
import { Data } from './pages/Data';
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

  // Handle file upload
  const handleFileUpload = async (file: File) => {
    setIsLoading(true);
    setUploadError(null);
    try {
      const result = await uploadDataset(file);
      setData(result);
      setActiveFilters({});
      setActiveTab('overview');
    } catch (err: any) {
      setUploadError(err.message || 'Failed to process file.');
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
          <PlaceholderPage
            title="Trends"
            subtitle="Track process behaviour and policy adoption over time."
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
      {/* Fixed Left Sidebar */}
      <Sidebar
        activeTab={activeTab}
        onTabChange={setActiveTab}
        datasetLoaded={Boolean(data?.loaded)}
      />

      {/* Main Analytical Content Workspace */}
      <main className="flex-1 overflow-y-auto px-7 py-8 md:px-10 md:py-9">
        {renderContent()}
      </main>
    </div>
  );
};

export default App;
