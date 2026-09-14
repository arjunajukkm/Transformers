/**
 * api.ts
 * ──────
 * HTTP API client for Workforce Intelligence backend.
 */

import {
  DashboardResponse,
  FilterOptions,
  ActiveFilters,
  TrendResponse,
  GroupedTrendMetrics,
} from '../types/workforce';

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';

export async function checkHealth(): Promise<{ status: string; module: string; version: string }> {
  const res = await fetch(`${API_BASE}/api/health`);
  if (!res.ok) {
    throw new Error(`Health check failed: ${res.statusText}`);
  }
  return res.json();
}

export async function fetchSummary(filters?: ActiveFilters): Promise<DashboardResponse> {
  const params = new URLSearchParams();
  if (filters) {
    Object.entries(filters).forEach(([k, v]) => {
      if (v) params.append(k, v);
    });
  }

  const url = `${API_BASE}/api/workforce/summary${params.toString() ? `?${params.toString()}` : ''}`;
  const res = await fetch(url);
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(errorData.detail || `Failed to fetch summary: ${res.statusText}`);
  }
  return res.json();
}

export async function uploadDataset(fileOrFiles: File | File[]): Promise<DashboardResponse> {
  const formData = new FormData();
  if (Array.isArray(fileOrFiles)) {
    if (fileOrFiles.length === 1) {
      formData.append('file', fileOrFiles[0]);
    } else {
      fileOrFiles.forEach((f) => formData.append('files', f));
    }
  } else {
    formData.append('file', fileOrFiles);
  }

  const res = await fetch(`${API_BASE}/api/workforce/upload`, {
    method: 'POST',
    body: formData,
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(errorData.detail || `Upload failed with status ${res.status}`);
  }

  return res.json();
}

export async function fetchFilters(): Promise<FilterOptions> {
  const res = await fetch(`${API_BASE}/api/workforce/filters`);
  if (!res.ok) {
    throw new Error(`Failed to fetch filters: ${res.statusText}`);
  }
  return res.json();
}

export async function fetchTrends(metric: string, filters?: ActiveFilters): Promise<TrendResponse> {
  const params = new URLSearchParams();
  params.append('metric', metric);
  if (filters) {
    Object.entries(filters).forEach(([k, v]) => {
      if (v) params.append(k, v);
    });
  }

  const url = `${API_BASE}/api/workforce/trends?${params.toString()}`;
  const res = await fetch(url);
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(errorData.detail || `Failed to fetch trends: ${res.statusText}`);
  }
  return res.json();
}

export async function fetchTrendMetrics(): Promise<GroupedTrendMetrics> {
  const res = await fetch(`${API_BASE}/api/workforce/trends/metrics`);
  if (!res.ok) {
    throw new Error(`Failed to fetch trend metrics: ${res.statusText}`);
  }
  return res.json();
}
