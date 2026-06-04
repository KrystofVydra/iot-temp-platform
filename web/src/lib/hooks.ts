import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, apiFetch, postJson } from './api';
import type {
  CreateDeviceResponse,
  CreateUserResponse,
  Device,
  DeviceAdmin,
  DevicePatch,
  DeviceStatus,
  DeviceWithLatestReading,
  InvitationLinkResponse,
  Reading,
  ResetLinkResponse,
  RotateMqttResponse,
  TimeRange,
  UserAdmin,
  UserAdminDetail,
} from './types';

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

export function useReadings(
  deviceId: number,
  range: TimeRange,
  enabled: boolean = true,
) {
  return useQuery({
    queryKey: ['devices', deviceId, 'readings', range],
    queryFn: () => {
      const { from, to, bucket } = computeRangeParams(range);
      const params = new URLSearchParams({ from, to, bucket });
      return apiFetch<Reading[]>(`/devices/${deviceId}/readings?${params}`);
    },
    refetchInterval: 60_000,
    enabled,
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

// =============================================================================
// Admin hooks
// =============================================================================

export function useAdminUsers() {
  return useQuery({
    queryKey: ['admin', 'users'],
    queryFn: () => apiFetch<UserAdmin[]>('/admin/users'),
  });
}

export function useAdminUser(id: number) {
  return useQuery({
    queryKey: ['admin', 'users', id],
    queryFn: () => apiFetch<UserAdminDetail>(`/admin/users/${id}`),
  });
}

export function useAdminDevices(filter: { q?: string; status?: DeviceStatus }) {
  const params = new URLSearchParams();
  if (filter.q) params.set('q', filter.q);
  if (filter.status) params.set('status', filter.status);
  const qs = params.toString();
  return useQuery({
    queryKey: [
      'admin',
      'devices',
      { q: filter.q ?? '', status: filter.status ?? '' },
    ],
    queryFn: () =>
      apiFetch<DeviceAdmin[]>(`/admin/devices${qs ? `?${qs}` : ''}`),
  });
}

export function useAdminDevice(id: number) {
  return useQuery({
    queryKey: ['admin', 'devices', id],
    queryFn: () => apiFetch<DeviceAdmin>(`/admin/devices/${id}`),
  });
}

export function useAdminLatestReading(deviceId: number) {
  return useQuery({
    queryKey: ['admin', 'devices', deviceId, 'latest'],
    queryFn: async (): Promise<Reading | null> => {
      try {
        const r = await apiFetch<Reading | undefined>(
          `/admin/devices/${deviceId}/readings/latest`,
        );
        // apiFetch returns undefined on 204 (no readings yet).
        return r ?? null;
      } catch (e) {
        if (e instanceof ApiError && e.status === 204) return null;
        throw e;
      }
    },
    refetchInterval: 30_000,
  });
}

export function useAdminReadings(
  deviceId: number,
  range: TimeRange,
  enabled: boolean = true,
) {
  return useQuery({
    queryKey: ['admin', 'devices', deviceId, 'readings', range],
    queryFn: () => {
      const { from, to, bucket } = computeRangeParams(range);
      const params = new URLSearchParams({ from, to, bucket });
      return apiFetch<Reading[]>(
        `/admin/devices/${deviceId}/readings?${params}`,
      );
    },
    refetchInterval: 60_000,
    enabled,
  });
}

export function useCreateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { email: string; display_name: string }) =>
      postJson<CreateUserResponse>('/admin/users', input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['admin', 'users'] });
    },
  });
}

export function useDeactivateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch<void>(`/admin/users/${id}/deactivate`, { method: 'POST' }),
    onSuccess: (_data, id) => {
      void qc.invalidateQueries({ queryKey: ['admin', 'users'] });
      void qc.invalidateQueries({ queryKey: ['admin', 'users', id] });
    },
  });
}

export function useReactivateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch<void>(`/admin/users/${id}/reactivate`, { method: 'POST' }),
    onSuccess: (_data, id) => {
      void qc.invalidateQueries({ queryKey: ['admin', 'users'] });
      void qc.invalidateQueries({ queryKey: ['admin', 'users', id] });
    },
  });
}

export function useDeleteUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch<void>(`/admin/users/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['admin', 'users'] });
      void qc.invalidateQueries({ queryKey: ['admin', 'devices'] });
    },
  });
}

export function useSendResetLink() {
  return useMutation({
    mutationFn: (id: number) =>
      postJson<ResetLinkResponse>(`/admin/users/${id}/reset-link`, {}),
  });
}

export function useResendInvitation() {
  return useMutation({
    mutationFn: (id: number) =>
      postJson<InvitationLinkResponse>(
        `/admin/users/${id}/resend-invitation`,
        {},
      ),
  });
}

export function useCreateDevice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      user_id: number;
      device_key: string;
      name: string;
      location: string | null;
    }) => postJson<CreateDeviceResponse>('/admin/devices', input),
    onSuccess: (_data, vars) => {
      void qc.invalidateQueries({ queryKey: ['admin', 'devices'] });
      void qc.invalidateQueries({ queryKey: ['admin', 'users'] });
      void qc.invalidateQueries({ queryKey: ['admin', 'users', vars.user_id] });
    },
  });
}

export function useUpdateDevice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: DevicePatch }) =>
      apiFetch<DeviceAdmin>(`/admin/devices/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(patch),
      }),
    onSuccess: (_data, vars) => {
      void qc.invalidateQueries({ queryKey: ['admin', 'devices'] });
      void qc.invalidateQueries({ queryKey: ['admin', 'devices', vars.id] });
      void qc.invalidateQueries({ queryKey: ['admin', 'users'] });
    },
  });
}

export function useDeleteDevice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch<void>(`/admin/devices/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['admin', 'devices'] });
      void qc.invalidateQueries({ queryKey: ['admin', 'users'] });
    },
  });
}

export function useRotateMqttPassword() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      postJson<RotateMqttResponse>(
        `/admin/devices/${id}/rotate-mqtt-password`,
        {},
      ),
    onSuccess: (_data, id) => {
      void qc.invalidateQueries({ queryKey: ['admin', 'devices'] });
      void qc.invalidateQueries({ queryKey: ['admin', 'devices', id] });
      void qc.invalidateQueries({ queryKey: ['admin', 'users'] });
    },
  });
}
