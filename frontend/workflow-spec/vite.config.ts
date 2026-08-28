import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// One island, one IIFE bundle, fixed filenames — the Python page hard-codes the two asset paths
// and there is no manifest to read at request time. Output lands in the package's static tree and
// is COMMITTED: `pip install workflow-spec` runs no node step, so an un-built island is a 404.
// Same reasoning as the webapp's causal-graph island, deliberately.
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  // Library mode skips Vite's usual NODE_ENV substitution, so React's `process.env.NODE_ENV`
  // check survives into the bundle and throws `process is not defined` in the browser.
  define: {
    "process.env.NODE_ENV": JSON.stringify(mode === "development" ? "development" : "production"),
  },
  build: {
    outDir: "../../workflow_spec/static",
    emptyOutDir: false,
    sourcemap: false,
    lib: {
      entry: "src/main.tsx",
      name: "WorkflowSpecIsland",
      formats: ["iife"],
      fileName: () => "workflow-spec.js",
      cssFileName: "workflow-spec",
    },
  },
  server: { port: 5175 },
}));
