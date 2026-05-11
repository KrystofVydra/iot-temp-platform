import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { format } from 'date-fns';
import { useDevice, useLatestReading, useReadings } from '../lib/hooks';
import type { TimeRange } from '../lib/types';

const RANGES: TimeRange[] = ['1h', '6h', '24h', '7d', '30d'];

export function DeviceDetail() {
  const { id } = useParams<{ id: string }>();
  const deviceId = parseInt(id!, 10);
  const [range, setRange] = useState<TimeRange>('24h');

  const device = useDevice(deviceId);
  const latest = useLatestReading(deviceId);
  const readings = useReadings(deviceId, range);

  if (device.isLoading) return <div>Loading…</div>;
  if (device.error)
    return <div className="text-red-600">Error: {(device.error as Error).message}</div>;
  if (!device.data) return <div>Not found.</div>;

  const chartData =
    readings.data?.map((r) => ({
      time: new Date(r.time).getTime(),
      temperature: r.temperature,
    })) ?? [];

  const wideRange = range === '7d' || range === '30d';

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

      <div className="bg-white rounded-lg shadow-sm p-4">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">Temperature History</h2>
          <div className="flex gap-1">
            {RANGES.map((r) => (
              <button
                key={r}
                onClick={() => setRange(r)}
                className={`px-3 py-1 rounded text-sm ${
                  range === r
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-100 hover:bg-gray-200'
                }`}
              >
                {r}
              </button>
            ))}
          </div>
        </div>
        <div style={{ width: '100%', height: 300 }}>
          <ResponsiveContainer>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
              <XAxis
                dataKey="time"
                type="number"
                scale="time"
                domain={['dataMin', 'dataMax']}
                tickFormatter={(t) =>
                  format(new Date(t), wideRange ? 'MMM d' : 'HH:mm')
                }
              />
              <YAxis domain={['auto', 'auto']} tickFormatter={(v) => `${v.toFixed(1)}°`} />
              <Tooltip
                labelFormatter={(t) => format(new Date(t as number), 'PPpp')}
                formatter={(v: number) => `${v.toFixed(2)}°C`}
              />
              <Line
                type="monotone"
                dataKey="temperature"
                stroke="#2563eb"
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
