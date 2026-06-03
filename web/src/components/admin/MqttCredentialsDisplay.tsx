import { useState } from 'react';
import { useUpdateDevice } from '../../lib/hooks';
import { CopyButton } from './CopyButton';

type Props = {
  deviceId: number;
  password: string;
  sshCommand: string;
  onClose: () => void;
};

export function MqttCredentialsDisplay({
  deviceId,
  password,
  sshCommand,
  onClose,
}: Props) {
  const update = useUpdateDevice();
  const [marking, setMarking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleMarkProvisioned = async () => {
    setMarking(true);
    setError(null);
    try {
      await update.mutateAsync({
        id: deviceId,
        patch: { mqtt_provisioned: true },
      });
      onClose();
    } catch (e) {
      setError((e as Error).message || 'Failed to mark provisioned.');
      setMarking(false);
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <p className="text-sm font-medium text-amber-700 mb-1">
          Save this password now — it cannot be retrieved later.
        </p>
        <div className="flex gap-2 items-center">
          <code className="flex-1 bg-gray-100 p-2 rounded text-xs break-all">
            {password}
          </code>
          <CopyButton text={password} />
        </div>
      </div>
      <div>
        <p className="text-sm font-medium text-gray-700 mb-1">
          SSH command — run on the VPS to register the credential with Mosquitto:
        </p>
        <div className="flex gap-2 items-start">
          <code className="flex-1 bg-gray-100 p-2 rounded text-xs break-all">
            {sshCommand}
          </code>
          <CopyButton text={sshCommand} />
        </div>
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          disabled={marking}
          className="px-3 py-1 text-sm bg-gray-200 hover:bg-gray-300 rounded"
        >
          Skip &mdash; I&rsquo;ll provision later
        </button>
        <button
          type="button"
          onClick={handleMarkProvisioned}
          disabled={marking}
          className="px-3 py-1 text-sm bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white rounded"
        >
          {marking ? 'Saving…' : "I've provisioned this device"}
        </button>
      </div>
    </div>
  );
}
