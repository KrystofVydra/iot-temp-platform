import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../components/AuthGate';
import { ApiError, postJson } from '../lib/api';

type Mode = 'invitation' | 'reset';

export function SetPassword() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { refresh } = useAuth();

  const token = params.get('token') ?? '';
  const mode: Mode = params.get('mode') === 'invitation' ? 'invitation' : 'reset';

  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const passwordTooShort = password.length > 0 && password.length < 8;
  const mismatch = confirm.length > 0 && password !== confirm;
  const canSubmit =
    token.length > 0 && password.length >= 8 && password === confirm && !submitting;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setError(null);
    setSubmitting(true);
    try {
      if (mode === 'invitation') {
        await postJson('/auth/accept-invitation', { token, password });
        await refresh();
        navigate('/', { replace: true });
      } else {
        await postJson('/auth/reset-password', { token, new_password: password });
        navigate('/login', {
          replace: true,
          state: { notice: 'Password updated. Please log in.' },
        });
      }
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.status === 400 ? 'Link is invalid or expired.' : err.message);
      } else {
        setError('Unexpected error. Try again.');
      }
    } finally {
      setSubmitting(false);
    }
  };

  if (!token) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="bg-white p-6 rounded-lg shadow-md w-full max-w-md space-y-4">
          <h1 className="text-xl font-semibold">Missing token</h1>
          <p className="text-sm text-gray-600">
            This page requires a valid invitation or reset link.
          </p>
          <Link to="/login" className="text-sm text-blue-600 hover:underline">
            Back to login
          </Link>
        </div>
      </div>
    );
  }

  const heading = mode === 'invitation' ? 'Set your password' : 'Choose a new password';
  const buttonLabel =
    mode === 'invitation' ? 'Set password and sign in' : 'Update password';

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <form
        onSubmit={handleSubmit}
        className="bg-white p-6 rounded-lg shadow-md w-full max-w-md space-y-4"
      >
        <h1 className="text-xl font-semibold">{heading}</h1>
        {error && <div className="text-sm text-red-600">{error}</div>}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1" htmlFor="new-password">
            New password
          </label>
          <input
            id="new-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoFocus
            minLength={8}
            className="w-full px-3 py-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          {passwordTooShort && (
            <div className="text-xs text-red-600 mt-1">Must be at least 8 characters.</div>
          )}
        </div>
        <div>
          <label
            className="block text-sm font-medium text-gray-700 mb-1"
            htmlFor="confirm-password"
          >
            Confirm password
          </label>
          <input
            id="confirm-password"
            type="password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            required
            className="w-full px-3 py-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          {mismatch && (
            <div className="text-xs text-red-600 mt-1">Passwords do not match.</div>
          )}
        </div>
        <button
          type="submit"
          disabled={!canSubmit}
          className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white py-2 rounded font-medium"
        >
          {submitting ? 'Saving…' : buttonLabel}
        </button>
      </form>
    </div>
  );
}
