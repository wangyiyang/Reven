import { createHash } from "node:crypto";
import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import { basename, join, relative, resolve } from "node:path";

const noticeName = /^(licen[cs]e|copying|copyright|notice|authors|ofl)([._-]|$)/i;

function noticeFiles(root) {
  const files = [];
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    if (entry.name === "node_modules" || entry.isSymbolicLink()) continue;
    const path = join(root, entry.name);
    if (entry.isDirectory()) files.push(...noticeFiles(path));
    else if (noticeName.test(entry.name)) files.push(path);
  }
  return files.sort();
}

function packageRoots(store) {
  const roots = new Set();
  for (const entry of readdirSync(store)) {
    const modules = join(store, entry, "node_modules");
    if (!existsSync(modules)) continue;
    for (const name of readdirSync(modules)) {
      const paths = name.startsWith("@")
        ? readdirSync(join(modules, name)).map((child) => join(modules, name, child))
        : [join(modules, name)];
      for (const path of paths) {
        if (!existsSync(join(path, "package.json"))) continue;
        const actual = realpathSync(path);
        if (actual.startsWith(`${store}/`)) roots.add(actual);
      }
    }
  }
  return [...roots].sort();
}

function collectPackage(root, output) {
  const raw = readFileSync(join(root, "package.json"));
  const pkg = JSON.parse(raw);
  const id = `${pkg.name.replaceAll("/", "__")}@${pkg.version}`;
  const evidence = [];
  for (const file of noticeFiles(root)) {
    const destination = join("packages", id, relative(root, file));
    mkdirSync(join(output, destination, ".."), { recursive: true });
    cpSync(file, join(output, destination));
    evidence.push({ path: destination, sha256: createHash("sha256").update(readFileSync(file)).digest("hex") });
  }
  mkdirSync(join(output, "packages", id), { recursive: true });
  writeFileSync(join(output, "packages", id, "package.json"), raw);
  return {
    name: pkg.name, version: pkg.version,
    license: pkg.license ?? pkg.licenses ?? "UNKNOWN",
    source: pkg.repository ?? pkg.homepage ?? "UNKNOWN",
    evidence,
    review: evidence.length ? "text-collected; human review required" : "MISSING LICENSE TEXT; review required",
  };
}

function applySupplemental(packages, project, output) {
  const directory = join(project, "licenses/supplemental/javascript");
  if (!existsSync(join(directory, "inventory.json"))) return;
  const manifest = JSON.parse(readFileSync(join(directory, "inventory.json")));
  for (const entry of manifest.packages) {
    const record = packages.get(`${entry.name}@${entry.version}`);
    if (!record) continue;
    for (const file of entry.evidence) {
      const source = resolve(directory, file.path);
      if (!source.startsWith(`${directory}/`)) throw new Error("Unsafe supplemental license path");
      const bytes = readFileSync(source);
      if (createHash("sha256").update(bytes).digest("hex") !== file.sha256) {
        throw new Error(`Supplemental license checksum mismatch: ${entry.name}`);
      }
      const destination = join("supplemental", file.path);
      mkdirSync(join(output, destination, ".."), { recursive: true });
      writeFileSync(join(output, destination), bytes);
      record.evidence.push({ path: destination, sha256: file.sha256, source: entry.source });
    }
    if (record.license === "UNKNOWN") record.license = entry.license;
    record.review = "supplemental original text collected; human review required";
  }
}

const [projectArg, outputArg] = process.argv.slice(2);
if (!projectArg || !outputArg) throw new Error("usage: node collect-js.mjs PROJECT OUTPUT");
const project = resolve(projectArg);
const output = resolve(outputArg);
const store = realpathSync(join(project, "node_modules/.pnpm"));
mkdirSync(output, { recursive: true });
const packages = new Map();
for (const root of packageRoots(store)) {
  const record = collectPackage(root, output);
  packages.set(`${record.name}@${record.version}`, record);
}
if (!packages.size) throw new Error("no installed pnpm packages found");
applySupplemental(packages, project, output);
const lock = readFileSync(join(project, "pnpm-lock.yaml"));
writeFileSync(join(output, "inventory.json"), JSON.stringify({
  scope: "Installed pnpm workspace dependency superset, including development tools; not bundle reachability",
  platform: `${process.platform}/${process.arch}`,
  lockfile: { path: "pnpm-lock.yaml", sha256: createHash("sha256").update(lock).digest("hex") },
  excluded: "Uninstalled optional/platform dependencies require separate review before redistributing those platforms",
  packages: [...packages.values()].sort((a, b) => `${a.name}@${a.version}`.localeCompare(`${b.name}@${b.version}`)),
}, null, 2) + "\n");
console.log(`Collected ${packages.size} installed package notices in ${basename(output)}`);
