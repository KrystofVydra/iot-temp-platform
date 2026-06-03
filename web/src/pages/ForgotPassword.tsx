import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { postJson } from '../lib/api';

type ForgotResp = { reset_url: string | null };

export function ForgotPassword() {
  const [email, setEmail] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [resetUrl, setResetUrl] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  // Reset the "Copied!" badge after 2s.
  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(t);
  }, [copied]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const resp = await postJson<ForgotResp>('/auth/forgot-password', { email });
      setResetUrl(resp.reset_url ?? null);
    } catch {
      // Backend always returns 200 here; if the request itself fails we still
      // show the generic success to avoid leaking anything.
    } finally {
      setSubmitted(true);
      setSubmitting(false);
    }
  };

  const handleCopy = async () => {
    if (!resetUrl) return;
    await navigator.clipboard.writeText(resetUrl);
    setCopied(true);
  };

  if (submitted) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="bg-white p-6 rounded-lg shadow-md w-full max-w-md space-y-4">
          <h1 className="text-xl font-semibold">Check your email</h1>
          <p className="text-sm text-gray-600">
            If an account exists for that email, a reset link will be sent.
          </p>
          {resetUrl && (
            <div className="border-t pt-4 space-y-2">
              <p className="text-xs font-medium text-amber-700">
                Admin: copy this link to email the user.
              </p>
              <code className="block bg-gray-100 p-2 rounded text-xs break-all">
                {resetUrl}
              </code>
              <button
                type="button"
                onClick={() => {
                  void handleCopy();
                }}
                className="px-3 py-1 text-sm bg-gray-200 hover:bg-gray-300 rounded"
              >
                {copied ? 'Copied!' : 'Copy'}
              </button>
            </div>
          )}
          <div className="text-center">
            <Link to="/login" className="text-sm text-blue-600 hover:underline">
              Back to login
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <form
        onSubmit={handleSubmit}
        className="bg-white p-6 rounded-lg shadow-md w-full max-w-md space-y-4"
      >
        <h1 className="text-xl font-semibold">Reset password</h1>
        <p className="text-sm text-gray-600">Enter your email to receive a reset link.</p>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="Email"
          required
          autoFocus
          className="w-full px-3 py-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <button
          type="submit"
          disabled={submitting}
          className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white py-2 rounded font-medium"
        >
          {submitting ? 'Sending…' : 'Send reset link'}
        </button>
        <div className="text-center">
          <Link to="/login" className="text-sm text-blue-600 hover:underline">
            Back to login
          </Link>
        </div>
      </form>
    </div>
  );
}
