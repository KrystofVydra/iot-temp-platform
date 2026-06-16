import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { format } from 'date-fns';
import type { ReadingPoint, TimeRange } from '../lib/types';

const RANGES: TimeRange[] = ['1h', '6h', '24h', '7d', '30d'];

type Props = {
  data: ReadingPoint[] | undefined;
  range: TimeRange;
  setRange: (r: TimeRange) => void;
  isLoading?: boolean;
};

export function ControllerChart({ data, range, setRange, isLoading }: Props) {
  const points =
    data
      ?.filter((r) => r.temperature_avg !== null)
      .map((r) => ({
        time: new Date(r.time).getTime(),
        temperature: r.temperature_avg as number,
      })) ?? [];

  const wideRange = range === '7d' || range === '30d';

  return (
    <div className="bg-white rounded-lg shadow-sm p-4">
      <div className="flex items-center justify-between mb-4">
        <h2 className="font-semibold">Temperature (avg of all nodes)</h2>
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
        {isLoading && points.length === 0 ? (
          <div className="h-full flex items-center justify-center text-sm text-gray-400">
            Loading…
          </div>
        ) : points.length === 0 ? (
          <div className="h-full flex items-center justify-center text-sm text-gray-400">
            No data for this range.
          </div>
        ) : (
          <ResponsiveContainer>
            <AreaChart data={points}>
              <defs>
                <linearGradient id="tempFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#2563eb" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="#2563eb" stopOpacity={0} />
                </linearGradient>
              </defs>
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
                formatter={(v: number) => [`${v.toFixed(2)}°C`, 'Avg temp']}
              />
              <Area
                type="monotone"
                dataKey="temperature"
                stroke="#2563eb"
                strokeWidth={2}
                fill="url(#tempFill)"
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
