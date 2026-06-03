import { useState } from 'react';
import { ApiError } from '../../lib/api';
import { useCreateUser } from '../../lib/hooks';
import { Modal } from '../Modal';
import { CopyButton } from './CopyButton';

type Props = {
  open: boolean;
  onClose: () => void;
};

export function AddUserModal({ open, onClose }: Props) {
  const [email, setEmail] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [invitationUrl, setInvitationUrl] = useState<string | null>(null);

  const createUser = useCreateUser();

  const handleClose = () => {
    setEmail('');
    setDisplayName('');
    setError(null);
    setInvitationUrl(null);
    onClose();
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      const res = await createUser.mutateAsync({
        email,
        display_name: displayName,
      });
      setInvitationUrl(res.invitation_url);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409) setError('A user with that email already exists.');
        else setError(err.message || 'Unable to create user.');
      } else {
        setError('Unexpected error.');
      }
    }
  };

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title={invitationUrl ? 'Invitation issued' : 'Add user'}
    >
      {invitationUrl ? (
        <div className="space-y-4">
          <p className="text-sm text-gray-600">
            Share this link with the user. It expires in 7 days.
          </p>
          <code className="block bg-gray-100 p-3 rounded text-xs break-all">
            {invitationUrl}
          </code>
          <div className="flex justify-end gap-2">
            <CopyButton text={invitationUrl} />
            <button
              type="button"
              onClick={handleClose}
              className="px-3 py-1 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded"
            >
              Done
            </button>
          </div>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          {error && <div className="text-sm text-red-600">{error}</div>}
          <div>
            <label
              className="block text-sm font-medium text-gray-700 mb-1"
              htmlFor="new-user-email"
            >
              Email
            </label>
            <input
              id="new-user-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
              className="w-full px-3 py-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label
              className="block text-sm font-medium text-gray-700 mb-1"
              htmlFor="new-user-display-name"
            >
              Display name
            </label>
            <input
              id="new-user-display-name"
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              required
              className="w-full px-3 py-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={handleClose}
              className="px-3 py-1 text-sm bg-gray-200 hover:bg-gray-300 rounded"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={createUser.isPending}
              className="px-3 py-1 text-sm bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white rounded"
            >
              {createUser.isPending ? 'Creating…' : 'Create + issue invitation'}
            </button>
          </div>
        </form>
      )}
    </Modal>
  );
}
