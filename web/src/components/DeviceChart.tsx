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
import { useAdminReadings, useReadings } from '../lib/hooks';
import type { TimeRange } from '../lib/types';

const RANGES: TimeRange[] = ['1h', '6h', '24h', '7d', '30d'];

export type DeviceChartMode = 'self' | 'admin';

type Props = {
  deviceId: number;
  range: TimeRange;
  setRange: (r: TimeRange) => void;
  mode?: DeviceChartMode;
};

export function DeviceChart({ deviceId, range, setRange, mode = 'self' }: Props) {
  // Both hooks register so React's rules-of-hooks holds across renders, but
  // only the one matching `mode` is enabled — the other stays in idle state.
  const selfQuery = useReadings(deviceId, range, mode === 'self');
  const adminQuery = useAdminReadings(deviceId, range, mode === 'admin');
  const readings = mode === 'admin' ? adminQuery : selfQuery;

  const data =
    readings.data?.map((r) => ({
      time: new Date(r.time).getTime(),
      temperature: r.temperature,
    })) ?? [];

  const wideRange = range === '7d' || range === '30d';

  return (
    <div className="bg-white rounded-lg shadow-sm p-4">
      <div className="flex items-center justify-between mb-4">
        <h2 className="font-semibold">Temperature History</h2>
        <div className="flex gap-1">
          {RANGES.map((r) => (
            <button
              key={r}
              type="button"
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
          <LineChart data={data}>
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
            <YAxis
              domain={['auto', 'auto']}
              tickFormatter={(v) => `${v.toFixed(1)}°`}
            />
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
  );
}
