import { useEffect, useState } from 'react';
import { ApiError } from '../../lib/api';
import { useSendResetLink } from '../../lib/hooks';
import { Modal } from '../Modal';
import { CopyButton } from './CopyButton';

type Props = {
  open: boolean;
  onClose: () => void;
  userId: number;
};

export function ResetLinkModal({ open, onClose, userId }: Props) {
  const [resetUrl, setResetUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const sendResetLink = useSendResetLink();

  useEffect(() => {
    if (!open) return;
    setResetUrl(null);
    setError(null);
    sendResetLink
      .mutateAsync(userId)
      .then((res) => setResetUrl(res.reset_url))
      .catch((e: unknown) => {
        if (e instanceof ApiError && e.status === 400) {
          setError(
            "This user hasn't set a password yet — use the invitation flow.",
          );
        } else {
          setError(
            (e as Error)?.message || 'Unable to issue reset link.',
          );
        }
      });
    // sendResetLink reference is stable across renders; the lint warning here
    // would re-trigger the effect every render if we listed it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, userId]);

  return (
    <Modal open={open} onClose={onClose} title="Password reset link">
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
      ) : resetUrl ? (
        <div className="space-y-4">
          <p className="text-sm text-gray-600">
            Share with the user. The link expires in 1 hour.
          </p>
          <code className="block bg-gray-100 p-3 rounded text-xs break-all">
            {resetUrl}
          </code>
          <div className="flex justify-end gap-2">
            <CopyButton text={resetUrl} />
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
