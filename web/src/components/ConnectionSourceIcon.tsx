import { format, isSameDay } from 'date-fns';

/**
 * Which link the gateway last reported on, from the MQTT payload's
 * `source` field: 0 = WiFi, 1 = LTE fallback, null = unknown (the gateway
 * hasn't reported since the feature landed).
 *
 * Offline wins over everything: a source value from a gateway we haven't
 * heard from in 5 minutes says nothing about how it's connected *now*, so
 * it renders grey rather than claiming a live link.
 */

const ONLINE_WINDOW_MS = 5 * 60_000;

const SOURCE_WIFI = 0;
const SOURCE_LTE = 1;

const SIZE_PX: Record<NonNullable<Props['size']>, number> = {
  sm: 14,
  md: 18,
  lg: 24,
};

type Props = {
  source: number | null;
  lastSeenAt: string | null;
  /** `gateway.last_source_changed_at` — drives the "since …" tooltip. */
  changedAt?: string | null;
  size?: 'sm' | 'md' | 'lg';
};

/** "14:32" for today, "Oct 19, 14:32" for anything older. */
function sinceLabel(changedAt: string | null | undefined): string | null {
  if (!changedAt) return null;
  const d = new Date(changedAt);
  if (Number.isNaN(d.getTime())) return null;
  return isSameDay(d, new Date()) ? format(d, 'HH:mm') : format(d, 'MMM d, HH:mm');
}

export function ConnectionSourceIcon({
  source,
  lastSeenAt,
  changedAt,
  size = 'sm',
}: Props) {
  const px = SIZE_PX[size];
  const online =
    !!lastSeenAt && Date.now() - new Date(lastSeenAt).getTime() < ONLINE_WINDOW_MS;

  if (!online) {
    return (
      <Icon
        px={px}
        className="text-gray-400"
        title="Gateway offline"
        shape={source === SOURCE_LTE ? 'lte' : 'wifi'}
      />
    );
  }

  const since = sinceLabel(changedAt);

  if (source === SOURCE_WIFI) {
    return (
      <Icon
        px={px}
        className="text-blue-500"
        title={since ? `WiFi since ${since}` : 'WiFi'}
        shape="wifi"
      />
    );
  }

  if (source === SOURCE_LTE) {
    return (
      <Icon
        px={px}
        // amber-500 is #f59e0b — the same amber as the door-open indicator.
        className="text-amber-500"
        title={
          since ? `LTE since ${since} (fallback)` : 'LTE (fallback)'
        }
        shape="lte"
      />
    );
  }

  return (
    <Icon
      px={px}
      className="text-gray-400"
      title="Connection source unknown"
      shape="unknown"
    />
  );
}

function Icon({
  px,
  className,
  title,
  shape,
}: {
  px: number;
  className: string;
  title: string;
  shape: 'wifi' | 'lte' | 'unknown';
}) {
  return (
    <span
      className={`inline-flex shrink-0 items-center ${className}`}
      title={title}
      role="img"
      aria-label={title}
    >
      <svg
        width={px}
        height={px}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        {shape === 'wifi' && (
          <>
            {/* Three arcs + the dot: the conventional WiFi fan. */}
            <path d="M2 8.5a16 16 0 0 1 20 0" />
            <path d="M5 12a11.5 11.5 0 0 1 14 0" />
            <path d="M8.5 15.5a7 7 0 0 1 7 0" />
            <circle cx="12" cy="19" r="1" fill="currentColor" stroke="none" />
          </>
        )}
        {shape === 'lte' && (
          <>
            {/* Cellular tower: mast, radiating arcs, splayed legs. */}
            <path d="M8 4.5a7 7 0 0 0 0 9" />
            <path d="M16 4.5a7 7 0 0 1 0 9" />
            <path d="M4.8 2a11.5 11.5 0 0 0 0 14" />
            <path d="M19.2 2a11.5 11.5 0 0 1 0 14" />
            <circle cx="12" cy="9" r="1.4" fill="currentColor" stroke="none" />
            <path d="M12 10.5V22" />
            <path d="M9 22l3-7 3 7" />
          </>
        )}
        {shape === 'unknown' && (
          <circle cx="12" cy="12" r="4" fill="currentColor" stroke="none" />
        )}
      </svg>
    </span>
  );
}
