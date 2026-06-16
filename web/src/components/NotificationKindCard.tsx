import { useEffect, useState } from 'react';
import type { NotificationSeverity, NotificationScope } from '../lib/types';

const KIND_LABEL: Record<string, string> = {
  temp_safe: 'Temperature — safe range',
  temp_preferred: 'Temperature — preferred range',
  temp_drift: 'Temperature drift',
  door_open: 'Door open too long',
  controller_offline: 'Controller offline',
  gateway_offline: 'Gateway offline',
  multi_controller_offline: 'Multiple controllers offline',
  battery_critical: 'Battery critically low',
  battery_low: 'Battery low',
  node_error_single: 'Node sensor error',
  node_error_cumulative: 'Multiple node errors',
};

type ThresholdShape = {
  label: string;
  suffix: string;
  step: number;
  min?: number;
  max?: number;
};

const THRESHOLD_SHAPE: Record<string, ThresholdShape> = {
  safe_min: { label: 'Safe min', suffix: '°C', step: 0.1, min: -50, max: 50 },
  safe_max: { label: 'Safe max', suffix: '°C', step: 0.1, min: -50, max: 50 },
  preferred_min: {
    label: 'Preferred min',
    suffix: '°C',
    step: 0.1,
    min: -50,
    max: 50,
  },
  preferred_max: {
    label: 'Preferred max',
    suffix: '°C',
    step: 0.1,
    min: -50,
    max: 50,
  },
  drift_c: { label: 'Δ', suffix: '°C', step: 0.1, min: 0.1, max: 50 },
  drift_minutes: { label: 'within', suffix: 'min', step: 1, min: 1, max: 1440 },
  max_open_minutes: { label: 'Threshold', suffix: 'min', step: 1, min: 1, max: 1440 },
  offline_minutes: { label: 'Threshold', suffix: 'min', step: 1, min: 1, max: 1440 },
  critical_pct: { label: 'Critical at', suffix: '%', step: 1, min: 0, max: 100 },
  low_pct: { label: 'Low at', suffix: '%', step: 1, min: 0, max: 100 },
};

const PAIR_RULES: Record<string, [string, string]> = {
  temp_safe: ['safe_min', 'safe_max'],
  temp_preferred: ['preferred_min', 'preferred_max'],
};

type Props = {
  kind: string;
  severity: NotificationSeverity;
  scope: NotificationScope;
  description: string;
  enabled: boolean;
  thresholds: Record<string, number>;
  saving: boolean;
  // Label of the toggle row — defaults to "Enabled / Disabled". Admin variant
  // overrides to "Enabled by default for new users".
  enabledLabel?: string;
  onSave: (patch: {
    enabled: boolean;
    thresholds: Record<string, number>;
  }) => Promise<void> | void;
};

export function NotificationKindCard({
  kind,
  severity,
  scope,
  description,
  enabled,
  thresholds,
  saving,
  enabledLabel,
  onSave,
}: Props) {
  const [localEnabled, setLocalEnabled] = useState(enabled);
  const [localThresholds, setLocalThresholds] = useState<Record<string, string>>(
    Object.fromEntries(
      Object.entries(thresholds).map(([k, v]) => [k, String(v)]),
    ),
  );
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    setLocalEnabled(enabled);
    setLocalThresholds(
      Object.fromEntries(
        Object.entries(thresholds).map(([k, v]) => [k, String(v)]),
      ),
    );
    // Reset when the source values change (e.g. after a refetch).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, JSON.stringify(thresholds)]);

  useEffect(() => {
    if (savedAt === null) return;
    const t = setTimeout(() => setSavedAt(null), 1500);
    return () => clearTimeout(t);
  }, [savedAt]);

  const dirty =
    localEnabled !== enabled ||
    Object.entries(localThresholds).some(
      ([k, v]) => Number(v) !== thresholds[k],
    );

  const handleSave = async () => {
    setError(null);
    const parsed: Record<string, number> = {};
    for (const [k, raw] of Object.entries(localThresholds)) {
      const num = Number(raw);
      if (raw === '' || !Number.isFinite(num)) {
        setError(`${THRESHOLD_SHAPE[k]?.label ?? k} must be a number.`);
        return;
      }
      const shape = THRESHOLD_SHAPE[k];
      if (shape) {
        if (shape.min !== undefined && num < shape.min) {
          setError(`${shape.label} must be ≥ ${shape.min}.`);
          return;
        }
        if (shape.max !== undefined && num > shape.max) {
          setError(`${shape.label} must be ≤ ${shape.max}.`);
          return;
        }
      }
      parsed[k] = num;
    }
    const pair = PAIR_RULES[kind];
    if (pair && parsed[pair[0]] !== undefined && parsed[pair[1]] !== undefined) {
      if (parsed[pair[0]] >= parsed[pair[1]]) {
        setError(`${pair[0]} must be less than ${pair[1]}.`);
        return;
      }
    }
    try {
      await onSave({ enabled: localEnabled, thresholds: parsed });
      setSavedAt(Date.now());
    } catch (e) {
      setError((e as Error).message || 'Save failed.');
    }
  };

  return (
    <div className="bg-white rounded-lg shadow-sm p-4">
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-semibold">
              {KIND_LABEL[kind] ?? kind}
            </span>
            <SeverityPill severity={severity} />
            <span className="text-xs text-gray-400">{scope}</span>
          </div>
          <p className="text-sm text-gray-500 mt-1">{description}</p>
        </div>
        <label className="flex items-center gap-2 shrink-0 text-sm">
          <input
            type="checkbox"
            checked={localEnabled}
            onChange={(e) => setLocalEnabled(e.target.checked)}
          />
          <span>{enabledLabel ?? (localEnabled ? 'Enabled' : 'Disabled')}</span>
        </label>
      </div>

      {Object.keys(localThresholds).length > 0 && (
        <div className="grid sm:grid-cols-2 gap-3 mt-3 pt-3 border-t">
          {Object.entries(localThresholds).map(([k, v]) => {
            const shape = THRESHOLD_SHAPE[k];
            return (
              <label key={k} className="text-sm">
                <span className="block text-gray-700 mb-1">
                  {shape?.label ?? k}
                </span>
                <span className="flex items-center gap-1">
                  <input
                    type="number"
                    value={v}
                    onChange={(e) =>
                      setLocalThresholds({
                        ...localThresholds,
                        [k]: e.target.value,
                      })
                    }
                    step={shape?.step ?? 1}
                    min={shape?.min}
                    max={shape?.max}
                    className="flex-1 px-2 py-1 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                  {shape?.suffix && (
                    <span className="text-gray-500 text-xs">{shape.suffix}</span>
                  )}
                </span>
              </label>
            );
          })}
        </div>
      )}

      {error && <div className="text-sm text-red-600 mt-3">{error}</div>}

      <div className="flex items-center gap-3 mt-3 pt-3 border-t text-sm">
        <button
          type="button"
          onClick={handleSave}
          disabled={!dirty || saving}
          className="px-3 py-1 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white rounded"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
        {savedAt !== null && (
          <span className="text-green-700 text-xs">Saved.</span>
        )}
      </div>
    </div>
  );
}

function SeverityPill({ severity }: { severity: NotificationSeverity }) {
  const cls =
    severity === 'critical'
      ? 'bg-red-100 text-red-700'
      : 'bg-yellow-100 text-yellow-700';
  return (
    <span
      className={`text-xs px-2 py-0.5 rounded font-medium uppercase ${cls}`}
    >
      {severity}
    </span>
  );
}
