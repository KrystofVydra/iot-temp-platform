import { useQuery } from '@tanstack/react-query';
import { apiFetch, ApiError } from './api';
import type { Device, DeviceWithLatestReading, Reading, TimeRange } from './types';

export function useDevices() {
  return useQuery({
    queryKey: ['devices'],
    queryFn: () => apiFetch<DeviceWithLatestReading[]>('/devices'),
    refetchInterval: 30_000,
  });
}

export function useDevice(id: number) {
  return useQuery({
    queryKey: ['devices', id],
    queryFn: () => apiFetch<Device>(`/devices/${id}`),
  });
}

export function useLatestReading(deviceId: number) {
  return useQuery({
    queryKey: ['devices', deviceId, 'latest'],
    queryFn: async (): Promise<Reading | null> => {
      try {
        const r = await apiFetch<Reading | undefined>(`/devices/${deviceId}/readings/latest`);
        // apiFetch returns undefined on 204 (device has no readings yet).
        return r ?? null;
      } catch (e) {
        if (e instanceof ApiError && e.status === 204) return null;
        throw e;
      }
    },
    refetchInterval: 30_000,
  });
}

export function useReadings(deviceId: number, range: TimeRange) {
  return useQuery({
    queryKey: ['devices', deviceId, 'readings', range],
    queryFn: () => {
      const { from, to, bucket } = computeRangeParams(range);
      const params = new URLSearchParams({ from, to, bucket });
      return apiFetch<Reading[]>(`/devices/${deviceId}/readings?${params}`);
    },
    refetchInterval: 60_000,
  });
}

function computeRangeParams(range: TimeRange): { from: string; to: string; bucket: string } {
  const now = new Date();
  const to = now.toISOString();
  const ranges: Record<TimeRange, { from: Date; bucket: string }> = {
    '1h': { from: new Date(now.getTime() - 60 * 60 * 1000), bucket: '1m' },
    '6h': { from: new Date(now.getTime() - 6 * 60 * 60 * 1000), bucket: '5m' },
    '24h': { from: new Date(now.getTime() - 24 * 60 * 60 * 1000), bucket: '15m' },
    '7d': { from: new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000), bucket: '1h' },
    '30d': { from: new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000), bucket: '6h' },
  };
  return {
    from: ranges[range].from.toISOString(),
    to,
    bucket: ranges[range].bucket,
  };
}
