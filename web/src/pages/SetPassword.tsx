import { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../components/AuthGate';
import { ApiError, apiFetch, postJson } from '../lib/api';

type Mode = 'invitation' | 'reset';
type ValidationStatus = 'loading' | 'valid' | 'expired' | 'invalid';

export function SetPassword() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { refresh } = useAuth();

  const token = params.get('token') ?? '';
  const rawMode = params.get('mode');
  // Strict: only the exact values 'invitation' or 'reset' are accepted. An
  // unknown mode short-circuits to the invalid card without an API call.
  const mode: Mode | null =
    rawMode === 'invitation' || rawMode === 'reset' ? rawMode : null;

  const [status, setStatus] = useState<ValidationStatus>(
    mode === null ? 'invalid' : 'loading',
  );

  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Pre-validate the token server-side so the user sees the expired/invalid
  // state immediately instead of after typing a password.
  useEffect(() => {
    if (mode === null) return;
    let cancelled = false;

    const validate = async () => {
      try {
        const qs = new URLSearchParams({ token, kind: mode });
        await apiFetch(`/auth/validate-token?${qs.toString()}`);
        if (!cancelled) setStatus('valid');
      } catch (err) {
        if (cancelled) return;
        let reason: string | null = null;
        if (err instanceof ApiError) {
          try {
            const body: unknown = JSON.parse(err.message);
            if (typeof body === 'object' && body !== null && 'reason' in body) {
              const r = (body as { reason: unknown }).reason;
              if (typeof r === 'string') reason = r;
            }
          } catch {
            // body wasn't JSON; treat as invalid
          }
        }
        setStatus(reason === 'expired' ? 'expired' : 'invalid');
      }
    };

    void validate();
    return () => {
      cancelled = true;
    };
  }, [mode, token]);

  const passwordTooShort = password.length > 0 && password.length < 8;
  const mismatch = confirm.length > 0 && password !== confirm;
  const canSubmit =
    token.length > 0 && password.length >= 8 && password === confirm && !submitting;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit || mode === null) return;
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

  if (status === 'loading') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="bg-white p-6 rounded-lg shadow-md w-full max-w-md text-center">
          <p className="text-sm text-gray-500">Checking link…</p>
        </div>
      </div>
    );
  }

  if (status === 'expired') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="bg-white p-6 rounded-lg shadow-md w-full max-w-md space-y-4 text-center">
          <h1 className="text-xl font-semibold">Link expired</h1>
          <p className="text-sm text-gray-600">
            This link has expired. Ask your admin for a new one.
          </p>
          <Link to="/login" className="inline-block text-sm text-blue-600 hover:underline">
            Back to login &rarr;
          </Link>
        </div>
      </div>
    );
  }

  if (status === 'invalid' || mode === null) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="bg-white p-6 rounded-lg shadow-md w-full max-w-md space-y-4 text-center">
          <h1 className="text-xl font-semibold">Link not usable</h1>
          <p className="text-sm text-gray-600">
            This link is invalid or no longer usable. Ask your admin for a new one.
          </p>
          <Link to="/login" className="inline-block text-sm text-blue-600 hover:underline">
            Back to login &rarr;
          </Link>
        </div>
      </div>
    );
  }

  // status === 'valid', mode is Mode
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
