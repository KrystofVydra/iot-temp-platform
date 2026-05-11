import { Link } from 'react-router-dom';
import { formatDistanceToNow } from 'date-fns';
import { useDevices } from '../lib/hooks';

const ONLINE_WINDOW_MS = 5 * 60_000;

export function Dashboard() {
  const { data, isLoading, error } = useDevices();

  if (isLoading) return <div>Loading…</div>;
  if (error) return <div className="text-red-600">Error: {(error as Error).message}</div>;
  if (!data || data.length === 0) return <div>No devices found.</div>;

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Devices</h1>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {data.map(({ device, latest }) => {
          const online =
            !!device.last_seen_at &&
            Date.now() - new Date(device.last_seen_at).getTime() < ONLINE_WINDOW_MS;
          return (
            <Link
              key={device.id}
              to={`/devices/${device.id}`}
              className="block bg-white rounded-lg shadow-sm p-4 hover:shadow-md transition"
            >
              <div className="flex justify-between items-start mb-2">
                <div>
                  <div className="font-semibold">{device.name}</div>
                  <div className="text-xs text-gray-500">
                    {device.location || device.device_key}
                  </div>
                </div>
                <span
                  className={`text-xs px-2 py-1 rounded ${
                    online ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600'
                  }`}
                >
                  {online ? 'Online' : 'Offline'}
                </span>
              </div>
              {latest ? (
                <div className="space-y-1 text-sm">
                  <div className="text-3xl font-light">{latest.temperature.toFixed(1)}°C</div>
                  <div className="text-gray-500">
                    Lux: {latest.lux} · Battery:{' '}
                    {latest.battery_v !== null ? `${latest.battery_v.toFixed(2)}V` : '–'}
                  </div>
                  <div className="text-xs text-gray-400">
                    Updated {formatDistanceToNow(new Date(latest.time), { addSuffix: true })}
                  </div>
                </div>
              ) : (
                <div className="text-gray-400 italic">No readings yet</div>
              )}
            </Link>
          );
        })}
      </div>
    </div>
  );
}
