import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch, postJson } from './api';
import type {
  AdminNotificationListResponse,
  Controller,
  ControllerDetail,
  ControllerPatch,
  CreateGatewayResponse,
  CreateUserResponse,
  DeviceStatus,
  GatewayAdmin,
  GatewayDetailAdmin,
  GatewayPatch,
  InvitationLinkResponse,
  KindDefault,
  KindDefaultPatch,
  Notification,
  NotificationListResponse,
  NotificationSetting,
  NotificationSettingPatch,
  NotificationSeverity,
  NotificationStatusFilter,
  NodePatch,
  ReadingPoint,
  ResetLinkResponse,
  RotateMqttResponse,
  TelemetryPoint,
  TimeRange,
  UserAdmin,
  UserAdminDetail,
} from './types';

// ===========================================================================
// User-facing controller hooks
// ===========================================================================

export function useControllers() {
  return useQuery({
    queryKey: ['controllers'],
    queryFn: () => apiFetch<Controller[]>('/controllers'),
    refetchInterval: 30_000,
  });
}

export function useController(id: number) {
  return useQuery({
    queryKey: ['controllers', id],
    queryFn: () => apiFetch<ControllerDetail>(`/controllers/${id}`),
    refetchInterval: 30_000,
  });
}

export function useControllerReadings(
  controllerId: number,
  range: TimeRange,
  enabled: boolean = true,
) {
  return useQuery({
    queryKey: ['controllers', controllerId, 'readings', range],
    queryFn: () => {
      const params = buildRangeParams(range);
      return apiFetch<ReadingPoint[]>(
        `/controllers/${controllerId}/readings?${params}`,
      );
    },
    refetchInterval: 60_000,
    enabled,
  });
}

export function useControllerTelemetry(
  controllerId: number,
  range: TimeRange,
  enabled: boolean = true,
) {
  return useQuery({
    queryKey: ['controllers', controllerId, 'telemetry', range],
    queryFn: () => {
      const params = buildRangeParams(range);
      return apiFetch<TelemetryPoint[]>(
        `/controllers/${controllerId}/telemetry?${params}`,
      );
    },
    refetchInterval: 60_000,
    enabled,
  });
}

// 1h, 6h → no bucket (raw points). 24h → 5m. 7d, 30d → 1h.
function buildRangeParams(range: TimeRange): string {
  const now = new Date();
  const to = now.toISOString();
  const spans: Record<TimeRange, { ms: number; bucket: string | null }> = {
    '1h': { ms: 60 * 60 * 1000, bucket: null },
    '6h': { ms: 6 * 60 * 60 * 1000, bucket: null },
    '24h': { ms: 24 * 60 * 60 * 1000, bucket: '5m' },
    '7d': { ms: 7 * 24 * 60 * 60 * 1000, bucket: '1h' },
    '30d': { ms: 30 * 24 * 60 * 60 * 1000, bucket: '1h' },
  };
  const spec = spans[range];
  const from = new Date(now.getTime() - spec.ms).toISOString();
  const params = new URLSearchParams({ from, to });
  if (spec.bucket) params.set('bucket', spec.bucket);
  return params.toString();
}

// ===========================================================================
// Admin: users
// ===========================================================================

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
      void qc.invalidateQueries({ queryKey: ['admin', 'gateways'] });
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

// ===========================================================================
// Admin: gateways
// ===========================================================================

export function useAdminGateways(filter: { q?: string; status?: DeviceStatus }) {
  const params = new URLSearchParams();
  if (filter.q) params.set('q', filter.q);
  if (filter.status) params.set('status', filter.status);
  const qs = params.toString();
  return useQuery({
    queryKey: [
      'admin',
      'gateways',
      { q: filter.q ?? '', status: filter.status ?? '' },
    ],
    queryFn: () =>
      apiFetch<GatewayAdmin[]>(`/admin/gateways${qs ? `?${qs}` : ''}`),
  });
}

export function useAdminGateway(id: number) {
  return useQuery({
    queryKey: ['admin', 'gateways', id],
    queryFn: () => apiFetch<GatewayDetailAdmin>(`/admin/gateways/${id}`),
    refetchInterval: 30_000,
  });
}

export function useCreateGateway() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      user_id: number;
      device_key: string;
      name: string;
      location: string | null;
    }) => postJson<CreateGatewayResponse>('/admin/gateways', input),
    onSuccess: (_data, vars) => {
      void qc.invalidateQueries({ queryKey: ['admin', 'gateways'] });
      void qc.invalidateQueries({ queryKey: ['admin', 'users'] });
      void qc.invalidateQueries({ queryKey: ['admin', 'users', vars.user_id] });
    },
  });
}

