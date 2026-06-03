import { useState } from 'react';
import { Link } from 'react-router-dom';
import { formatDistanceToNow } from 'date-fns';
import { useAuth } from '../../components/AuthGate';
import { AddUserModal } from '../../components/admin/AddUserModal';
import { ResetLinkModal } from '../../components/admin/ResetLinkModal';
import {
  useAdminUsers,
  useDeactivateUser,
  useDeleteUser,
  useReactivateUser,
} from '../../lib/hooks';
import type { UserAdmin } from '../../lib/types';

type Status = 'active' | 'deactivated' | 'pending';

function statusOf(u: UserAdmin): Status {
  if (!u.is_active) return 'deactivated';
  if (!u.has_password) return 'pending';
  return 'active';
}

function StatusPill({ status }: { status: Status }) {
  const cls = {
    active: 'bg-green-100 text-green-700',
    deactivated: 'bg-gray-100 text-gray-600',
    pending: 'bg-yellow-100 text-yellow-700',
  }[status];
  const label = {
    active: 'Active',
    deactivated: 'Deactivated',
    pending: 'Pending invitation',
  }[status];
  return <span className={`text-xs px-2 py-1 rounded ${cls}`}>{label}</span>;
}

export function AdminUsers() {
  const { user: currentUser } = useAuth();
  const { data: users, isLoading, error } = useAdminUsers();
  const [showAdd, setShowAdd] = useState(false);
  const [resetForUserId, setResetForUserId] = useState<number | null>(null);

  const deactivate = useDeactivateUser();
  const reactivate = useReactivateUser();
  const del = useDeleteUser();

  const handleDelete = (u: UserAdmin) => {
    if (
      !window.confirm(
        `Delete ${u.email}? This drops all of their devices and readings.`,
      )
    )
      return;
    del.mutate(u.id);
  };

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h1 className="text-2xl font-bold">Users</h1>
        <button
          type="button"
          onClick={() => setShowAdd(true)}
          className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded text-sm font-medium"
        >
          + Add user
        </button>
      </div>

      {isLoading && <div className="text-sm text-gray-500">Loading…</div>}
      {error && (
        <div className="text-sm text-red-600">
          Error: {(error as Error).message}
        </div>
      )}

      {users && users.length === 0 && (
        <div className="text-sm text-gray-500">No users yet.</div>
      )}

      {users && users.length > 0 && (
        <div className="bg-white rounded-lg shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left">
              <tr>
                <th className="px-4 py-2">Email</th>
                <th className="px-4 py-2">Display Name</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2">Last Login</th>
                <th className="px-4 py-2">Created</th>
                <th className="px-4 py-2">Devices</th>
                <th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => {
                const isMe = currentUser?.id === u.id;
                const status = statusOf(u);
                return (
                  <tr key={u.id} className="border-t">
                    <td className="px-4 py-2">
                      <Link
                        to={`/admin/users/${u.id}`}
                        className="text-blue-600 hover:underline"
                      >
                        {u.email}
                      </Link>
                      {u.is_admin && (
                        <span className="ml-2 text-xs bg-purple-100 text-purple-700 px-2 py-0.5 rounded">
                          admin
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2">{u.display_name}</td>
                    <td className="px-4 py-2">
                      <StatusPill status={status} />
                    </td>
                    <td className="px-4 py-2 text-gray-600">
                      {u.last_login_at
                        ? formatDistanceToNow(new Date(u.last_login_at), {
                            addSuffix: true,
                          })
                        : 'Never'}
                    </td>
                    <td className="px-4 py-2 text-gray-600">
                      {formatDistanceToNow(new Date(u.created_at), {
                        addSuffix: true,
                      })}
                    </td>
                    <td className="px-4 py-2 text-gray-600">
                      {u.device_count}
                    </td>
                    <td className="px-4 py-2 text-right">
                      <details className="relative inline-block">
                        <summary className="cursor-pointer list-none text-gray-500 hover:text-gray-900 px-2 select-none">
                          ⋯
                        </summary>
                        <div className="absolute right-0 mt-1 bg-white shadow-md border rounded text-sm w-48 z-10">
                          <Link
                            to={`/admin/users/${u.id}`}
                            className="block px-3 py-2 hover:bg-gray-50"
                          >
                            View
                          </Link>
                          {u.has_password && (
                            <button
                              type="button"
                              onClick={() => setResetForUserId(u.id)}
                              className="block w-full text-left px-3 py-2 hover:bg-gray-50"
                            >
                              Send reset link
                            </button>
                          )}
                          {!isMe && u.is_active && (
                            <button
                              type="button"
                              onClick={() => deactivate.mutate(u.id)}
                              className="block w-full text-left px-3 py-2 hover:bg-gray-50"
                            >
                              Deactivate
                            </button>
                          )}
                          {!u.is_active && (
                            <button
                              type="button"
                              onClick={() => reactivate.mutate(u.id)}
                              className="block w-full text-left px-3 py-2 hover:bg-gray-50"
                            >
                              Reactivate
                            </button>
                          )}
                          {!isMe && (
                            <button
                              type="button"
                              onClick={() => handleDelete(u)}
                              className="block w-full text-left px-3 py-2 hover:bg-gray-50 text-red-600"
                            >
                              Delete
                            </button>
                          )}
                        </div>
                      </details>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <AddUserModal open={showAdd} onClose={() => setShowAdd(false)} />
      {resetForUserId !== null && (
        <ResetLinkModal
          userId={resetForUserId}
          open={true}
          onClose={() => setResetForUserId(null)}
        />
      )}
    </div>
  );
}
