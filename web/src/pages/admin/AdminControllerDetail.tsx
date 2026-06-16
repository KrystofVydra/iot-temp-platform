import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { format } from 'date-fns';
import { ControllerChart } from '../../components/ControllerChart';
import { Modal } from '../../components/Modal';
import { NodeTile } from '../../components/NodeTile';
import {
  useAdminController,
  useAdminControllerReadings,
  useDeleteController,
  useDeleteNode,
  useUpdateController,
  useUpdateNode,
} from '../../lib/hooks';
import type { NodeOut, TimeRange } from '../../lib/types';

export function AdminControllerDetail() {
  const { id } = useParams<{ id: string }>();
  const controllerId = parseInt(id!, 10);
  const navigate = useNavigate();
  const [range, setRange] = useState<TimeRange>('24h');

  const controller = useAdminController(controllerId);
  const readings = useAdminControllerReadings(controllerId, range);
  const updateController = useUpdateController();
  const deleteController = useDeleteController();

  const [name, setName] = useState('');
  const [location, setLocation] = useState('');
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [editNode, setEditNode] = useState<NodeOut | null>(null);

  useEffect(() => {
    if (controller.data) {
      setName(controller.data.name);
      setLocation(controller.data.location ?? '');
    }
  }, [controller.data]);

  useEffect(() => {
    if (!saved) return;
    const t = setTimeout(() => setSaved(false), 1500);
    return () => clearTimeout(t);
  }, [saved]);

  if (controller.isLoading)
    return <div className="text-sm text-gray-500">Loading…</div>;
  if (controller.error)
    return (
      <div className="text-sm text-red-600">
        Error: {(controller.error as Error).message}
      </div>
    );
  if (!controller.data) return null;

  const c = controller.data;
  const latestTel = c.latest_telemetry;

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaveError(null);
    try {
      await updateController.mutateAsync({
        id: controllerId,
        patch: {
          name,
          location: location.trim() === '' ? null : location.trim(),
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
        `Delete controller ${c.name}? All of its nodes and readings will be lost.`,
      )
    )
      return;
    try {
      await deleteController.mutateAsync(controllerId);
      navigate(`/admin/gateways/${c.gateway.id}`);
    } catch (e) {
      alert((e as Error).message || 'Unable to delete.');
    }
  };

  return (
    <div>
      <Link
        to={`/admin/gateways/${c.gateway.id}`}
        className="text-sm text-blue-600 hover:underline mb-4 inline-block"
      >
        &larr; {c.gateway.name}
      </Link>

      <div className="bg-white rounded-lg shadow-sm p-6 mb-6">
        <div className="text-sm text-gray-500">
          {c.gateway.name} <span className="text-gray-300">›</span>{' '}
          <span className="text-gray-700 font-medium">{c.name}</span>
        </div>
        <h1 className="text-2xl font-bold">{c.name}</h1>
        {c.location && <p className="text-gray-500 text-sm">{c.location}</p>}
        <p className="text-xs text-gray-400 font-mono mt-1">sn: {c.sn}</p>

        <form onSubmit={handleSave} className="mt-4 space-y-3">
          {saveError && (
            <div className="text-sm text-red-600">{saveError}</div>
          )}
          {saved && <div className="text-sm text-green-700">Saved.</div>}
          <div>
            <label
              className="block text-sm font-medium text-gray-700 mb-1"
              htmlFor="edit-controller-name"
            >
              Name
            </label>
            <input
              id="edit-controller-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              className="w-full px-3 py-2 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label
              className="block text-sm font-medium text-gray-700 mb-1"
              htmlFor="edit-controller-location"
            >
              Location
            </label>
            <input
              id="edit-controller-location"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div className="flex justify-between gap-2">
            <button
              type="submit"
              disabled={updateController.isPending}
              className="px-3 py-1 text-sm bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white rounded"
            >
              {updateController.isPending ? 'Saving…' : 'Save changes'}
            </button>
            <button
              type="button"
              onClick={handleDelete}
              className="px-3 py-1 text-sm bg-red-50 hover:bg-red-100 rounded text-red-700"
            >
              Delete controller
            </button>
          </div>
        </form>
      </div>

      <h2 className="text-lg font-semibold mb-3">Nodes ({c.nodes.length})</h2>
      {c.nodes.length === 0 ? (
        <p className="text-sm text-gray-500 mb-6">No nodes yet.</p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 mb-6">
          {c.nodes.map((n) => (
            <NodeTile
              key={n.id}
              node={n}
              actions={
                <NodeActions node={n} onEdit={() => setEditNode(n)} />
              }
            />
          ))}
        </div>
      )}

      <ControllerChart
        data={readings.data}
        range={range}
        setRange={setRange}
        isLoading={readings.isLoading}
      />

      <div className="mt-4 bg-white rounded-lg shadow-sm p-4 text-sm text-gray-600">
        <div className="font-medium text-gray-700 mb-2">Controller telemetry</div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          <div>
            <div className="text-xs text-gray-400">Battery</div>
            <div>
              {latestTel.battery_v !== null
                ? `${latestTel.battery_v.toFixed(2)} V`
                : '—'}
            </div>
          </div>
          <div>
            <div className="text-xs text-gray-400">Door</div>
            <div>
              {latestTel.door_open === null
                ? '—'
                : latestTel.door_open
                  ? 'Open'
                  : 'Closed'}
            </div>
          </div>
          <div>
            <div className="text-xs text-gray-400">Last telemetry</div>
            <div>
              {latestTel.time
                ? format(new Date(latestTel.time), 'PPp')
                : '—'}
            </div>
          </div>
        </div>
      </div>

      {editNode && (
        <EditNodeModal node={editNode} onClose={() => setEditNode(null)} />
      )}
    </div>
  );
}

function NodeActions({
  node,
  onEdit,
}: {
  node: NodeOut;
  onEdit: () => void;
}) {
  const del = useDeleteNode();
  const handleDelete = async () => {
    if (
      !window.confirm(
        `Delete node ${node.name?.trim() || `#${node.node_index}`}? Its readings will be lost.`,
      )
    )
      return;
    try {
      await del.mutateAsync(node.id);
    } catch (e) {
      alert((e as Error).message || 'Unable to delete.');
    }
  };
  return (
    <>
      <button
        type="button"
        onClick={onEdit}
        className="px-2 py-1 text-xs bg-gray-100 hover:bg-gray-200 rounded text-gray-700"
      >
        Edit
      </button>
      <button
        type="button"
        onClick={handleDelete}
        className="px-2 py-1 text-xs bg-red-50 hover:bg-red-100 rounded text-red-700"
      >
        Delete
      </button>
    </>
  );
}

function EditNodeModal({
  node,
  onClose,
}: {
  node: NodeOut;
  onClose: () => void;
}) {
  const update = useUpdateNode();
  const [name, setName] = useState(node.name ?? '');
  const [hasLux, setHasLux] = useState(node.has_lux);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      const trimmed = name.trim();
      await update.mutateAsync({
        id: node.id,
        patch: {
          ...(trimmed === '' ? {} : { name: trimmed }),
          has_lux: hasLux,
        },
      });
      onClose();
    } catch (e) {
      setError((e as Error).message || 'Unable to save.');
    }
  };

  return (
    <Modal
      open={true}
      onClose={onClose}
      title={`Edit node #${node.node_index}`}
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        {error && <div className="text-sm text-red-600">{error}</div>}
        <div>
          <label
            className="block text-sm font-medium text-gray-700 mb-1"
            htmlFor="edit-node-name"
          >
            Name (optional)
          </label>
          <input
            id="edit-node-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={`Node ${node.node_index}`}
            className="w-full px-3 py-2 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={hasLux}
            onChange={(e) => setHasLux(e.target.checked)}
          />
          Has lux sensor
        </label>
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
            disabled={update.isPending}
            className="px-3 py-1 text-sm bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white rounded"
          >
            {update.isPending ? 'Saving…' : 'Save'}
          </button>
        </div>
      </form>
    </Modal>
  );
}
