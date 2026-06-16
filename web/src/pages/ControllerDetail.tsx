import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { format } from 'date-fns';
import { ControllerChart } from '../components/ControllerChart';
import { NodeTile } from '../components/NodeTile';
import {
  useController,
  useControllerReadings,
  useControllerTelemetry,
} from '../lib/hooks';
import type { TimeRange } from '../lib/types';

export function ControllerDetail() {
  const { id } = useParams<{ id: string }>();
  const controllerId = parseInt(id!, 10);
  const [range, setRange] = useState<TimeRange>('24h');

  const controller = useController(controllerId);
  const readings = useControllerReadings(controllerId, range);
  const telemetry = useControllerTelemetry(controllerId, range);

  if (controller.isLoading)
    return <div className="text-sm text-gray-500">Loading…</div>;
  if (controller.error)
    return (
      <div className="text-red-600">
        Error: {(controller.error as Error).message}
      </div>
    );
  if (!controller.data) return <div>Not found.</div>;

  const c = controller.data;
  const latestTel = c.latest_telemetry;

  return (
    <div>
      <Link
        to="/"
        className="text-sm text-blue-600 hover:underline mb-4 inline-block"
      >
        ← Controllers
      </Link>

      <div className="mb-6">
        <div className="text-sm text-gray-500">
          {c.gateway.name} <span className="text-gray-300">›</span>{' '}
          <span className="text-gray-700 font-medium">{c.name}</span>
        </div>
        <h1 className="text-2xl font-bold">{c.name}</h1>
        {c.location && (
          <p className="text-gray-500 text-sm">{c.location}</p>
        )}
        <p className="text-xs text-gray-400 font-mono mt-1">sn: {c.sn}</p>
      </div>

      <h2 className="text-lg font-semibold mb-3">
        Nodes ({c.nodes.length})
      </h2>
      {c.nodes.length === 0 ? (
        <p className="text-sm text-gray-500 mb-6">No nodes yet.</p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 mb-6">
          {c.nodes.map((n) => (
            <NodeTile key={n.id} node={n} />
          ))}
        </div>
      )}

      <ControllerChart
        data={readings.data}
        range={range}
        setRange={setRange}
        isLoading={readings.isLoading}
      />

      <div className="mt-4 bg-white rounded-lg shadow-sm p-4 text-sm text-gray-600">
        <div className="font-medium text-gray-700 mb-2">Controller telemetry</div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div>
            <div className="text-xs text-gray-400">Battery</div>
            <div>
              {latestTel.battery_v !== null
                ? `${latestTel.battery_v.toFixed(2)} V`
                : '—'}
            </div>
          </div>
          <div>
            <div className="text-xs text-gray-400">Door</div>
            <div>
              {latestTel.door_open === null
                ? '—'
                : latestTel.door_open
                  ? 'Open'
                  : 'Closed'}
            </div>
          </div>
          <div>
            <div className="text-xs text-gray-400">Last telemetry</div>
            <div>
              {latestTel.time
                ? format(new Date(latestTel.time), 'PPp')
                : '—'}
            </div>
          </div>
          <div>
            <div className="text-xs text-gray-400">Points in range</div>
            <div>{telemetry.data?.length ?? 0}</div>
          </div>
        </div>
      </div>
    </div>
  );
}
