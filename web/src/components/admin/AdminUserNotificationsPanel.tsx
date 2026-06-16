import { useEffect, useState } from 'react';
import { NotificationKindCard } from '../NotificationKindCard';
import {
  useAdminFireTestNotification,
  useAdminKindDefaults,
  useAdminUpdateUserNotificationSetting,
  useAdminUserNotificationSettings,
} from '../../lib/hooks';
import type { NotificationSetting } from '../../lib/types';

type Props = { userId: number };

export function AdminUserNotificationsPanel({ userId }: Props) {
  const settings = useAdminUserNotificationSettings(userId);
  const update = useAdminUpdateUserNotificationSetting(userId);

  if (settings.isLoading)
    return <div className="text-sm text-gray-500">Loading settings…</div>;
  if (settings.error)
    return (
      <div className="text-sm text-red-600">
        Error: {(settings.error as Error).message}
      </div>
    );
  if (!settings.data) return null;

  const grouped = group(settings.data);

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-lg font-semibold">Notification settings</h2>
        <div className="text-xs text-gray-500">
          Editing on behalf of the user. Their UI shows the same values.
        </div>
      </div>

      {(['critical', 'alert'] as const).map((sev) => (
        <section key={sev} className="mb-6">
          <h3 className="font-semibold text-gray-700 mb-2 uppercase text-xs tracking-wide">
            {sev}
          </h3>
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

      <TestNotificationFireSection userId={userId} />
    </div>
  );
}

function group(
  settings: NotificationSetting[],
): Record<'critical' | 'alert', NotificationSetting[]> {
  const critical: NotificationSetting[] = [];
  const alert: NotificationSetting[] = [];
  for (const s of settings) {
    if (s.severity === 'critical') critical.push(s);
    else alert.push(s);
  }
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

function TestNotificationFireSection({ userId }: { userId: number }) {
  const kindDefaults = useAdminKindDefaults();
  const fire = useAdminFireTestNotification();
  const [selectedKind, setSelectedKind] = useState<string>('');
  const [feedback, setFeedback] = useState<
    { kind: 'ok' | 'err'; message: string } | null
  >(null);

  // Default to the first kind once defaults load.
  useEffect(() => {
    if (!selectedKind && kindDefaults.data && kindDefaults.data.length > 0) {
      setSelectedKind(kindDefaults.data[0].kind);
    }
  }, [kindDefaults.data, selectedKind]);

  useEffect(() => {
    if (feedback?.kind === 'ok') {
      const t = setTimeout(() => setFeedback(null), 4000);
      return () => clearTimeout(t);
    }
  }, [feedback]);

  const handleFire = async () => {
    setFeedback(null);
    if (!selectedKind) return;
    try {
      await fire.mutateAsync({ user_id: userId, kind: selectedKind });
      setFeedback({
        kind: 'ok',
        message: `Test notification fired. User will see it as ${selectedKind}.`,
      });
    } catch (e) {
      setFeedback({
        kind: 'err',
        message: (e as Error).message || 'Failed to fire test notification.',
      });
    }
  };

  return (
    <section className="mt-8 pt-6 border-t">
      <h3 className="text-lg font-semibold mb-2">Test notifications</h3>
      <p className="text-sm text-gray-500 mb-3">
        Fire a synthetic notification of any kind to verify the user sees it
        in their feed. Subject is the user's lowest-id entity of the
        required scope; the notification is tagged with{' '}
        <code className="bg-gray-100 px-1 rounded text-xs">is_test</code>.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={selectedKind}
          onChange={(e) => setSelectedKind(e.target.value)}
          className="px-2 py-1 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {kindDefaults.data?.map((k) => (
            <option key={k.kind} value={k.kind}>
              {k.kind} ({k.severity}, {k.scope})
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={handleFire}
          disabled={!selectedKind || fire.isPending}
          className="px-3 py-1 text-sm bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white rounded"
        >
          {fire.isPending ? 'Firing…' : 'Fire test notification'}
        </button>
      </div>
      {feedback && (
        <div
          className={`mt-3 text-sm ${
            feedback.kind === 'ok' ? 'text-green-700' : 'text-red-600'
          }`}
        >
          {feedback.message}
        </div>
      )}
    </section>
  );
}
