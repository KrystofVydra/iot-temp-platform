import { Link } from 'react-router-dom';

export function NotFound() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="bg-white p-6 rounded-lg shadow-md w-full max-w-md space-y-4 text-center">
        <h1 className="text-xl font-semibold">Page not found</h1>
        <p className="text-sm text-gray-600">
          The page you tried to open doesn&rsquo;t exist.
        </p>
        <Link to="/login" className="inline-block text-sm text-blue-600 hover:underline">
          Back to login &rarr;
        </Link>
      </div>
    </div>
  );
}
