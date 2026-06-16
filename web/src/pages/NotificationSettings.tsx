import { NotificationKindCard } from '../components/NotificationKindCard';
import {
  useMyNotificationSettings,
  useUpdateMyNotificationSetting,
} from '../lib/hooks';
import type { NotificationSetting } from '../lib/types';

export function NotificationSettings() {
  const { data, isLoading, error } = useMyNotificationSettings();
  const update = useUpdateMyNotificationSetting();

  if (isLoading) return <div className="text-sm text-gray-500">Loading…</div>;
  if (error)
    return (
      <div className="text-red-600">
        Error: {(error as Error).message}
      </div>
    );
  if (!data) return null;

  const grouped = groupBySeverity(data);

  return (
    <div>
      <h1 className="text-2xl font-bold mb-2">Notification preferences</h1>
      <p className="text-sm text-gray-500 mb-6">
        Critical notifications surface as red badges. Alerts are
        informational and shown in yellow. Disable any kind to stop
        receiving notifications for it.
      </p>

      {(['critical', 'alert'] as const).map((sev) => (
        <section key={sev} className="mb-8">
          <h2 className="font-semibold text-gray-700 mb-3 uppercase text-xs tracking-wide">
            {sev}
          </h2>
          <div className="grid gap-3">
            {grouped[sev].map((s) => (
              <NotificationKindCard
                key={s.kind}
                kind={s.kind}
                severity={s.severity}
                scope={s.scope}
                description={s.description}
                enabled={s.enabled}
                thresholds={s.thresholds}
                saving={update.isPending}
                onSave={async (patch) => {
                  await update.mutateAsync({ kind: s.kind, patch });
                }}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function groupBySeverity(
  settings: NotificationSetting[],
): Record<'critical' | 'alert', NotificationSetting[]> {
  const critical: NotificationSetting[] = [];
  const alert: NotificationSetting[] = [];
  for (const s of settings) {
    if (s.severity === 'critical') critical.push(s);
    else alert.push(s);
  }
  // Within each group, configurable kinds first, then bare-flag kinds.
  const byConfigurability = (
    a: NotificationSetting,
    b: NotificationSetting,
  ) => {
    const ah = Object.keys(a.thresholds).length > 0 ? 0 : 1;
    const bh = Object.keys(b.thresholds).length > 0 ? 0 : 1;
    if (ah !== bh) return ah - bh;
    return a.kind.localeCompare(b.kind);
  };
  critical.sort(byConfigurability);
  alert.sort(byConfigurability);
  return { critical, alert };
}
