import { useEffect, useState } from 'react';
import { ApiError } from '../../lib/api';
import { useResendInvitation } from '../../lib/hooks';
import { Modal } from '../Modal';
import { CopyButton } from './CopyButton';

type Props = {
  open: boolean;
  onClose: () => void;
  userId: number;
};

export function ResendInvitationModal({ open, onClose, userId }: Props) {
  const [invitationUrl, setInvitationUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const resend = useResendInvitation();

  useEffect(() => {
    if (!open) return;
    setInvitationUrl(null);
    setError(null);
    resend
      .mutateAsync(userId)
      .then((res) => setInvitationUrl(res.invitation_url))
      .catch((e: unknown) => {
        if (e instanceof ApiError && e.status === 400) {
          setError(
            'User already has a password set — use the reset link instead.',
          );
        } else {
          setError(
            (e as Error)?.message || 'Unable to issue invitation link.',
          );
        }
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, userId]);

  return (
    <Modal open={open} onClose={onClose} title="Invitation link">
      {error ? (
        <div className="space-y-4">
          <p className="text-sm text-red-600">{error}</p>
          <div className="flex justify-end">
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1 text-sm bg-gray-200 hover:bg-gray-300 rounded"
            >
              Close
            </button>
          </div>
        </div>
      ) : invitationUrl ? (
        <div className="space-y-4">
          <p className="text-sm text-gray-600">
            Share with the user. It expires in 7 days. Previously-issued
            invitations for this user remain valid until they expire too.
          </p>
          <code className="block bg-gray-100 p-3 rounded text-xs break-all">
            {invitationUrl}
          </code>
          <div className="flex justify-end gap-2">
            <CopyButton text={invitationUrl} />
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded"
            >
              Done
            </button>
          </div>
        </div>
      ) : (
        <p className="text-sm text-gray-500">Generating link…</p>
      )}
    </Modal>
  );
}
