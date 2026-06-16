import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { format, formatDistanceToNow } from 'date-fns';
import { Modal } from '../../components/Modal';
import { MqttCredentialsModal } from '../../components/admin/MqttCredentialsModal';
import {
  useAcceptPendingController,
  useAdminGateway,
  useAdminUsers,
  useDeleteGateway,
  useRejectPendingController,
  useUpdateGateway,
} from '../../lib/hooks';
import type {
  ControllerForGateway,
  PendingController,
} from '../../lib/types';

const ONLINE_WINDOW_MS = 5 * 60_000;

function controllerOnline(c: ControllerForGateway): boolean {
  return (
    !!c.last_seen_at &&
    Date.now() - new Date(c.last_seen_at).getTime() < ONLINE_WINDOW_MS
  );
}

export function AdminGatewayDetail() {
  const { id } = useParams<{ id: string }>();
  const gatewayId = parseInt(id!, 10);
  const navigate = useNavigate();

  const { data: gateway, isLoading, error } = useAdminGateway(gatewayId);
  const { data: allUsers } = useAdminUsers();
  const updateMutation = useUpdateGateway();
  const deleteMutation = useDeleteGateway();
  const [rotateOpen, setRotateOpen] = useState(false);
  const [acceptTarget, setAcceptTarget] = useState<PendingController | null>(
    null,
  );

  const [name, setName] = useState('');
  const [location, setLocation] = useState('');
  const [ownerId, setOwnerId] = useState<number>(0);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (gateway) {
      setName(gateway.name);
      setLocation(gateway.location ?? '');
      setOwnerId(gateway.owner.id);
    }
  }, [gateway]);

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
  if (!gateway) return null;

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaveError(null);
    try {
      await updateMutation.mutateAsync({
        id: gatewayId,
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
        `Delete ${gateway.device_key}? All of its controllers and readings will be lost.`,
      )
    )
      return;
    try {
      await deleteMutation.mutateAsync(gatewayId);
      navigate('/admin/gateways');
    } catch (e) {
      alert((e as Error).message || 'Unable to delete.');
    }
  };

  return (
    <div>
      <Link
        to="/admin/gateways"
        className="text-sm text-blue-600 hover:underline mb-4 inline-block"
      >
        &larr; Gateways
      </Link>

      <div className="bg-white rounded-lg shadow-sm p-6 mb-6">
        <div className="flex justify-between items-start">
          <div>
            <h1 className="text-2xl font-bold">{gateway.name}</h1>
            <p className="text-gray-600 font-mono text-sm">
              {gateway.device_key}
            </p>
            <p className="text-gray-500 text-sm mt-1">
              Owner:{' '}
              <Link
                to={`/admin/users/${gateway.owner.id}`}
                className="text-blue-600 hover:underline"
              >
                {gateway.owner.email}
              </Link>
            </p>
          </div>
          <span
            className={`text-xs px-2 py-1 rounded ${
              gateway.mqtt_provisioned
                ? 'bg-green-100 text-green-700'
                : 'bg-yellow-100 text-yellow-700'
            }`}
          >
            {gateway.mqtt_provisioned
              ? '✓ MQTT provisioned'
              : '⚠ MQTT not provisioned'}
          </span>
        </div>
        <dl className="mt-4 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-gray-500">Created</dt>
          <dd>{format(new Date(gateway.created_at), 'PPpp')}</dd>
          <dt className="text-gray-500">Last seen</dt>
          <dd>
            {gateway.last_seen_at
              ? format(new Date(gateway.last_seen_at), 'PPpp')
              : 'Never'}
          </dd>
        </dl>

        <div className="mt-4 pt-4 border-t flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setRotateOpen(true)}
            className="px-3 py-1 text-sm bg-gray-100 hover:bg-gray-200 rounded text-gray-700"
          >
            {gateway.mqtt_provisioned
              ? 'Rotate MQTT password'
              : 'Generate MQTT password'}
          </button>
          <button
            type="button"
            onClick={handleDelete}
            className="px-3 py-1 text-sm bg-red-50 hover:bg-red-100 rounded text-red-700"
          >
            Delete gateway
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
              htmlFor="edit-gateway-name"
            >
              Name
            </label>
            <input
              id="edit-gateway-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              className="w-full px-3 py-2 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label
              className="block text-sm font-medium text-gray-700 mb-1"
              htmlFor="edit-gateway-location"
            >
              Location
            </label>
            <input
              id="edit-gateway-location"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label
              className="block text-sm font-medium text-gray-700 mb-1"
              htmlFor="edit-gateway-owner"
            >
              Owner
            </label>
            <select
              id="edit-gateway-owner"
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

      {gateway.pending_controllers.length > 0 && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-6 mb-6">
          <h2 className="font-semibold mb-3 text-yellow-900">
            Pending controllers ({gateway.pending_controllers.length})
          </h2>
          <p className="text-xs text-yellow-800 mb-3">
            These controllers are reporting via this gateway but haven't been
            accepted yet.
          </p>
          <ul className="divide-y divide-yellow-200">
            {gateway.pending_controllers.map((p) => (
              <PendingControllerRow
                key={p.id}
                pending={p}
                gatewayId={gatewayId}
                onAccept={() => setAcceptTarget(p)}
              />
            ))}
          </ul>
        </div>
      )}

      <h2 className="text-lg font-semibold mb-3">
        Controllers ({gateway.controllers.length})
      </h2>
      {gateway.controllers.length === 0 ? (
        <p className="text-sm text-gray-500">No controllers yet.</p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {gateway.controllers.map((c) => {
            const online = controllerOnline(c);
            return (
              <Link
                key={c.id}
                to={`/admin/controllers/${c.id}`}
                className="block bg-white rounded-lg shadow-sm p-3 hover:shadow-md transition"
              >
                <div className="flex justify-between items-start mb-2 gap-2">
                  <div className="min-w-0">
                    <div className="font-semibold truncate">{c.name}</div>
                    <div className="text-xs text-gray-500 font-mono truncate">
                      {c.sn}
                    </div>
                  </div>
                  <span
                    className={`text-xs px-2 py-0.5 rounded shrink-0 ${
                      online
                        ? 'bg-green-100 text-green-700'
                        : 'bg-gray-100 text-gray-600'
                    }`}
                  >
                    {online ? 'Online' : 'Offline'}
                  </span>
                </div>
                <div className="text-xs text-gray-500">
                  {c.node_count} node{c.node_count === 1 ? '' : 's'}
                </div>
                <div className="text-xs text-gray-400 mt-1">
                  {c.last_seen_at
                    ? `seen ${formatDistanceToNow(new Date(c.last_seen_at), { addSuffix: true })}`
                    : 'never seen'}
                </div>
              </Link>
            );
          })}
        </div>
      )}

      {rotateOpen && (
        <MqttCredentialsModal
          open={true}
          onClose={() => setRotateOpen(false)}
          gatewayId={gatewayId}
        />
      )}
      {acceptTarget && (
        <AcceptPendingModal
          pending={acceptTarget}
          onClose={() => setAcceptTarget(null)}
        />
      )}
    </div>
  );
}

