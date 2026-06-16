import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { formatDistanceToNow } from 'date-fns';
import {
  useAdminKindDefaults,
  useAdminNotifications,
} from '../../lib/hooks';
import type {
  AdminNotification,
  NotificationSeverity,
  NotificationStatusFilter,
} from '../../lib/types';

const PAGE_SIZE = 50;

const STATUS_CHOICES: { value: NotificationStatusFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'active', label: 'Active' },
  { value: 'resolved', label: 'Resolved' },
];

const SEVERITY_CHOICES: {
  value: NotificationSeverity | null;
  label: string;
}[] = [
  { value: null, label: 'All' },
  { value: 'critical', label: 'Critical' },
  { value: 'alert', label: 'Alert' },
];

export function AdminNotifications() {
  const [emailInput, setEmailInput] = useState('');
  const [email, setEmail] = useState('');
  const [status, setStatus] = useState<NotificationStatusFilter>('all');
  const [severity, setSeverity] = useState<NotificationSeverity | null>(null);
  const [kind, setKind] = useState<string>('');
  const [page, setPage] = useState(0);

  // Debounce the email substring search 300ms before triggering the query.
  useEffect(() => {
    const t = setTimeout(() => {
      setEmail(emailInput);
      setPage(0);
    }, 300);
    return () => clearTimeout(t);
  }, [emailInput]);

  // Reset to page 0 whenever any other filter changes.
  useEffect(() => {
    setPage(0);
  }, [status, severity, kind]);

  const kindDefaults = useAdminKindDefaults();
  const { data, isLoading, error } = useAdminNotifications({
    user_email: email || undefined,
    status,
    severity: severity ?? undefined,
    kind: kind || undefined,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  });

  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-bold">All notifications</h1>
        <div className="text-sm text-gray-500">
          {total.toLocaleString()} matching
        </div>
      </div>

      <div className="bg-white rounded-lg shadow-sm p-3 mb-4 space-y-3">
        <input
          type="text"
          placeholder="Filter by user email (substring)…"
          value={emailInput}
          onChange={(e) => setEmailInput(e.target.value)}
          className="w-full px-3 py-2 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <div className="flex flex-wrap items-center gap-3">
          <ChipGroup
            label="Status"
            choices={STATUS_CHOICES}
            value={status}
            onChange={setStatus}
          />
          <ChipGroup
            label="Severity"
            choices={SEVERITY_CHOICES}
            value={severity}
            onChange={setSeverity}
          />
          <label className="flex items-center gap-2 text-sm">
            <span className="text-gray-600">Kind:</span>
            <select
              value={kind}
              onChange={(e) => setKind(e.target.value)}
              className="px-2 py-1 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">All kinds</option>
              {kindDefaults.data?.map((k) => (
                <option key={k.kind} value={k.kind} title={k.description}>
                  {k.kind}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {isLoading && <div className="text-sm text-gray-500">Loading…</div>}
      {error && (
        <div className="text-sm text-red-600">
          Error: {(error as Error).message}
        </div>
      )}

      {data && data.notifications.length === 0 && !isLoading && (
        <div className="text-sm text-gray-500">No notifications match.</div>
      )}

      {data && data.notifications.length > 0 && (
        <div className="bg-white rounded-lg shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left">
              <tr>
                <th className="px-3 py-2">Severity</th>
                <th className="px-3 py-2">Kind</th>
                <th className="px-3 py-2">User</th>
                <th className="px-3 py-2">Subject</th>
                <th className="px-3 py-2">Summary</th>
                <th className="px-3 py-2">Opened</th>
                <th className="px-3 py-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {data.notifications.map((n) => (
                <NotificationRow
                  key={n.id}
                  notification={n}
                  kindDescription={
                    kindDefaults.data?.find((k) => k.kind === n.kind)?.description
                  }
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data && total > PAGE_SIZE && (
        <div className="mt-4 flex items-center justify-between text-sm">
          <button
            type="button"
            disabled={page === 0}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            className="px-3 py-1 bg-gray-100 hover:bg-gray-200 disabled:opacity-50 rounded"
          >
            ← Prev
          </button>
          <div className="text-gray-500">
            Page {page + 1} of {totalPages}
          </div>
          <button
            type="button"
            disabled={page + 1 >= totalPages}
            onClick={() => setPage((p) => p + 1)}
            className="px-3 py-1 bg-gray-100 hover:bg-gray-200 disabled:opacity-50 rounded"
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
}

type ChipGroupProps<T> = {
  label: string;
  choices: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
};

function ChipGroup<T>({ label, choices, value, onChange }: ChipGroupProps<T>) {
  return (
    <div className="flex items-center gap-1">
      <span className="text-gray-600 text-sm mr-1">{label}:</span>
      {choices.map((c) => {
        const active = c.value === value;
        return (
          <button
            key={c.label}
            type="button"
            onClick={() => onChange(c.value)}
            className={`px-2.5 py-0.5 rounded text-xs ${
              active
                ? 'bg-blue-600 text-white'
                : 'bg-gray-100 hover:bg-gray-200'
            }`}
          >
            {c.label}
          </button>
        );
      })}
    </div>
  );
}

function SeverityBadge({ severity }: { severity: NotificationSeverity }) {
  const cls =
    severity === 'critical'
      ? 'bg-red-100 text-red-700'
      : 'bg-yellow-100 text-yellow-700';
  return (
    <span className={`text-xs px-2 py-0.5 rounded font-medium uppercase ${cls}`}>
      {severity}
    </span>
  );
}

function TestBadge() {
  return (
    <span className="ml-1 text-[10px] px-1.5 py-0.5 rounded bg-gray-500 text-white font-medium uppercase tracking-wide">
      Test
    </span>
  );
}

function NotificationRow({
  notification,
  kindDescription,
}: {
  notification: AdminNotification;
  kindDescription?: string;
}) {
  const isTest = notification.details?.is_test === true;
  const subjectTarget = subjectLink(notification);
  const resolved = notification.resolved_at !== null;

  return (
    <tr className="border-t">
      <td className="px-3 py-2 whitespace-nowrap">
        <SeverityBadge severity={notification.severity} />
        {isTest && <TestBadge />}
      </td>
      <td className="px-3 py-2 text-xs text-gray-700" title={kindDescription}>
        {notification.kind}
      </td>
      <td className="px-3 py-2 text-xs">
        <Link
          to={`/admin/users/${notification.user.id}`}
          className="text-blue-600 hover:underline"
        >
          {notification.user.email}
        </Link>
      </td>
      <td className="px-3 py-2 text-xs text-gray-700">
        {subjectTarget ? (
          <Link
            to={subjectTarget.href}
            className="text-blue-600 hover:underline"
          >
            {notification.subject_name || subjectTarget.label}
          </Link>
        ) : (
          notification.subject_name || '—'
        )}
      </td>
      <td className="px-3 py-2 text-sm text-gray-900">
        {notification.summary}
      </td>
      <td className="px-3 py-2 text-xs text-gray-500 whitespace-nowrap">
        {formatDistanceToNow(new Date(notification.opened_at), {
          addSuffix: true,
        })}
      </td>
      <td className="px-3 py-2 whitespace-nowrap">
        {resolved ? (
          <span
            className="text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-600"
            title={
              notification.resolved_at
                ? `Resolved ${formatDistanceToNow(new Date(notification.resolved_at), {
                    addSuffix: true,
                  })}`
                : undefined
            }
          >
            Resolved
          </span>
        ) : (
          <span className="text-xs px-2 py-0.5 rounded bg-green-100 text-green-700">
            Active
          </span>
        )}
      </td>
    </tr>
  );
}

function subjectLink(
  n: AdminNotification,
): { href: string; label: string } | null {
  if (n.controller_id !== null) {
    return {
      href: `/admin/controllers/${n.controller_id}`,
      label: n.subject_name ?? 'Controller',
    };
  }
  if (n.gateway_id !== null) {
    return {
      href: `/admin/gateways/${n.gateway_id}`,
      label: n.subject_name ?? 'Gateway',
    };
  }
  return null;
}
