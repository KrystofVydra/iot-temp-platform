import { formatDistanceToNow } from 'date-fns';
import type { NodeOut } from '../lib/types';

const ONLINE_WINDOW_MS = 5 * 60_000;

const ERR_LABEL: Record<string, string> = {
  comms: 'Comms failure',
  lux: 'Lux sensor',
  temp: 'Temp sensor',
  both: 'Both sensors',
};

function nodeOnline(n: NodeOut): boolean {
  return (
    !!n.last_seen_at &&
    Date.now() - new Date(n.last_seen_at).getTime() < ONLINE_WINDOW_MS
  );
}

type Props = {
  node: NodeOut;
  actions?: React.ReactNode;
};

export function NodeTile({ node, actions }: Props) {
  const online = nodeOnline(node);
  const title = node.name?.trim() || `Node ${node.node_index}`;
  const errLabel = node.latest.err ? ERR_LABEL[node.latest.err] ?? node.latest.err : null;

  return (
    <div className="bg-white rounded-lg shadow-sm p-3">
      <div className="flex justify-between items-start mb-2 gap-2">
        <div className="min-w-0">
          <div className="font-semibold truncate">{title}</div>
          <div className="text-xs text-gray-500">#{node.node_index}</div>
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

      <div className="text-2xl font-light">
        {node.latest.temperature !== null
          ? `${node.latest.temperature.toFixed(1)}°C`
          : '—'}
      </div>

      {node.has_lux && (
        <div className="text-xs text-gray-500 mt-1">
          {node.latest.lux !== null ? `${node.latest.lux} lx` : 'lux —'}
        </div>
      )}

      {errLabel && (
        <div className="mt-2">
          <span className="text-xs px-2 py-0.5 rounded bg-red-100 text-red-700">
            ⚠ {errLabel}
          </span>
        </div>
      )}

      <div className="text-xs text-gray-400 mt-2">
        {node.latest.time
          ? formatDistanceToNow(new Date(node.latest.time), {
              addSuffix: true,
            })
          : 'No data'}
      </div>

      {actions && <div className="mt-3 pt-3 border-t flex gap-2">{actions}</div>}
    </div>
  );
}
