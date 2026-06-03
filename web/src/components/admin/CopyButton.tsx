import { useEffect, useState } from 'react';
import { copyToClipboard } from '../../lib/clipboard';

type Props = {
  text: string;
  className?: string;
};

export function CopyButton({ text, className }: Props) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(t);
  }, [copied]);

  return (
    <button
      type="button"
      onClick={async () => {
        const ok = await copyToClipboard(text);
        if (ok) setCopied(true);
      }}
      className={
        className ??
        'px-3 py-1 text-sm bg-gray-200 hover:bg-gray-300 rounded whitespace-nowrap'
      }
    >
      {copied ? 'Copied!' : 'Copy'}
    </button>
  );
}
