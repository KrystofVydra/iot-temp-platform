import { useEffect, useRef } from 'react';

interface ConfirmDeleteModalProps {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void | Promise<void>;
  title: string;
  entityName: string;
  description: string;
  confirmLabel?: string;
  showDownloadOption?: boolean;
  onDownload?: () => void;
  isPending?: boolean;
}

export function ConfirmDeleteModal({
  open,
  onClose,
  onConfirm,
  title,
  entityName,
  description,
  confirmLabel = 'Delete',
  showDownloadOption = false,
  onDownload,
  isPending = false,
}: ConfirmDeleteModalProps) {
  const cancelRef = useRef<HTMLButtonElement>(null);

  // Escape closes (unless a delete is in flight).
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !isPending) onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose, isPending]);

  // Start focus on Cancel (safer than defaulting focus to the destructive
  // action). Enter/Space on the focused Cancel button cancels natively.
  useEffect(() => {
    if (open) cancelRef.current?.focus();
  }, [open]);

  if (!open) return null;

  const secondaryBtn =
    'px-3 py-1.5 text-sm bg-gray-100 hover:bg-gray-200 rounded text-gray-700 ' +
    'disabled:opacity-50 disabled:cursor-not-allowed';

  return (
    <div
      className="fixed inset-0 bg-black/30 flex items-center justify-center z-50 p-4"
      onClick={isPending ? undefined : onClose}
      role="presentation"
    >
      <div
        className="bg-white rounded-lg shadow-lg max-w-md w-full"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="p-6">
          <div className="flex items-start gap-3">
            <div className="shrink-0 w-10 h-10 rounded-full bg-red-50 flex items-center justify-center">
              <WarningIcon />
            </div>
            <div className="min-w-0">
              <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
              <p className="mt-2 text-sm text-gray-900 font-semibold break-words">
                {entityName}
              </p>
              <p className="mt-1 text-sm text-gray-600">{description}</p>
              <p className="mt-3 text-sm font-medium text-red-600">
                This action cannot be undone.
              </p>
            </div>
          </div>

          <div className="mt-6 flex justify-end gap-2">
            {showDownloadOption && (
              <button
                type="button"
                onClick={onDownload}
                disabled={isPending}
                className={`mr-auto ${secondaryBtn}`}
              >
                Download data first
              </button>
            )}
            <button
              ref={cancelRef}
              type="button"
              onClick={onClose}
              disabled={isPending}
              className={secondaryBtn}
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => {
                void onConfirm();
              }}
              disabled={isPending}
              className="px-3 py-1.5 text-sm bg-red-600 hover:bg-red-700 disabled:bg-red-300 text-white rounded inline-flex items-center gap-2"
            >
              {isPending && <Spinner />}
              {isPending ? 'Deleting…' : confirmLabel}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function WarningIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="w-5 h-5 text-red-600"
      aria-hidden="true"
    >
      <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  );
}

function Spinner() {
  return (
    <svg
      className="animate-spin w-4 h-4"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 0 1 8-8v4a4 4 0 0 0-4 4H4z"
      />
    </svg>
  );
}
