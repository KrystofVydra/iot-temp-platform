import { useEffect, useState } from 'react';
import { useRotateMqttPassword } from '../../lib/hooks';
import type { RotateMqttResponse } from '../../lib/types';
import { Modal } from '../Modal';
import { MqttCredentialsDisplay } from './MqttCredentialsDisplay';

type Props = {
  open: boolean;
  onClose: () => void;
  gatewayId: number;
};

export function MqttCredentialsModal({ open, onClose, gatewayId }: Props) {
  const [result, setResult] = useState<RotateMqttResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const rotate = useRotateMqttPassword();

  useEffect(() => {
    if (!open) return;
    setResult(null);
    setError(null);
    rotate
      .mutateAsync(gatewayId)
      .then(setResult)
      .catch((e: unknown) =>
        setError((e as Error)?.message || 'Failed to rotate password.'),
      );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, gatewayId]);

  return (
    <Modal open={open} onClose={onClose} title="MQTT credentials">
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
      ) : result ? (
        <MqttCredentialsDisplay
          gatewayId={gatewayId}
          password={result.mqtt_password}
          sshCommand={result.ssh_command}
          onClose={onClose}
        />
      ) : (
        <p className="text-sm text-gray-500">Generating credentials…</p>
      )}
    </Modal>
  );
}
