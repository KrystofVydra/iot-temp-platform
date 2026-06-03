import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { formatDistanceToNow } from 'date-fns';
import { AddUserModal } from '../../components/admin/AddUserModal';
import { useAdminUsers } from '../../lib/hooks';
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
  const navigate = useNavigate();
  const { data: users, isLoading, error } = useAdminUsers();
  const [showAdd, setShowAdd] = useState(false);

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
              </tr>
            </thead>
            <tbody>
              {users.map((u) => {
                const status = statusOf(u);
                return (
                  <tr
                    key={u.id}
                    onClick={() => navigate(`/admin/users/${u.id}`)}
                    className="border-t hover:bg-gray-50 cursor-pointer"
                  >
                    <td className="px-4 py-2">
                      {u.email}
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
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <AddUserModal open={showAdd} onClose={() => setShowAdd(false)} />
    </div>
  );
}
