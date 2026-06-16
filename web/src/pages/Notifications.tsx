import { useState } from 'react';
import { Link } from 'react-router-dom';
import { formatDistanceToNow } from 'date-fns';
import {
  useMarkAllRead,
  useMarkRead,
  useMyNotifications,
} from '../lib/hooks';
import type {
  Notification,
  NotificationStatusFilter,
} from '../lib/types';

const FILTERS: { value: NotificationStatusFilter; label: string }[] = [
  { value: 'active', label: 'Active' },
  { value: 'all', label: 'All' },
  { value: 'resolved', label: 'Resolved' },
];

export function Notifications() {
  const [filter, setFilter] = useState<NotificationStatusFilter>('active');
  const { data, isLoading, error } = useMyNotifications({
    status: filter,
    limit: 100,
  });
  const markAllRead = useMarkAllRead();

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-bold">Notifications</h1>
        {(data?.unread ?? 0) > 0 && (
          <button
            type="button"
            onClick={() => markAllRead.mutate()}
            disabled={markAllRead.isPending}
            className="text-sm px-3 py-1 bg-gray-100 hover:bg-gray-200 rounded text-gray-700 disabled:opacity-50"
          >
            Mark all as read
          </button>
        )}
      </div>

      <div className="flex gap-2 mb-4">
        {FILTERS.map((f) => (
          <button
            key={f.value}
            type="button"
            onClick={() => setFilter(f.value)}
            className={`px-3 py-1 rounded text-sm ${
              filter === f.value
                ? 'bg-blue-600 text-white'
                : 'bg-gray-100 hover:bg-gray-200'
            }`}
          >
            {f.label}
            {f.value === 'active' && data ? ` (${data.active})` : ''}
          </button>
        ))}
      </div>

      {isLoading && <div className="text-sm text-gray-500">Loading…</div>}
      {error && (
        <div className="text-sm text-red-600">
          Error: {(error as Error).message}
        </div>
      )}

      {data && data.notifications.length === 0 && (
        <div className="text-sm text-gray-500">
          {filter === 'active'
            ? 'No active notifications.'
            : 'No notifications.'}
        </div>
      )}

      <ul className="space-y-2">
        {data?.notifications.map((n) => (
          <NotificationRow key={n.id} notification={n} />
        ))}
      </ul>
    </div>
  );
}

function SeverityBadge({ severity }: { severity: Notification['severity'] }) {
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

function NotificationRow({ notification }: { notification: Notification }) {
  const markRead = useMarkRead();
  const unread = notification.read_at === null;
  const resolved = notification.resolved_at !== null;
  const isTest = notification.details?.is_test === true;

  const handleClick = () => {
    if (unread) markRead.mutate(notification.id);
  };

  const target = subjectLink(notification);

  return (
    <li
      onClick={handleClick}
      className={`bg-white rounded-lg shadow-sm p-3 cursor-pointer transition ${
        unread ? 'ring-1 ring-blue-200' : ''
      }`}
    >
      <div className="flex items-start gap-3">
        <div className="flex flex-col items-center pt-1 gap-1">
          <SeverityBadge severity={notification.severity} />
          {isTest && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-500 text-white font-medium uppercase tracking-wide">
              Test
            </span>
          )}
          {unread && (
            <span
              className="mt-1 w-2 h-2 rounded-full bg-blue-600"
              aria-label="Unread"
            />
          )}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm text-gray-900">{notification.summary}</div>
          <div className="text-xs text-gray-500 mt-1 flex flex-wrap gap-x-2">
            {target && (
              <Link
                to={target.href}
                onClick={(e) => e.stopPropagation()}
                className="hover:underline text-blue-600"
              >
                {target.label}
              </Link>
            )}
            <span>
              opened{' '}
              {formatDistanceToNow(new Date(notification.opened_at), {
                addSuffix: true,
              })}
            </span>
            {resolved && notification.resolved_at && (
              <span>
                resolved{' '}
                {formatDistanceToNow(new Date(notification.resolved_at), {
                  addSuffix: true,
                })}
              </span>
            )}
          </div>
        </div>
      </div>
    </li>
  );
}

function subjectLink(
  n: Notification,
): { href: string; label: string } | null {
  // Prefer the most specific available target: node → controller → gateway.
  const name = n.subject_name ?? 'Unknown';
  if (n.controller_id !== null) {
    return { href: `/controllers/${n.controller_id}`, label: name };
  }
  // No user-facing gateway page — fall back to dashboard.
  if (n.gateway_id !== null) {
    return { href: '/', label: name };
  }
  return null;
}
