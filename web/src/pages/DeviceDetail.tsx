import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { format } from 'date-fns';
import { DeviceChart } from '../components/DeviceChart';
import { useDevice, useLatestReading } from '../lib/hooks';
import type { TimeRange } from '../lib/types';

export function DeviceDetail() {
  const { id } = useParams<{ id: string }>();
  const deviceId = parseInt(id!, 10);
  const [range, setRange] = useState<TimeRange>('24h');

  const device = useDevice(deviceId);
  const latest = useLatestReading(deviceId);

  if (device.isLoading) return <div>Loading…</div>;
  if (device.error)
    return <div className="text-red-600">Error: {(device.error as Error).message}</div>;
  if (!device.data) return <div>Not found.</div>;

  return (
    <div>
      <Link to="/" className="text-sm text-blue-600 hover:underline mb-4 inline-block">
        ← Back
      </Link>
      <h1 className="text-2xl font-bold">{device.data.name}</h1>
      <p className="text-gray-500 mb-6">{device.data.location || device.data.device_key}</p>

      {latest.data && (
        <div className="bg-white rounded-lg shadow-sm p-6 mb-6">
          <div className="text-5xl font-light mb-2">
            {latest.data.temperature.toFixed(2)}°C
          </div>
          <div className="text-sm text-gray-500">
            Lux: {latest.data.lux} · Battery:{' '}
            {latest.data.battery_v !== null ? `${latest.data.battery_v.toFixed(2)}V` : '–'} ·
            Updated {format(new Date(latest.data.time), 'PPpp')}
          </div>
        </div>
      )}

      <DeviceChart deviceId={deviceId} range={range} setRange={setRange} />
    </div>
  );
}
