/**
 * ELK hierarchical layout, top-to-bottom.
 *
 * Layout is the one thing the server does NOT decide — the payload carries no coordinates, and it
 * should not: a stage's position is a property of how you are looking at it, not of the design.
 */
import ELK from "elkjs/lib/elk.bundled.js";

import type { Edge, Node } from "./contract";
import { END_ID, START_ID } from "./contract";

const elk = new ELK();

export const NODE_WIDTH = 210;

export interface Placed {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** Terminals are small pills; a stage grows with how many implementations it has to show. */
function nodeHeight(id: string, lines: number): number {
  if (id === START_ID || id === END_ID) return 34;
  return 46 + lines * 17;
}

export async function layoutGraph(
  nodes: Node[],
  edges: Edge[],
  linesFor: (id: string) => number,
): Promise<Map<string, Placed>> {
  const ids = [START_ID, ...nodes.map((n) => n.id), END_ID];
  const result = await elk.layout({
    id: "root",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": "DOWN",
      "elk.edgeRouting": "POLYLINE",
      "elk.layered.spacing.nodeNodeBetweenLayers": "70",
      "elk.spacing.nodeNode": "40",
      "elk.layered.crossingMinimization.strategy": "LAYER_SWEEP",
      "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
    },
    children: ids.map((id) => ({
      id,
      width: id === START_ID || id === END_ID ? 90 : NODE_WIDTH,
      height: nodeHeight(id, linesFor(id)),
    })),
    edges: edges.map((e, i) => ({
      id: e.id || `e${i}`,
      sources: [e.source],
      targets: [e.target],
    })),
  });

  const placed = new Map<string, Placed>();
  for (const child of result.children ?? []) {
    placed.set(child.id, {
      x: child.x ?? 0,
      y: child.y ?? 0,
      width: child.width ?? NODE_WIDTH,
      height: child.height ?? 60,
    });
  }
  return placed;
}
