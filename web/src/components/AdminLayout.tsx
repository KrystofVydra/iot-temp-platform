import { NavLink, Outlet } from 'react-router-dom';

const tabClass = ({ isActive }: { isActive: boolean }) =>
  `px-3 py-2 text-sm ${
    isActive
      ? 'font-semibold underline text-gray-900'
      : 'text-gray-600 hover:text-gray-900'
  }`;

export function AdminLayout() {
  return (
    <div>
      <nav className="border-b mb-6 flex gap-2" aria-label="Admin sections">
        <NavLink to="/admin/users" className={tabClass}>
          Users
        </NavLink>
        <NavLink to="/admin/gateways" className={tabClass}>
          Gateways
        </NavLink>
        <NavLink to="/admin/notifications" className={tabClass}>
          All notifications
        </NavLink>
        <NavLink to="/admin/notification-defaults" className={tabClass}>
          Notification defaults
        </NavLink>
      </nav>
      <Outlet />
    </div>
  );
}
