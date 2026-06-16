import { Link } from 'react-router-dom';
import { formatDistanceToNow } from 'date-fns';
import { useControllers } from '../lib/hooks';
import type { Controller } from '../lib/types';

const ONLINE_WINDOW_MS = 5 * 60_000;

function isOnline(c: Controller): boolean {
  return (
    !!c.last_seen_at &&
    Date.now() - new Date(c.last_seen_at).getTime() < ONLINE_WINDOW_MS
  );
}

function batteryClass(v: number | null): string {
  if (v === null) return 'text-gray-400';
  if (v < 2.0) return 'text-red-600';
  if (v < 2.5) return 'text-orange-500';
  return 'text-gray-500';
}

export function Dashboard() {
  const { data, isLoading, error } = useControllers();

  if (isLoading) return <div>Loading…</div>;
  if (error)
    return (
      <div className="text-red-600">Error: {(error as Error).message}</div>
    );

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Controllers</h1>

      {!data || data.length === 0 ? (
        <div className="text-gray-500">
          No controllers yet. Contact your admin to provision a device.
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {data.map((c) => (
            <ControllerTile key={c.id} controller={c} />
          ))}
        </div>
      )}
    </div>
  );
}

function ControllerTile({ controller }: { controller: Controller }) {
  const online = isOnline(controller);
  const { latest } = controller;
  const tempStr =
    latest.temperature_avg !== null
      ? `${latest.temperature_avg.toFixed(2)} °C`
      : '—';

  return (
    <Link
      to={`/controllers/${controller.id}`}
      className="block bg-white rounded-lg shadow-sm p-4 hover:shadow-md transition"
    >
      <div className="flex justify-between items-start mb-2 gap-2">
        <div className="min-w-0">
          <div className="font-semibold truncate">{controller.name}</div>
          <div className="text-xs text-gray-500 truncate">
            via {controller.gateway.name}
          </div>
          {controller.location && (
            <div className="text-xs text-gray-500 truncate">
              {controller.location}
            </div>
          )}
        </div>
        <span
          className={`text-xs px-2 py-1 rounded shrink-0 ${
            online
              ? 'bg-green-100 text-green-700'
              : 'bg-gray-100 text-gray-600'
          }`}
        >
          {online ? 'Online' : 'Offline'}
        </span>
      </div>

      <div className="text-3xl font-light mb-2">{tempStr}</div>

      <div className="flex items-center gap-3 text-xs">
        <span
          className={batteryClass(latest.battery_v)}
          title="Battery voltage"
        >
          🔋{' '}
          {latest.battery_v !== null
            ? `${latest.battery_v.toFixed(1)}V`
            : '—'}
        </span>
        {latest.door_open !== null && (
          <span
            className={
              latest.door_open ? 'text-amber-600' : 'text-gray-500'
            }
            title={latest.door_open ? 'Door open' : 'Door closed'}
          >
            🚪 {latest.door_open ? 'Open' : 'Closed'}
          </span>
        )}
        {latest.any_node_error && (
          <span className="text-red-600" title="One or more nodes reporting an error">
            ⚠ Error
          </span>
        )}
      </div>

      <div className="text-xs text-gray-400 mt-2">
        {latest.time
          ? `Updated ${formatDistanceToNow(new Date(latest.time), { addSuffix: true })}`
          : 'No readings yet'}
      </div>

      <div className="text-xs text-gray-400 mt-1">
        {controller.node_count} node{controller.node_count === 1 ? '' : 's'}
      </div>
    </Link>
  );
}
