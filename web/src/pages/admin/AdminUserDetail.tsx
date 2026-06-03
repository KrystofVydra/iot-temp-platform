import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { format, formatDistanceToNow } from 'date-fns';
import { AddDeviceModal } from '../../components/admin/AddDeviceModal';
import { MqttCredentialsModal } from '../../components/admin/MqttCredentialsModal';
import { useAdminUser } from '../../lib/hooks';
import type { DeviceForUser } from '../../lib/types';

const ONLINE_WINDOW_MS = 5 * 60_000;

function isOnline(d: DeviceForUser): boolean {
  return (
    !!d.last_seen_at &&
    Date.now() - new Date(d.last_seen_at).getTime() < ONLINE_WINDOW_MS
  );
}

export function AdminUserDetail() {
  const { id } = useParams<{ id: string }>();
  const userId = parseInt(id!, 10);
  const { data, isLoading, error } = useAdminUser(userId);

  const [showAddDevice, setShowAddDevice] = useState(false);
  const [rotateForDeviceId, setRotateForDeviceId] = useState<number | null>(null);

  if (isLoading) return <div className="text-sm text-gray-500">Loading…</div>;
  if (error)
    return (
      <div className="text-sm text-red-600">
        Error: {(error as Error).message}
      </div>
    );
  if (!data) return null;

  const statusBadge = !data.is_active
    ? { cls: 'bg-gray-100 text-gray-600', label: 'Deactivated' }
    : !data.has_password
      ? { cls: 'bg-yellow-100 text-yellow-700', label: 'Pending invitation' }
      : { cls: 'bg-green-100 text-green-700', label: 'Active' };

  return (
    <div>
      <Link
        to="/admin/users"
        className="text-sm text-blue-600 hover:underline mb-4 inline-block"
      >
        &larr; Users
      </Link>

      <div className="bg-white rounded-lg shadow-sm p-6 mb-6">
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-bold">{data.display_name}</h1>
            <p className="text-gray-600">{data.email}</p>
          </div>
          <div className="flex gap-2 items-center">
            {data.is_admin && (
              <span className="text-xs px-2 py-1 rounded bg-purple-100 text-purple-700">
                admin
              </span>
            )}
            <span className={`text-xs px-2 py-1 rounded ${statusBadge.cls}`}>
              {statusBadge.label}
            </span>
          </div>
        </div>
        <dl className="mt-4 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-gray-500">Created</dt>
          <dd>{format(new Date(data.created_at), 'PPpp')}</dd>
          <dt className="text-gray-500">Last login</dt>
          <dd>
            {data.last_login_at
              ? formatDistanceToNow(new Date(data.last_login_at), {
                  addSuffix: true,
                })
              : 'Never'}
          </dd>
        </dl>
      </div>

      <div className="flex items-center justify-between mb-3">
        <h2 className="text-lg font-semibold">
          Devices ({data.devices.length})
        </h2>
        <button
          type="button"
          onClick={() => setShowAddDevice(true)}
          className="bg-blue-600 hover:bg-blue-700 text-white px-3 py-1 rounded text-sm font-medium"
        >
          + Add device
        </button>
      </div>

      <div className="bg-white rounded-lg shadow-sm overflow-hidden">
        {data.devices.length === 0 ? (
          <p className="text-sm text-gray-500 p-4">No devices yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left">
              <tr>
                <th className="px-4 py-2">Device key</th>
                <th className="px-4 py-2">Name</th>
                <th className="px-4 py-2">Location</th>
                <th className="px-4 py-2">Last Seen</th>
                <th className="px-4 py-2">MQTT</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {data.devices.map((d) => {
                const online = isOnline(d);
                return (
                  <tr key={d.id} className="border-t">
                    <td className="px-4 py-2 font-mono">
                      <Link
                        to={`/admin/devices/${d.id}`}
                        className="text-blue-600 hover:underline"
                      >
                        {d.device_key}
                      </Link>
                    </td>
                    <td className="px-4 py-2">{d.name}</td>
                    <td className="px-4 py-2 text-gray-600">
                      {d.location || '—'}
                    </td>
                    <td className="px-4 py-2 text-gray-600">
                      {d.last_seen_at
                        ? formatDistanceToNow(new Date(d.last_seen_at), {
                            addSuffix: true,
                          })
                        : 'Never'}
                    </td>
                    <td className="px-4 py-2">
                      <span
                        className={`text-xs px-2 py-1 rounded ${
                          d.mqtt_provisioned
                            ? 'bg-green-100 text-green-700'
                            : 'bg-yellow-100 text-yellow-700'
                        }`}
                      >
                        {d.mqtt_provisioned
                          ? '✓ Provisioned'
                          : '⚠ Not provisioned'}
                      </span>
                    </td>
                    <td className="px-4 py-2">
                      <span
                        className={`text-xs px-2 py-1 rounded ${
                          online
                            ? 'bg-green-100 text-green-700'
                            : 'bg-gray-100 text-gray-600'
                        }`}
                      >
                        {online ? 'Online' : 'Offline'}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-right">
                      <details className="relative inline-block">
                        <summary className="cursor-pointer list-none text-gray-500 hover:text-gray-900 px-2 select-none">
                          ⋯
                        </summary>
                        <div className="absolute right-0 mt-1 bg-white shadow-md border rounded text-sm w-56 z-10">
                          <Link
                            to={`/admin/devices/${d.id}`}
                            className="block px-3 py-2 hover:bg-gray-50"
                          >
                            View
                          </Link>
                          <button
                            type="button"
                            onClick={() => setRotateForDeviceId(d.id)}
                            className="block w-full text-left px-3 py-2 hover:bg-gray-50"
                          >
                            {d.mqtt_provisioned
                              ? 'Rotate MQTT password'
                              : 'Generate MQTT password'}
                          </button>
                        </div>
                      </details>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <AddDeviceModal
        open={showAddDevice}
        onClose={() => setShowAddDevice(false)}
        userId={userId}
      />
      {rotateForDeviceId !== null && (
        <MqttCredentialsModal
          open={true}
          onClose={() => setRotateForDeviceId(null)}
          deviceId={rotateForDeviceId}
        />
      )}
    </div>
  );
}
