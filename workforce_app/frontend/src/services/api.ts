/**
 * api.ts
 * ──────
 * HTTP API client for Workforce Intelligence backend.
 */

import { DashboardResponse, FilterOptions, ActiveFilters } from '../types/workforce';

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

export async function uploadDataset(file: File): Promise<DashboardResponse> {
  const formData = new FormData();
  formData.append('file', file);

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
