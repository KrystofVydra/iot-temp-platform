import { useState } from 'react';
import { ApiError } from '../../lib/api';
import { useCreateDevice } from '../../lib/hooks';
import type { CreateDeviceResponse } from '../../lib/types';
import { Modal } from '../Modal';
import { MqttCredentialsDisplay } from './MqttCredentialsDisplay';

type Props = {
  open: boolean;
  onClose: () => void;
  userId: number;
};

export function AddDeviceModal({ open, onClose, userId }: Props) {
  const [deviceKey, setDeviceKey] = useState('');
  const [name, setName] = useState('');
  const [location, setLocation] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CreateDeviceResponse | null>(null);

  const createDevice = useCreateDevice();

  const handleClose = () => {
    setDeviceKey('');
    setName('');
    setLocation('');
    setError(null);
    setResult(null);
    onClose();
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      const res = await createDevice.mutateAsync({
        user_id: userId,
        device_key: deviceKey,
        name,
        location: location.trim() === '' ? null : location.trim(),
      });
      setResult(res);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409)
          setError('A device with that key already exists.');
        else if (err.status === 400)
          setError(err.message || 'Invalid device key.');
        else setError(err.message || 'Unable to create device.');
      } else {
        setError('Unexpected error.');
      }
    }
  };

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title={result ? 'Device created — MQTT credentials' : 'Add device'}
    >
      {result ? (
        <MqttCredentialsDisplay
          deviceId={result.device.id}
          password={result.mqtt_password}
          sshCommand={result.ssh_command}
          onClose={handleClose}
        />
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          {error && <div className="text-sm text-red-600">{error}</div>}
          <div>
            <label
              className="block text-sm font-medium text-gray-700 mb-1"
              htmlFor="new-device-key"
            >
              Device key
            </label>
            <input
              id="new-device-key"
              type="text"
              value={deviceKey}
              onChange={(e) => setDeviceKey(e.target.value)}
              required
              autoFocus
              pattern="^[a-z0-9_-]+$"
              placeholder="esp32-kitchen-01"
              className="w-full px-3 py-2 border border-gray-300 rounded font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <p className="text-xs text-gray-500 mt-1">
              Lowercase letters, digits, <code>_</code>, and <code>-</code> only.
              Used as the MQTT username and topic prefix.
            </p>
          </div>
          <div>
            <label
              className="block text-sm font-medium text-gray-700 mb-1"
              htmlFor="new-device-name"
            >
              Name
            </label>
            <input
              id="new-device-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              className="w-full px-3 py-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label
              className="block text-sm font-medium text-gray-700 mb-1"
              htmlFor="new-device-location"
            >
              Location (optional)
            </label>
            <input
              id="new-device-location"
              type="text"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
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
              disabled={createDevice.isPending}
              className="px-3 py-1 text-sm bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white rounded"
            >
              {createDevice.isPending ? 'Creating…' : 'Create device'}
            </button>
          </div>
        </form>
      )}
    </Modal>
  );
}
