import { useState } from 'react';

export function TokenGate({ children }: { children: React.ReactNode }) {
  const [hasToken, setHasToken] = useState(() => !!localStorage.getItem('api_token'));
  const [input, setInput] = useState('');

  if (hasToken) return <>{children}</>;

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (input.trim()) {
            localStorage.setItem('api_token', input.trim());
            setHasToken(true);
          }
        }}
        className="bg-white p-6 rounded-lg shadow-md w-full max-w-md space-y-4"
      >
        <h1 className="text-xl font-semibold">API Token Required</h1>
        <p className="text-sm text-gray-600">
          Enter your API token to access the dashboard. It will be stored in your browser.
        </p>
        <input
          type="password"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="API token"
          className="w-full px-3 py-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
          autoFocus
        />
        <button
          type="submit"
          className="w-full bg-blue-600 hover:bg-blue-700 text-white py-2 rounded font-medium"
        >
          Save
        </button>
      </form>
    </div>
  );
}
