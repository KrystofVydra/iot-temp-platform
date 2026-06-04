import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { format } from 'date-fns';
import { DeviceChart } from '../../components/DeviceChart';
import { MqttCredentialsModal } from '../../components/admin/MqttCredentialsModal';
import {
  useAdminDevice,
  useAdminLatestReading,
  useAdminUsers,
  useDeleteDevice,
  useUpdateDevice,
} from '../../lib/hooks';
import type { TimeRange } from '../../lib/types';

export function AdminDeviceDetail() {
  const { id } = useParams<{ id: string }>();
  const deviceId = parseInt(id!, 10);
  const navigate = useNavigate();

  const { data: device, isLoading, error } = useAdminDevice(deviceId);
  const { data: allUsers } = useAdminUsers();
  const updateMutation = useUpdateDevice();
  const deleteMutation = useDeleteDevice();
  const [rotateOpen, setRotateOpen] = useState(false);

  const [name, setName] = useState('');
  const [location, setLocation] = useState('');
  const [ownerId, setOwnerId] = useState<number>(0);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const [range, setRange] = useState<TimeRange>('24h');
  const latest = useAdminLatestReading(deviceId);

  useEffect(() => {
    if (device) {
      setName(device.name);
      setLocation(device.location ?? '');
      setOwnerId(device.owner.id);
    }
  }, [device]);

  useEffect(() => {
    if (!saved) return;
    const t = setTimeout(() => setSaved(false), 1500);
    return () => clearTimeout(t);
  }, [saved]);

  if (isLoading) return <div className="text-sm text-gray-500">Loading…</div>;
  if (error)
    return (
      <div className="text-sm text-red-600">
        Error: {(error as Error).message}
      </div>
    );
  if (!device) return null;

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaveError(null);
    try {
      await updateMutation.mutateAsync({
        id: deviceId,
        patch: {
          name,
          location: location.trim() === '' ? null : location.trim(),
          user_id: ownerId,
        },
      });
      setSaved(true);
    } catch (e) {
      setSaveError((e as Error).message || 'Unable to save.');
    }
  };

  const handleDelete = async () => {
    if (
      !window.confirm(
        `Delete ${device.device_key}? All of its readings will be lost.`,
      )
    )
      return;
    try {
      await deleteMutation.mutateAsync(deviceId);
      navigate('/admin/devices');
    } catch (e) {
      alert((e as Error).message || 'Unable to delete.');
    }
  };

  return (
    <div>
      <Link
        to="/admin/devices"
        className="text-sm text-blue-600 hover:underline mb-4 inline-block"
      >
        &larr; Devices
      </Link>

      <div className="bg-white rounded-lg shadow-sm p-6 mb-6">
        <div className="flex justify-between items-start">
          <div>
            <h1 className="text-2xl font-bold">{device.name}</h1>
            <p className="text-gray-600 font-mono text-sm">
              {device.device_key}
            </p>
            <p className="text-gray-500 text-sm mt-1">
              Owner:{' '}
              <Link
                to={`/admin/users/${device.owner.id}`}
                className="text-blue-600 hover:underline"
              >
                {device.owner.email}
              </Link>
            </p>
          </div>
          <span
            className={`text-xs px-2 py-1 rounded ${
              device.mqtt_provisioned
                ? 'bg-green-100 text-green-700'
                : 'bg-yellow-100 text-yellow-700'
            }`}
          >
            {device.mqtt_provisioned
              ? '✓ MQTT provisioned'
              : '⚠ MQTT not provisioned'}
          </span>
        </div>
        <dl className="mt-4 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-gray-500">Created</dt>
          <dd>{format(new Date(device.created_at), 'PPpp')}</dd>
          <dt className="text-gray-500">Last seen</dt>
          <dd>
            {device.last_seen_at
              ? format(new Date(device.last_seen_at), 'PPpp')
              : 'Never'}
          </dd>
        </dl>

        <div className="mt-4 pt-4 border-t flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setRotateOpen(true)}
            className="px-3 py-1 text-sm bg-gray-100 hover:bg-gray-200 rounded text-gray-700"
          >
            {device.mqtt_provisioned
              ? 'Rotate MQTT password'
              : 'Generate MQTT password'}
          </button>
          <button
            type="button"
            onClick={handleDelete}
            className="px-3 py-1 text-sm bg-red-50 hover:bg-red-100 rounded text-red-700"
          >
            Delete device
          </button>
        </div>
      </div>

      <div className="bg-white rounded-lg shadow-sm p-6 mb-6">
        <h2 className="font-semibold mb-3">Edit</h2>
        <form onSubmit={handleSave} className="space-y-3">
          {saveError && (
            <div className="text-sm text-red-600">{saveError}</div>
          )}
          {saved && <div className="text-sm text-green-700">Saved.</div>}
          <div>
            <label
              className="block text-sm font-medium text-gray-700 mb-1"
              htmlFor="edit-device-name"
            >
              Name
            </label>
            <input
              id="edit-device-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              className="w-full px-3 py-2 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label
              className="block text-sm font-medium text-gray-700 mb-1"
              htmlFor="edit-device-location"
            >
              Location
            </label>
            <input
              id="edit-device-location"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label
              className="block text-sm font-medium text-gray-700 mb-1"
              htmlFor="edit-device-owner"
            >
              Owner
            </label>
            <select
              id="edit-device-owner"
              value={ownerId}
              onChange={(e) => setOwnerId(parseInt(e.target.value, 10))}
              className="w-full px-3 py-2 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {allUsers?.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.email}
                </option>
              ))}
            </select>
          </div>
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={updateMutation.isPending}
              className="px-3 py-1 text-sm bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white rounded"
            >
              {updateMutation.isPending ? 'Saving…' : 'Save changes'}
            </button>
          </div>
        </form>
      </div>

      {latest.data && (
        <div className="bg-white rounded-lg shadow-sm p-6 mb-6">
          <div className="text-5xl font-light mb-2">
            {latest.data.temperature.toFixed(2)}°C
          </div>
          <div className="text-sm text-gray-500">
            Lux: {latest.data.lux} · Battery:{' '}
            {latest.data.battery_v !== null
              ? `${latest.data.battery_v.toFixed(2)}V`
              : '–'}{' '}
            · Updated {format(new Date(latest.data.time), 'PPpp')}
          </div>
        </div>
      )}

      <DeviceChart
        deviceId={deviceId}
        mode="admin"
        range={range}
        setRange={setRange}
      />

      {rotateOpen && (
        <MqttCredentialsModal
          open={true}
          onClose={() => setRotateOpen(false)}
          deviceId={deviceId}
        />
      )}
    </div>
  );
}
