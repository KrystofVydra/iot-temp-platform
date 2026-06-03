import { Link, Outlet } from 'react-router-dom';
import { useAuth } from './AuthGate';

export function Layout() {
  const { user, logout } = useAuth();

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white shadow-sm border-b">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
          <Link to="/" className="text-lg font-semibold">
            IoT Temperature Platform
          </Link>
          <div className="flex items-center gap-3 text-sm">
            {user && <span className="text-gray-600">{user.display_name}</span>}
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
