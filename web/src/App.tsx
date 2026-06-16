import { QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AdminLayout } from './components/AdminLayout';
import { AuthProvider, RequireAdmin, RequireAuth } from './components/AuthGate';
import { Layout } from './components/Layout';
import { ApiError } from './lib/api';
import { ControllerDetail } from './pages/ControllerDetail';
import { Dashboard } from './pages/Dashboard';
import { ForgotPassword } from './pages/ForgotPassword';
import { Login } from './pages/Login';
import { NotFound } from './pages/NotFound';
import { SetPassword } from './pages/SetPassword';
import { AdminControllerDetail } from './pages/admin/AdminControllerDetail';
import { AdminGatewayDetail } from './pages/admin/AdminGatewayDetail';
import { AdminGateways } from './pages/admin/AdminGateways';
import { AdminUserDetail } from './pages/admin/AdminUserDetail';
import { AdminUsers } from './pages/admin/AdminUsers';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (failureCount, error) => {
        // Don't waste retries on auth/permission failures. 403 from admin
        // endpoints is handled by RequireAdmin; 401 redirects via onError.
        if (
          error instanceof ApiError &&
          (error.status === 401 || error.status === 403)
        ) {
          return false;
        }
        return failureCount < 1;
      },
      refetchOnWindowFocus: false,
    },
  },
  queryCache: new QueryCache({
    onError: (error) => {
      // Only 401 redirects — 403 is just "not allowed for this user" and
      // should be surfaced inline by the page, not bounce them to /login.
      if (
        error instanceof ApiError &&
        error.status === 401 &&
        window.location.pathname !== '/login'
      ) {
        window.location.href = '/login';
      }
    },
  }),
});

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/forgot-password" element={<ForgotPassword />} />
            <Route path="/set-password" element={<SetPassword />} />
            <Route
              element={
                <RequireAuth>
                  <Layout />
                </RequireAuth>
              }
            >
              <Route path="/" element={<Dashboard />} />
              <Route path="/controllers/:id" element={<ControllerDetail />} />
              <Route
                path="/admin"
                element={
                  <RequireAdmin>
                    <AdminLayout />
                  </RequireAdmin>
                }
              >
                <Route index element={<Navigate to="/admin/users" replace />} />
                <Route path="users" element={<AdminUsers />} />
                <Route path="users/:id" element={<AdminUserDetail />} />
                <Route path="gateways" element={<AdminGateways />} />
                <Route path="gateways/:id" element={<AdminGatewayDetail />} />
                <Route
                  path="controllers/:id"
                  element={<AdminControllerDetail />}
                />
              </Route>
            </Route>
            <Route path="*" element={<NotFound />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

export default App;