export function useUpdateGateway() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: GatewayPatch }) =>
      apiFetch<GatewayAdmin>(`/admin/gateways/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(patch),
      }),
    onSuccess: (_data, vars) => {
      void qc.invalidateQueries({ queryKey: ['admin', 'gateways'] });
      void qc.invalidateQueries({ queryKey: ['admin', 'gateways', vars.id] });
      void qc.invalidateQueries({ queryKey: ['admin', 'users'] });
    },
  });
}

export function useDeleteGateway() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch<void>(`/admin/gateways/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['admin', 'gateways'] });
      void qc.invalidateQueries({ queryKey: ['admin', 'users'] });
    },
  });
}

export function useRotateMqttPassword() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (gatewayId: number) =>
      postJson<RotateMqttResponse>(
        `/admin/gateways/${gatewayId}/rotate-mqtt-password`,
        {},
      ),
    onSuccess: (_data, gatewayId) => {
      void qc.invalidateQueries({ queryKey: ['admin', 'gateways'] });
      void qc.invalidateQueries({ queryKey: ['admin', 'gateways', gatewayId] });
      void qc.invalidateQueries({ queryKey: ['admin', 'users'] });
    },
  });
}

// ===========================================================================
// Admin: pending controllers
// ===========================================================================

export function useAcceptPendingController() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      pendingId,
      name,
      location,
    }: {
      pendingId: number;
      name: string;
      location: string | null;
    }) =>
      postJson<unknown>(`/admin/pending-controllers/${pendingId}/accept`, {
        name,
        location,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['admin', 'gateways'] });
    },
  });
}

export function useRejectPendingController() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (pendingId: number) =>
      postJson<unknown>(`/admin/pending-controllers/${pendingId}/reject`, {}),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['admin', 'gateways'] });
    },
  });
}

// ===========================================================================
// Admin: controllers
// ===========================================================================

export function useAdminController(id: number) {
  return useQuery({
    queryKey: ['admin', 'controllers', id],
    queryFn: () => apiFetch<ControllerDetail>(`/admin/controllers/${id}`),
    refetchInterval: 30_000,
  });
}

export function useAdminControllerReadings(
  controllerId: number,
  range: TimeRange,
  enabled: boolean = true,
) {
  return useQuery({
    queryKey: ['admin', 'controllers', controllerId, 'readings', range],
    queryFn: () => {
      const params = buildRangeParams(range);
      return apiFetch<ReadingPoint[]>(
        `/admin/controllers/${controllerId}/readings?${params}`,
      );
    },
    refetchInterval: 60_000,
    enabled,
  });
}

export function useAdminControllerTelemetry(
  controllerId: number,
  range: TimeRange,
  enabled: boolean = true,
) {
  return useQuery({
    queryKey: ['admin', 'controllers', controllerId, 'telemetry', range],
    queryFn: () => {
      const params = buildRangeParams(range);
      return apiFetch<TelemetryPoint[]>(
        `/admin/controllers/${controllerId}/telemetry?${params}`,
      );
    },
    refetchInterval: 60_000,
    enabled,
  });
}

export function useUpdateController() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: ControllerPatch }) =>
      apiFetch<ControllerDetail>(`/admin/controllers/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(patch),
      }),
    onSuccess: (_data, vars) => {
      void qc.invalidateQueries({
        queryKey: ['admin', 'controllers', vars.id],
      });
      void qc.invalidateQueries({ queryKey: ['admin', 'gateways'] });
    },
  });
}

export function useDeleteController() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch<void>(`/admin/controllers/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['admin', 'controllers'] });
      void qc.invalidateQueries({ queryKey: ['admin', 'gateways'] });
    },
  });
}

// ===========================================================================
// Admin: nodes
// ===========================================================================

export function useUpdateNode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: NodePatch }) =>
      apiFetch<unknown>(`/admin/nodes/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(patch),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['admin', 'controllers'] });
    },
  });
}

export function useDeleteNode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch<void>(`/admin/nodes/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['admin', 'controllers'] });
    },
  });
}

// ===========================================================================
// Notifications (Round 4)
// ===========================================================================

export function useMyNotificationSettings() {
  return useQuery({
    queryKey: ['me', 'notifications', 'settings'],
    queryFn: () =>
      apiFetch<NotificationSetting[]>('/me/notifications/settings'),
  });
}