function PendingControllerRow({
  pending,
  gatewayId,
  onAccept,
}: {
  pending: PendingController;
  gatewayId: number;
  onAccept: () => void;
}) {
  const reject = useRejectPendingController();
  const [busy, setBusy] = useState(false);

  const handleReject = async () => {
    if (
      !window.confirm(
        `Reject controller ${pending.sn}? It will be dropped from this gateway.`,
      )
    )
      return;
    setBusy(true);
    try {
      await reject.mutateAsync(pending.id);
    } catch (e) {
      alert((e as Error).message || 'Unable to reject.');
      setBusy(false);
    }
    // ignore gatewayId — query invalidation handles refetch
    void gatewayId;
  };

  return (
    <li className="py-2 flex flex-wrap items-center justify-between gap-2">
      <div>
        <div className="font-mono text-sm text-yellow-900">{pending.sn}</div>
        <div className="text-xs text-yellow-800">
          first seen{' '}
          {formatDistanceToNow(new Date(pending.first_seen_at), {
            addSuffix: true,
          })}{' '}
          · last{' '}
          {formatDistanceToNow(new Date(pending.last_seen_at), {
            addSuffix: true,
          })}{' '}
          · {pending.message_count} msg
        </div>
      </div>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={onAccept}
          disabled={busy}
          className="px-3 py-1 text-sm bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white rounded"
        >
          Accept
        </button>
        <button
          type="button"
          onClick={handleReject}
          disabled={busy}
          className="px-3 py-1 text-sm bg-red-50 hover:bg-red-100 rounded text-red-700"
        >
          Reject
        </button>
      </div>
    </li>
  );
}

function AcceptPendingModal({
  pending,
  onClose,
}: {
  pending: PendingController;
  onClose: () => void;
}) {
  const accept = useAcceptPendingController();
  const [name, setName] = useState(`Controller ${pending.sn}`);
  const [location, setLocation] = useState('');
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await accept.mutateAsync({
        pendingId: pending.id,
        name,
        location: location.trim() === '' ? null : location.trim(),
      });
      onClose();
    } catch (e) {
      setError((e as Error).message || 'Unable to accept.');
    }
  };

  return (
    <Modal
      open={true}
      onClose={onClose}
      title={`Accept controller ${pending.sn}`}
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        {error && <div className="text-sm text-red-600">{error}</div>}
        <div>
          <label
            className="block text-sm font-medium text-gray-700 mb-1"
            htmlFor="accept-name"
          >
            Name
          </label>
          <input
            id="accept-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            autoFocus
            className="w-full px-3 py-2 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label
            className="block text-sm font-medium text-gray-700 mb-1"
            htmlFor="accept-location"
          >
            Location (optional)
          </label>
          <input
            id="accept-location"
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1 text-sm bg-gray-200 hover:bg-gray-300 rounded"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={accept.isPending}
            className="px-3 py-1 text-sm bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white rounded"
          >
            {accept.isPending ? 'Accepting…' : 'Accept'}
          </button>
        </div>
      </form>
    </Modal>
  );
}
