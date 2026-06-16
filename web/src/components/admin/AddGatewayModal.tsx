import { useState } from 'react';
import { ApiError } from '../../lib/api';
import { useAdminUsers, useCreateGateway } from '../../lib/hooks';
import type { CreateGatewayResponse } from '../../lib/types';
import { Modal } from '../Modal';
import { MqttCredentialsDisplay } from './MqttCredentialsDisplay';

type Props = {
  open: boolean;
  onClose: () => void;
  // If provided, pre-fill the owner. Otherwise show a user picker.
  userId?: number;
};

export function AddGatewayModal({ open, onClose, userId }: Props) {
  const [deviceKey, setDeviceKey] = useState('');
  const [name, setName] = useState('');
  const [location, setLocation] = useState('');
  const [selectedUserId, setSelectedUserId] = useState<number | null>(
    userId ?? null,
  );
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CreateGatewayResponse | null>(null);

  const createGateway = useCreateGateway();
  const users = useAdminUsers();

  const handleClose = () => {
    setDeviceKey('');
    setName('');
    setLocation('');
    setSelectedUserId(userId ?? null);
    setError(null);
    setResult(null);
    onClose();
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const effectiveUserId = userId ?? selectedUserId;
    if (!effectiveUserId) {
      setError('Pick an owner.');
      return;
    }
    try {
      const res = await createGateway.mutateAsync({
        user_id: effectiveUserId,
        device_key: deviceKey,
        name,
        location: location.trim() === '' ? null : location.trim(),
      });
      setResult(res);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409)
          setError('A gateway with that key already exists.');
        else if (err.status === 400)
          setError(err.message || 'Invalid device key.');
        else setError(err.message || 'Unable to create gateway.');
      } else {
        setError('Unexpected error.');
      }
    }
  };

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title={result ? 'Gateway created — MQTT credentials' : 'Add gateway'}
    >
      {result ? (
        <MqttCredentialsDisplay
          gatewayId={result.gateway.id}
          password={result.mqtt_password}
          sshCommand={result.ssh_command}
          onClose={handleClose}
        />
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          {error && <div className="text-sm text-red-600">{error}</div>}
          {userId === undefined && (
            <div>
              <label
                className="block text-sm font-medium text-gray-700 mb-1"
                htmlFor="new-gateway-owner"
              >
                Owner
              </label>
              <select
                id="new-gateway-owner"
                value={selectedUserId ?? ''}
                onChange={(e) =>
                  setSelectedUserId(
                    e.target.value ? parseInt(e.target.value, 10) : null,
                  )
                }
                required
                className="w-full px-3 py-2 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">— Select user —</option>
                {users.data?.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.email}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div>
            <label
              className="block text-sm font-medium text-gray-700 mb-1"
              htmlFor="new-gateway-key"
            >
              Device key
            </label>
            <input
              id="new-gateway-key"
              type="text"
              value={deviceKey}
              onChange={(e) => setDeviceKey(e.target.value)}
              required
              autoFocus
              pattern="^[a-z0-9_-]+$"
              placeholder="gateway-warehouse-01"
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
              htmlFor="new-gateway-name"
            >
              Name
            </label>
            <input
              id="new-gateway-name"
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
              htmlFor="new-gateway-location"
            >
              Location (optional)
            </label>
            <input
              id="new-gateway-location"
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
              disabled={createGateway.isPending}
              className="px-3 py-1 text-sm bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white rounded"
            >
              {createGateway.isPending ? 'Creating…' : 'Create gateway'}
            </button>
          </div>
        </form>
      )}
    </Modal>
  );
}
