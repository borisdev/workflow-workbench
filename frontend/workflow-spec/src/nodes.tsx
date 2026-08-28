/** The two node types: a stage, and a terminal. All semantics come from the payload. */
import { Handle, Position, type Node as RFNode, type NodeProps } from "@xyflow/react";

import type { Binding } from "./contract";

export type StageData = {
  id: string;
  /** [layer name, binding] for the two selected layers. One entry when they agree. */
  shown: Array<{ layer: string; binding: Binding }>;
  varies: boolean;
  /** Seconds, from the A layer. undefined = nobody measured, which must not render as 0. */
  latency?: number;
};
export type TermData = { label: string };

export type WsNode = RFNode<StageData, "stage"> | RFNode<TermData, "term">;

/** ⚠️ Three states, three renderings. `unbound` is not a quieter `skipped` — one is a decision
 *  the strategy made, the other is a stage nobody wired, and collapsing them is the
 *  NOT CHECKED / 0 FOUND failure in miniature. */
function implText(b: Binding) {
  if (b.unbound) return <span className="ws-unbound">UNBOUND</span>;
  if (b.skipped) return <span className="ws-skip">— skipped</span>;
  return <span className="ws-impl">{b.impl}</span>;
}

export function StageView({ data, selected }: NodeProps<RFNode<StageData, "stage">>) {
  const cls = ["ws-node", data.varies ? "ws-varies" : "ws-shared", selected ? "ws-sel" : ""]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={cls}>
      <Handle type="target" position={Position.Top} />
      <div className="ws-name">{data.id}</div>
      {data.shown.map(({ layer, binding }, i) => (
        <div key={layer} className={`ws-line ${data.shown.length > 1 ? `ws-l${i}` : ""}`}>
          {data.shown.length > 1 && <span className="ws-layer">{layer}</span>}
          {implText(binding)}
        </div>
      ))}
      {/* Absent latency prints NOTHING rather than 0.0s — a stage nobody timed is not a fast one. */}
      {data.latency != null && <div className="ws-lat">{data.latency.toFixed(1)}s</div>}
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}

export function TermView({ data }: NodeProps<RFNode<TermData, "term">>) {
  return (
    <div className="ws-term">
      <Handle type="target" position={Position.Top} />
      {data.label}
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}

export const nodeTypes = { stage: StageView, term: TermView };
