import { QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { AuthProvider, RequireAuth } from './components/AuthGate';
import { Layout } from './components/Layout';
import { ApiError } from './lib/api';
import { Dashboard } from './pages/Dashboard';
import { DeviceDetail } from './pages/DeviceDetail';
import { ForgotPassword } from './pages/ForgotPassword';
import { Login } from './pages/Login';
import { SetPassword } from './pages/SetPassword';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (failureCount, error) => {
        // Don't waste retries on auth failures — AuthProvider will redirect.
        if (error instanceof ApiError && error.status === 401) return false;
        return failureCount < 1;
      },
      refetchOnWindowFocus: false,
    },
  },
  queryCache: new QueryCache({
    onError: (error) => {
      // Any query 401 → kick the user back to /login. Hard navigation drops
      // any stale cached data along with the page state, so we don't need to
      // imperatively reset queryClient.
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
              <Route path="/devices/:id" element={<DeviceDetail />} />
            </Route>
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

export default App;
