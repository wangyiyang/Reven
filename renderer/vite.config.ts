import { defineConfig } from "vite";
import { fileURLToPath } from "node:url";

const cssTreeBundle = fileURLToPath(import.meta.resolve("css-tree/dist/csstree.esm.js")).replace(/\.js$/, "");
const sanitizerShim = fileURLToPath(new URL("./src/doocs-sanitizer.ts", import.meta.url));

export default defineConfig({
  resolve: {
    alias: [
      { find: /^css-tree$/, replacement: cssTreeBundle },
      { find: /^isomorphic-dompurify$/, replacement: sanitizerShim },
    ],
  },
  build: {
    ssr: "src/cli.ts",
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        entryFileNames: "cli.mjs",
        inlineDynamicImports: true,
      },
    },
  },
  ssr: {
    noExternal: true,
  },
  test: {
    environment: "node",
  },
});
