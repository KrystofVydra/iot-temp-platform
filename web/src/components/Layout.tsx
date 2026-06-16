import { Link, Outlet } from 'react-router-dom';
import { useAuth } from './AuthGate';
import { useUnreadCount } from '../lib/hooks';

function BellIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="w-5 h-5"
      aria-hidden="true"
    >
      <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
      <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
    </svg>
  );
}

function NotificationBell() {
  const { data } = useUnreadCount();
  const count = data?.count ?? 0;
  return (
    <Link
      to="/notifications"
      className="relative text-gray-600 hover:text-gray-900"
      aria-label={`Notifications${count > 0 ? ` (${count} unread)` : ''}`}
    >
      <BellIcon />
      {count > 0 && (
        <span className="absolute -top-1 -right-1 bg-red-600 text-white text-[10px] leading-none px-1.5 py-0.5 rounded-full font-medium">
          {count > 99 ? '99+' : count}
        </span>
      )}
    </Link>
  );
}

export function Layout() {
  const { user, logout } = useAuth();

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white shadow-sm border-b">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
          <Link to="/" className="text-lg font-semibold">
            IoT Temperature Platform
          </Link>
          <div className="flex items-center gap-4 text-sm">
            {user && <span className="text-gray-600">{user.display_name}</span>}
            {user && <NotificationBell />}
            <Link
              to="/settings/notifications"
              className="text-gray-600 hover:text-gray-900"
            >
              Settings
            </Link>
            {user?.is_admin && (
              <Link to="/admin" className="text-gray-600 hover:text-gray-900">
                Admin
              </Link>
            )}
            <button
              onClick={() => {
                void logout();
              }}
              className="text-gray-600 hover:text-gray-900"
            >
              Logout
            </button>
          </div>
        </div>
      </header>
      <main className="max-w-6xl mx-auto px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
