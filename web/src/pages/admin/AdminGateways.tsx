import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { formatDistanceToNow } from 'date-fns';
import { AddGatewayModal } from '../../components/admin/AddGatewayModal';
import { useAdminGateways } from '../../lib/hooks';
import type { DeviceStatus, GatewayAdmin } from '../../lib/types';

const ONLINE_WINDOW_MS = 5 * 60_000;

function gatewayOnline(g: GatewayAdmin): boolean {
  return (
    !!g.last_seen_at &&
    Date.now() - new Date(g.last_seen_at).getTime() < ONLINE_WINDOW_MS
  );
}

const STATUS_CHOICES: { value: DeviceStatus | null; label: string }[] = [
  { value: null, label: 'All' },
  { value: 'online', label: 'Online' },
  { value: 'offline', label: 'Offline' },
];

export function AdminGateways() {
  const navigate = useNavigate();
  const [searchInput, setSearchInput] = useState('');
  const [q, setQ] = useState('');
  const [status, setStatus] = useState<DeviceStatus | null>(null);
  const [showAdd, setShowAdd] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setQ(searchInput), 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  const { data: gateways, isLoading, error } = useAdminGateways({
    q: q || undefined,
    status: status ?? undefined,
  });

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h1 className="text-2xl font-bold">Gateways</h1>
        <button
          type="button"
          onClick={() => setShowAdd(true)}
          className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded text-sm font-medium"
        >
          + Add Gateway
        </button>
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
      {gateways && gateways.length === 0 && !isLoading && (
        <div className="text-sm text-gray-500">No gateways match.</div>
      )}

      {gateways && gateways.length > 0 && (
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
                <th className="px-4 py-2">Controllers</th>
              </tr>
            </thead>
            <tbody>
              {gateways.map((g) => {
                const online = gatewayOnline(g);
                return (
                  <tr
                    key={g.id}
                    onClick={() => navigate(`/admin/gateways/${g.id}`)}
                    className="border-t hover:bg-gray-50 cursor-pointer"
                  >
                    <td className="px-4 py-2 font-mono">
                      <Link
                        to={`/admin/gateways/${g.id}`}
                        onClick={(e) => e.stopPropagation()}
                        className="text-blue-600 hover:text-blue-800 hover:underline font-medium"
                      >
                        {g.device_key}
                      </Link>
                    </td>
                    <td className="px-4 py-2">{g.name}</td>
                    <td className="px-4 py-2 text-gray-600">
                      <Link
                        to={`/admin/users/${g.owner.id}`}
                        onClick={(e) => e.stopPropagation()}
                        className="hover:underline"
                      >
                        {g.owner.email}
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
                          g.mqtt_provisioned
                            ? 'bg-green-100 text-green-700'
                            : 'bg-yellow-100 text-yellow-700'
                        }`}
                      >
                        {g.mqtt_provisioned
                          ? '✓ Provisioned'
                          : '⚠ Not provisioned'}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-gray-600">
                      {g.last_seen_at
                        ? formatDistanceToNow(new Date(g.last_seen_at), {
                            addSuffix: true,
                          })
                        : 'Never'}
                    </td>
                    <td className="px-4 py-2 text-gray-600">
                      {g.controller_count}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <AddGatewayModal open={showAdd} onClose={() => setShowAdd(false)} />
    </div>
  );
}
