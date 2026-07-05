import {
  Area,
  AreaChart,
  CartesianGrid,
  LineChart,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { TooltipProps } from 'recharts';
import { format } from 'date-fns';
import type { ReadingPoint, TelemetryPoint, TimeRange } from '../lib/types';

const RANGES: TimeRange[] = ['1h', '6h', '24h', '7d', '30d'];

// Amber-500 — door-open is a NORMAL event, so deliberately not red (red is
// reserved for temperature alerts elsewhere in the UI).
const DOOR_OPEN_COLOR = '#f59e0b';
const DOOR_CLOSED_COLOR = '#e5e7eb'; // gray-200

// Both charts share these so the rug strip's plot area lines up pixel-for-pixel
// with the temperature chart's (same left gutter = margin.left + YAxis width,
// same right margin).
const Y_AXIS_WIDTH = 48;
const CHART_MARGIN = { top: 5, right: 8, left: 0, bottom: 0 } as const;
const RUG_MARGIN = { top: 0, right: 8, left: 0, bottom: 0 } as const;

// Door shading/rug loses meaning once a bucket spans much more than an hour,
// so we hide it for the 30d range (which buckets to 1h but covers too wide a
// span to read sub-bucket door activity). 7d and shorter stay visible.
function doorLayerVisible(range: TimeRange): boolean {
  return range !== '30d';
}

type Props = {
  data: ReadingPoint[] | undefined;
  telemetry?: TelemetryPoint[];
  range: TimeRange;
  setRange: (r: TimeRange) => void;
  isLoading?: boolean;
};

type TempPoint = { time: number; temperature: number; door: boolean | null };
type DoorInterval = { x1: number; x2: number };

export function ControllerChart({
  data,
  telemetry,
  range,
  setRange,
  isLoading,
}: Props) {
  // Door state keyed by exact bucket timestamp. Readings and telemetry share
  // the same bucket, so timestamps align exactly (a controller message writes
  // one node_reading and one controller_telemetry at the same instant).
  const doorByTime = new Map<number, boolean | null>();
  (telemetry ?? []).forEach((t) =>
    doorByTime.set(new Date(t.time).getTime(), t.door_open),
  );

  const points: TempPoint[] =
    data
      ?.filter((r) => r.temperature_avg !== null)
      .map((r) => {
        const time = new Date(r.time).getTime();
        return {
          time,
          temperature: r.temperature_avg as number,
          door: doorByTime.get(time) ?? null,
        };
      }) ?? [];

  const telPoints = (telemetry ?? []).map((t) => ({
    time: new Date(t.time).getTime(),
    door: t.door_open,
  }));

  const showDoor = doorLayerVisible(range) && telPoints.length > 0;
  const doorIntervals = showDoor ? computeDoorIntervals(telPoints) : [];

  // Pin an explicit x-domain shared by the temp chart and the rug so their
  // time-scales map identically.
  const xDomain = computeDomain(points.map((p) => p.time));

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
            <AreaChart data={points} margin={CHART_MARGIN}>
              <defs>
                <linearGradient id="tempFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#2563eb" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="#2563eb" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
              {/* Door-open shading — rendered BEFORE the Area so it draws behind
                  the temperature line. */}
              {doorIntervals.map((iv) => (
                <ReferenceArea
                  key={`door-${iv.x1}`}
                  x1={iv.x1}
                  x2={iv.x2}
                  fill={DOOR_OPEN_COLOR}
                  fillOpacity={0.15}
                  strokeOpacity={0}
                />
              ))}
              <XAxis
                dataKey="time"
                type="number"
                scale="time"
                domain={xDomain}
                tickFormatter={(t) =>
                  format(new Date(t), wideRange ? 'MMM d' : 'HH:mm')
                }
              />
              <YAxis
                width={Y_AXIS_WIDTH}
                domain={['auto', 'auto']}
                tickFormatter={(v) => `${v.toFixed(1)}°`}
              />
              <Tooltip content={<DoorTooltip wideRange={wideRange} />} />
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

      {/* Door rug strip (or the hidden-at-wide-zoom note). */}
      {points.length > 0 &&
        (doorLayerVisible(range) ? (
          showDoor ? (
            <div className="relative mt-1" style={{ height: 16 }}>
              <span
                className="absolute left-0 top-0 bottom-0 flex items-center justify-end pr-2 text-[10px] text-gray-400 select-none"
                style={{ width: Y_AXIS_WIDTH }}
              >
                Door
              </span>
              <ResponsiveContainer width="100%" height={16}>
                <LineChart data={telPoints} margin={RUG_MARGIN}>
                  <XAxis
                    dataKey="time"
                    type="number"
                    scale="time"
                    domain={xDomain}
                    hide
                  />
                  {/* Space-reserving invisible YAxis so the rug's left gutter
                      matches the temperature chart's YAxis width. */}
                  <YAxis
                    width={Y_AXIS_WIDTH}
                    domain={[0, 1]}
                    tick={false}
                    axisLine={false}
                    tickLine={false}
                  />
                  {/* Gray "closed" baseline across the whole range… */}
                  <ReferenceArea
                    x1={xDomain[0]}
                    x2={xDomain[1]}
                    y1={0}
                    y2={1}
                    fill={DOOR_CLOSED_COLOR}
                    fillOpacity={1}
                    strokeOpacity={0}
                  />
                  {/* …then solid amber over each door-open interval. */}
                  {doorIntervals.map((iv) => (
                    <ReferenceArea
                      key={`rug-${iv.x1}`}
                      x1={iv.x1}
                      x2={iv.x2}
                      y1={0}
                      y2={1}
                      fill={DOOR_OPEN_COLOR}
                      fillOpacity={1}
                      strokeOpacity={0}
                    />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : null
        ) : (
          <div className="mt-2 text-xs text-gray-400">
            Door activity available at 7d or shorter range
          </div>
        ))}
    </div>
  );
}

// Group consecutive door_open===true samples into contiguous [x1, x2]
// intervals. The trailing edge extends to the next sample's timestamp (or one
// inferred step past the last sample) so even a single open sample renders as a
// visible band rather than a zero-width sliver.
function computeDoorIntervals(
  tel: { time: number; door: boolean | null }[],
): DoorInterval[] {
  const n = tel.length;
  if (n === 0) return [];
  const step = inferStep(tel.map((t) => t.time));
  const intervals: DoorInterval[] = [];
  let i = 0;
  while (i < n) {
    if (tel[i].door === true) {
      const x1 = tel[i].time;
      let j = i;
      while (j < n && tel[j].door === true) j++;
      const x2 = j < n ? tel[j].time : tel[j - 1].time + step;
      intervals.push({ x1, x2 });
      i = j;
    } else {
      i++;
    }
  }
  return intervals;
}

// Smallest positive gap between consecutive timestamps ≈ the bucket width.
function inferStep(times: number[]): number {
  let step = Infinity;
  for (let i = 1; i < times.length; i++) {
    const d = times[i] - times[i - 1];
    if (d > 0 && d < step) step = d;
  }
  return Number.isFinite(step) ? step : 60_000;
}

function computeDomain(times: number[]): [number, number] {
  if (times.length === 0) return [0, 1];
  let min = times[0];
  let max = times[0];
  for (const t of times) {
    if (t < min) min = t;
    if (t > max) max = t;
  }
  return [min, max];
}

function DoorTooltip({
  active,
  payload,
  wideRange,
}: TooltipProps<number, string> & { wideRange: boolean }) {
  if (!active || !payload || payload.length === 0) return null;
  const p = payload[0].payload as TempPoint;
  const doorLabel =
    p.door === null || p.door === undefined
      ? '—'
      : p.door
        ? 'open'
        : 'closed';
  return (
    <div className="bg-white border border-gray-200 rounded px-2 py-1 text-xs shadow">
      {format(new Date(p.time), wideRange ? 'MMM d, HH:mm' : 'HH:mm')} —{' '}
      {p.temperature.toFixed(1)}°C — Door: {doorLabel}
    </div>
  );
}
