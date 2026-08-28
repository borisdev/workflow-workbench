/**
 * Everything under the canvas: the bindings matrix, what was measured, and the code.
 *
 * ⚠️ Every optional number renders "not reported" when absent, never 0. `.claude/rules/checks.md`
 * — NOT CHECKED and 0 FOUND must never look the same, and a latency of 0.0s or a score of 0.000
 * is a claim we did not earn.
 */
import type { Layer, WorkflowReport } from "./contract";

const NR = <span className="ws-nr">not reported</span>;

export function Panel({
  report,
  layers,
  a,
  b,
  varies,
  picked,
}: {
  report: WorkflowReport;
  layers: Layer[];
  a: string;
  b: string;
  varies: ReadonlySet<string>;
  picked: string | null;
}) {
  const metrics = [...new Set(layers.flatMap((l) => Object.keys(l.scores ?? {})))];
  const floor = report.noise_floor ?? null;
  const selA = layers.find((l) => l.name === a);
  const selB = layers.find((l) => l.name === b);
  const codeFor = picked ? [selA, selB].filter(Boolean) : [];

  const design = report.design_findings ?? [];

  return (
    <div className="ws-panel">
      {/* ⚠️ A design with findings must never render as a clean one — including a NOT CHECKED
          line, which names a check that did NOT run and is not a pass. */}
      {design.length > 0 && (
        <section className="ws-findings">
          <h3>Design findings</h3>
          <ul>
            {design.map((f) => (
              <li key={f} className={f.startsWith("NOT CHECKED") ? "ws-notchecked" : "ws-bad"}>
                {f}
              </li>
            ))}
          </ul>
        </section>
      )}
      <section>
        <h3>Bindings</h3>
        <div className="ws-scroll">
          <table>
            <thead>
              <tr>
                <th>stage</th>
                {layers.map((l) => <th key={l.name}>{l.name}</th>)}
              </tr>
            </thead>
            <tbody>
              {report.nodes.map((n) => (
                <tr key={n.id}>
                  <td className="ws-mono ws-sticky">{n.id}</td>
                  {layers.map((l) => {
                    const bd = l.bindings?.[n.id];
                    const hot = (l.name === a || l.name === b) && varies.has(n.id);
                    return (
                      <td
                        key={l.name}
                        className={[
                          bd?.unbound ? "ws-unbound" : bd?.skipped ? "ws-skip" : "ws-mono",
                          hot ? "ws-hot" : "",
                        ].filter(Boolean).join(" ")}
                      >
                        {bd?.unbound ? "UNBOUND" : bd?.skipped ? "—" : (bd?.impl ?? "?")}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="ws-sub">
          — = explicitly skipped by that strategy. UNBOUND = nobody wired it, which
          check_bindings refuses.
        </p>
      </section>

      <section className="ws-metrics">
        <h3>Latency &amp; scores</h3>
        <div className="ws-scroll">
          <table>
            <thead>
              <tr>
                <th>strategy</th>
                <th>total latency</th>
                {metrics.map((m) => <th key={m}>{m}</th>)}
              </tr>
            </thead>
            <tbody>
              {layers.map((l) => {
                const lat = l.latency
                  ? Object.values(l.latency).reduce((x, y) => x + (y || 0), 0)
                  : null;
                return (
                  <tr key={l.name}>
                    <td className="ws-mono">{l.name}</td>
                    <td>{lat == null ? NR : `${lat.toFixed(1)}s`}</td>
                    {metrics.map((m) => {
                      const v = l.scores?.[m];
                      if (v == null) return <td key={m}>{NR}</td>;
                      const f = floor?.[m];
                      const noisy = f != null && Math.abs(v) < Math.abs(f);
                      return (
                        <td key={m}>
                          {v.toFixed(3)}
                          {noisy && <span className="ws-pill">inside noise</span>}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="ws-sub">
          {floor
            ? `noise floor: ${JSON.stringify(floor)} — a delta smaller than this is not a result.`
            : "no noise floor reported — no replicate ran, so no delta here is known to mean anything."}
        </p>
      </section>

      <section>
        <h3>Code</h3>
        {!picked && <p className="ws-sub">tap a stage in the graph to see its implementations.</p>}
        {picked &&
          codeFor.map((l) => {
            const bd = l!.bindings?.[picked];
            if (!bd?.code) {
              return (
                <p key={l!.name} className="ws-sub">
                  {l!.name} · {picked} — {bd?.skipped ? "skipped by this strategy" : "no source in the payload"}
                </p>
              );
            }
            return (
              <details key={l!.name} open>
                <summary>
                  {l!.name} · <span className="ws-mono">{picked}</span> →{" "}
                  <span className="ws-mono">{bd.impl}</span>
                  <span className="ws-pill">
                    {(bd.file ?? "").split("/").pop()}:{bd.line ?? 0}
                  </span>
                </summary>
                <pre>{bd.code}</pre>
              </details>
            );
          })}
      </section>
    </div>
  );
}
