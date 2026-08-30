/**
 * The wire contract — the TypeScript half of `workflow_workbench/payload.py`.
 *
 * ⚠️ HAND-KEPT IN STEP with the Pydantic model. There is no codegen, so `contract.test`-style
 * drift is possible; the guard is `tests/test_contract_parity.py`, which parses THIS file and
 * asserts every field of every model appears here. A type that exists in one language only is a
 * field somebody will silently stop sending.
 */

/** A named, typed value flowing along an edge. */
export interface Variable {
  name: string;
  type?: string;
}

export interface Node {
  id: string;
  kind?: string;
  inputs?: Variable[];
  outputs?: Variable[];
}

export interface Edge {
  id?: string;
  source: string;
  target: string;
  variable?: string | null;
  type?: string | null;
  /** What ARRIVES at the target when it differs from `variable` — one item of a
   *  fanned-out collection, or a value reshaped on the wire. */
  delivers?: string | null;
}

/**
 * What one strategy puts in one stage.
 *
 * ⚠️ `skipped` and `unbound` are different claims and both are explicit: skipped means this arm
 * deliberately does not run the stage, unbound means nobody wired it. They must never render
 * alike.
 */
export interface Binding {
  impl: string | null;
  skipped?: boolean;
  unbound?: boolean;
  file?: string;
  line?: number;
  code?: string;
}

export interface Layer {
  name: string;
  bindings: Record<string, Binding>;
  /** Absent means NOBODY MEASURED — render "not reported", never 0. */
  latency?: Record<string, number> | null;
  scores?: Record<string, number> | null;
  findings?: string[];
  ok?: boolean;
}

export interface WorkflowReport {
  name?: string;
  input_type?: string;
  output_type?: string;
  nodes: Node[];
  edges: Edge[];
  layers?: Layer[];
  /** The bar a delta must clear. null = no replicate ran, so no number here is a result. */
  noise_floor?: Record<string, number> | null;
  /** Findings about the DESIGN, independent of any strategy. Includes NOT CHECKED lines. */
  design_findings?: string[];
  mermaid?: string;
  meta?: Record<string, unknown>;
}

export const START_ID = "__start__";
export const END_ID = "__end__";