export function useUpdateMyNotificationSetting() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      kind,
      patch,
    }: {
      kind: string;
      patch: NotificationSettingPatch;
    }) =>
      apiFetch<NotificationSetting>(`/me/notifications/settings/${kind}`, {
        method: 'PATCH',
        body: JSON.stringify(patch),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['me', 'notifications', 'settings'] });
    },
  });
}

export function useMyNotifications(filter: {
  status?: NotificationStatusFilter;
  kind?: string;
  limit?: number;
}) {
  const params = new URLSearchParams();
  if (filter.status) params.set('status', filter.status);
  if (filter.kind) params.set('kind', filter.kind);
  if (filter.limit) params.set('limit', String(filter.limit));
  const qs = params.toString();
  return useQuery({
    queryKey: [
      'me',
      'notifications',
      {
        status: filter.status ?? '',
        kind: filter.kind ?? '',
        limit: filter.limit ?? 0,
      },
    ],
    queryFn: () =>
      apiFetch<NotificationListResponse>(
        `/me/notifications${qs ? `?${qs}` : ''}`,
      ),
    refetchInterval: 60_000,
  });
}

export function useUnreadCount() {
  return useQuery({
    queryKey: ['me', 'notifications', 'unread-count'],
    queryFn: () => apiFetch<{ count: number }>('/me/notifications/unread-count'),
    refetchInterval: 30_000,
  });
}

export function useMarkRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch<void>(`/me/notifications/${id}/read`, { method: 'POST' }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['me', 'notifications'] });
    },
  });
}

export function useMarkAllRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<void>('/me/notifications/mark-all-read', { method: 'POST' }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['me', 'notifications'] });
    },
  });
}

// ----- admin -----

export function useAdminKindDefaults() {
  return useQuery({
    queryKey: ['admin', 'notification-defaults'],
    queryFn: () =>
      apiFetch<KindDefault[]>('/admin/notification-defaults'),
  });
}

export function useAdminUpdateKindDefault() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ kind, patch }: { kind: string; patch: KindDefaultPatch }) =>
      apiFetch<KindDefault>(`/admin/notification-defaults/${kind}`, {
        method: 'PATCH',
        body: JSON.stringify(patch),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['admin', 'notification-defaults'] });
    },
  });
}

export function useAdminNotifications(filter: {
  user_id?: number;
  user_email?: string;
  status?: NotificationStatusFilter;
  kind?: string;
  severity?: NotificationSeverity;
  limit?: number;
  offset?: number;
}) {
  const params = new URLSearchParams();
  if (filter.user_id !== undefined) params.set('user_id', String(filter.user_id));
  if (filter.user_email) params.set('user_email', filter.user_email);
  if (filter.status) params.set('status', filter.status);
  if (filter.kind) params.set('kind', filter.kind);
  if (filter.severity) params.set('severity', filter.severity);
  if (filter.limit !== undefined) params.set('limit', String(filter.limit));
  if (filter.offset !== undefined) params.set('offset', String(filter.offset));
  const qs = params.toString();
  return useQuery({
    queryKey: [
      'admin',
      'notifications',
      {
        user_id: filter.user_id ?? null,
        user_email: filter.user_email ?? '',
        status: filter.status ?? '',
        kind: filter.kind ?? '',
        severity: filter.severity ?? '',
        limit: filter.limit ?? 0,
        offset: filter.offset ?? 0,
      },
    ],
    queryFn: () =>
      apiFetch<AdminNotificationListResponse>(
        `/admin/notifications${qs ? `?${qs}` : ''}`,
      ),
  });
}

export function useAdminUserNotificationSettings(userId: number) {
  return useQuery({
    queryKey: ['admin', 'users', userId, 'notification-settings'],
    queryFn: () =>
      apiFetch<NotificationSetting[]>(
        `/admin/users/${userId}/notification-settings`,
      ),
  });
}

export function useAdminUpdateUserNotificationSetting(userId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      kind,
      patch,
    }: {
      kind: string;
      patch: NotificationSettingPatch;
    }) =>
      apiFetch<NotificationSetting>(
        `/admin/users/${userId}/notification-settings/${kind}`,
        {
          method: 'PATCH',
          body: JSON.stringify(patch),
        },
      ),
    onSuccess: () => {
      void qc.invalidateQueries({
        queryKey: ['admin', 'users', userId, 'notification-settings'],
      });
    },
  });
}

export function useAdminFireTestNotification() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ user_id, kind }: { user_id: number; kind: string }) =>
      postJson<Notification>(`/admin/users/${user_id}/notifications/test`, {
        kind,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['admin', 'notifications'] });
      // Bell badge for the targeted user will refresh on next tick — no
      // direct access to /me/notifications cache from the admin context.
    },
  });
}
