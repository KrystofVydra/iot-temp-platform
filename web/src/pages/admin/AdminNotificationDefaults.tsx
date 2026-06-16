import { NotificationKindCard } from '../../components/NotificationKindCard';
import {
  useAdminKindDefaults,
  useAdminUpdateKindDefault,
} from '../../lib/hooks';
import type { KindDefault } from '../../lib/types';

export function AdminNotificationDefaults() {
  const { data, isLoading, error } = useAdminKindDefaults();
  const update = useAdminUpdateKindDefault();

  if (isLoading) return <div className="text-sm text-gray-500">Loading…</div>;
  if (error)
    return (
      <div className="text-red-600">
        Error: {(error as Error).message}
      </div>
    );
  if (!data) return null;

  const grouped = group(data);

  return (
    <div>
      <h1 className="text-2xl font-bold mb-2">Notification defaults</h1>
      <div className="bg-yellow-50 border border-yellow-200 rounded p-3 text-sm text-yellow-900 mb-6">
        These are the global defaults applied to new users. Existing users
        keep their customised settings.
      </div>

      {(['critical', 'alert'] as const).map((sev) => (
        <section key={sev} className="mb-8">
          <h2 className="font-semibold text-gray-700 mb-3 uppercase text-xs tracking-wide">
            {sev}
          </h2>
          <div className="grid gap-3">
            {grouped[sev].map((d) => (
              <NotificationKindCard
                key={d.kind}
                kind={d.kind}
                severity={d.severity}
                scope={d.scope}
                description={d.description}
                enabled={d.enabled_default}
                thresholds={d.thresholds}
                saving={update.isPending}
                enabledLabel="Enabled by default for new users"
                onSave={async (patch) => {
                  await update.mutateAsync({
                    kind: d.kind,
                    patch: {
                      enabled_default: patch.enabled,
                      thresholds: patch.thresholds,
                    },
                  });
                }}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function group(
  defaults: KindDefault[],
): Record<'critical' | 'alert', KindDefault[]> {
  const critical: KindDefault[] = [];
  const alert: KindDefault[] = [];
  for (const d of defaults) {
    if (d.severity === 'critical') critical.push(d);
    else alert.push(d);
  }
  const byConfigurability = (a: KindDefault, b: KindDefault) => {
    const ah = Object.keys(a.thresholds).length > 0 ? 0 : 1;
    const bh = Object.keys(b.thresholds).length > 0 ? 0 : 1;
    if (ah !== bh) return ah - bh;
    return a.kind.localeCompare(b.kind);
  };
  critical.sort(byConfigurability);
  alert.sort(byConfigurability);
  return { critical, alert };
}
