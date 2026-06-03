import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { formatDistanceToNow } from 'date-fns';
import { useAdminDevices } from '../../lib/hooks';
import type { DeviceAdmin, DeviceStatus } from '../../lib/types';

const ONLINE_WINDOW_MS = 5 * 60_000;

function deviceOnline(d: DeviceAdmin): boolean {
  return (
    !!d.last_seen_at &&
    Date.now() - new Date(d.last_seen_at).getTime() < ONLINE_WINDOW_MS
  );
}

const STATUS_CHOICES: { value: DeviceStatus | null; label: string }[] = [
  { value: null, label: 'All' },
  { value: 'online', label: 'Online' },
  { value: 'offline', label: 'Offline' },
];

export function AdminDevices() {
  const navigate = useNavigate();
  const [searchInput, setSearchInput] = useState('');
  const [q, setQ] = useState('');
  const [status, setStatus] = useState<DeviceStatus | null>(null);

  // Debounce the search input 300ms before triggering the query.
  useEffect(() => {
    const t = setTimeout(() => setQ(searchInput), 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  const { data: devices, isLoading, error } = useAdminDevices({
    q: q || undefined,
    status: status ?? undefined,
  });

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h1 className="text-2xl font-bold">Devices</h1>
      </div>

      <div className="bg-white rounded-lg shadow-sm p-3 mb-4 flex gap-2 items-center">
        <input
          type="text"
          placeholder="Search by key, name, location, or owner email…"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          className="flex-1 px-3 py-2 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <div className="flex gap-1">
          {STATUS_CHOICES.map((s) => {
            const active = status === s.value;
            return (
              <button
                key={s.label}
                type="button"
                onClick={() => setStatus(s.value)}
                className={`px-3 py-1 rounded text-sm ${
                  active
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-100 hover:bg-gray-200'
                }`}
              >
                {s.label}
              </button>
            );
          })}
        </div>
      </div>

      {isLoading && <div className="text-sm text-gray-500">Loading…</div>}
      {error && (
        <div className="text-sm text-red-600">
          Error: {(error as Error).message}
        </div>
      )}
      {devices && devices.length === 0 && !isLoading && (
        <div className="text-sm text-gray-500">No devices match.</div>
      )}

      {devices && devices.length > 0 && (
        <div className="bg-white rounded-lg shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left">
              <tr>
                <th className="px-4 py-2">Device Key</th>
                <th className="px-4 py-2">Name</th>
                <th className="px-4 py-2">Owner</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2">MQTT</th>
                <th className="px-4 py-2">Last Seen</th>
              </tr>
            </thead>
            <tbody>
              {devices.map((d) => {
                const online = deviceOnline(d);
                return (
                  <tr
                    key={d.id}
                    onClick={() => navigate(`/admin/devices/${d.id}`)}
                    className="border-t hover:bg-gray-50 cursor-pointer"
                  >
                    <td className="px-4 py-2 font-mono">
                      <Link
                        to={`/admin/devices/${d.id}`}
                        onClick={(e) => e.stopPropagation()}
                        className="text-blue-600 hover:text-blue-800 hover:underline font-medium"
                      >
                        {d.device_key}
                      </Link>
                    </td>
                    <td className="px-4 py-2">{d.name}</td>
                    <td className="px-4 py-2 text-gray-600">
                      <Link
                        to={`/admin/users/${d.owner.id}`}
                        onClick={(e) => e.stopPropagation()}
                        className="hover:underline"
                      >
                        {d.owner.email}
                      </Link>
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
                    <td className="px-4 py-2 text-gray-600">
                      {d.last_seen_at
                        ? formatDistanceToNow(new Date(d.last_seen_at), {
                            addSuffix: true,
                          })
                        : 'Never'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
