/**
 * The island: fetch the report, pick two layers, lay it out with ELK, render with React Flow.
 *
 * The one thing worth arguing about: what a re-layout is allowed to do. Switching layers changes
 * only the TEXT inside stages — the topology is fixed by the design, which is the whole premise —
 * so the layout is computed ONCE per report and reused. Re-running ELK on every dropdown change
 * would make boxes jump for no reason and destroy the comparison the page exists for.
 */
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Edge as RFEdge,
} from "@xyflow/react";
import { useCallback, useEffect, useMemo, useState } from "react";

import type { Binding, Layer, WorkflowReport } from "./contract";
import { END_ID, START_ID } from "./contract";
import { layoutGraph, type Placed } from "./layout";
import { nodeTypes, type WsNode } from "./nodes";
import { Panel } from "./Panel";

const EMPTY: Binding = { impl: null, unbound: true };

function bindingOf(layer: Layer | undefined, id: string): Binding {
  return layer?.bindings?.[id] ?? EMPTY;
}

function Canvas({ report }: { report: WorkflowReport }) {
  const layers = report.layers ?? [];
  const [a, setA] = useState(layers[0]?.name ?? "");
  const [b, setB] = useState(layers[Math.min(1, layers.length - 1)]?.name ?? "");
  const [picked, setPicked] = useState<string | null>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<WsNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<RFEdge>([]);
  const { fitView } = useReactFlow();
  // ⛔ STATE, NOT A REF. This was a `useRef`, and the island mounted with ZERO nodes: ELK resolves
  // asynchronously, the ref was filled inside the promise, and assigning a ref triggers no
  // re-render — so the effect that builds the nodes had already run once against `null` and never
  // ran again. React Flow rendered its wrapper and nothing inside it, which looks like an empty
  // workflow rather than a bug. Caught by `test_react_flow_actually_rendered_the_nodes`.
  const [placed, setPlaced] = useState<Map<string, Placed> | null>(null);

  const layerA = layers.find((l) => l.name === a);
  const layerB = layers.find((l) => l.name === b);

  const varies = useMemo(
    () =>
      new Set(
        report.nodes
          .filter((n) => bindingOf(layerA, n.id).impl !== bindingOf(layerB, n.id).impl)
          .map((n) => n.id),
      ),
    [report.nodes, layerA, layerB],
  );

  // ── layout: once per report, never per layer change ──────────────────────────────────────
  useEffect(() => {
    let live = true;
    const lines = (id: string) =>
      id === START_ID || id === END_ID ? 0 : varies.has(id) ? 2 : 1;
    layoutGraph(report.nodes, report.edges, lines).then((placed) => {
      if (!live) return;
      setPlaced(placed);
      setEdges(
        report.edges.map((e, i) => ({
          id: e.id || `e${i}`,
          source: e.source,
          target: e.target,
          label: e.variable ?? undefined,
          animated: false,
          style: { stroke: "#3d4a70", strokeWidth: 1.6 },
        })),
      );
      setTimeout(() => fitView({ padding: 0.15, duration: 0 }), 0);
    });
    return () => {
      live = false;
    };
    // Deliberately NOT keyed on `varies`: topology is fixed by the design, so a layer switch
    // must not move a single box.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [report, setEdges, fitView]);

  // ── the text inside the boxes, which DOES follow the dropdowns ───────────────────────────
  useEffect(() => {
    if (!placed) return;
    const at = (id: string) => placed.get(id) ?? { x: 0, y: 0, width: 0, height: 0 };
    const out: WsNode[] = [
      { id: START_ID, type: "term", position: at(START_ID), data: { label: "START" },
        draggable: false, selectable: false },
      { id: END_ID, type: "term", position: at(END_ID), data: { label: "END" },
        draggable: false, selectable: false },
    ];
    for (const n of report.nodes) {
      const ba = bindingOf(layerA, n.id);
      const bb = bindingOf(layerB, n.id);
      const differs = varies.has(n.id);
      out.push({
        id: n.id,
        type: "stage",
        position: at(n.id),
        data: {
          id: n.id,
          varies: differs,
          shown: differs
            ? [{ layer: a, binding: ba }, { layer: b, binding: bb }]
            : [{ layer: a, binding: ba }],
          latency: layerA?.latency?.[n.id],
        },
      });
    }
    setNodes(out);
  }, [report.nodes, placed, layerA, layerB, a, b, varies, setNodes]);

  const onNodeClick = useCallback((_: unknown, n: { id: string }) => {
    setPicked(n.id === START_ID || n.id === END_ID ? null : n.id);
  }, []);

  return (
    <div className="ws-root">
      <div className="ws-bar">
        <label>
          <span>Layer A</span>
          <select value={a} onChange={(e) => setA(e.target.value)}>
            {layers.map((l) => (
              <option key={l.name} value={l.name}>{l.name}</option>
            ))}
          </select>
        </label>
        <label>
          <span>Layer B</span>
          <select value={b} onChange={(e) => setB(e.target.value)}>
            {layers.map((l) => (
              <option key={l.name} value={l.name}>{l.name}</option>
            ))}
          </select>
        </label>
      </div>
      <div className="ws-varies-line" data-testid="varies">
        {varies.size === 0
          ? "nothing differs — same bindings on every stage (a replicate)"
          : `${[...varies].join(" · ")} — ${varies.size} of ${report.nodes.length} stages differ`}
      </div>
      <div className="ws-canvas">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={onNodeClick}
          onPaneClick={() => setPicked(null)}
          fitView
          minZoom={0.2}
          maxZoom={2}
          proOptions={{ hideAttribution: true }}
          className="ws-flow"
        >
          <Background color="#1e2743" gap={22} />
          <Controls showInteractive={false} />
          <MiniMap pannable zoomable className="ws-mini" nodeColor={(n) =>
            (n.data as { varies?: boolean }).varies ? "#fbbf24" : "#2a3352"} />
        </ReactFlow>
      </div>
      <Panel report={report} layers={layers} a={a} b={b} varies={varies} picked={picked} />
    </div>
  );
}

export function App({ reportUrl }: { reportUrl: string }) {
  const [report, setReport] = useState<WorkflowReport | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch(reportUrl)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then(setReport)
      // ⚠️ Say what failed. A blank canvas reads as "a workflow with nothing in it", which is the
      // one thing it must never be mistaken for.
      .catch((e) => setError(String(e?.message ?? e)));
  }, [reportUrl]);

  if (error) return <div className="ws-error">could not load {reportUrl} — {error}</div>;
  if (!report) return <div className="ws-loading">loading…</div>;
  return (
    <ReactFlowProvider>
      <Canvas report={report} />
    </ReactFlowProvider>
  );
}
