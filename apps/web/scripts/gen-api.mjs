#!/usr/bin/env node
// Generates the web's view of the API from the spec contracts (specs/*/contracts/*.yaml):
//   src/api/schema.d.ts      types (openapi-typescript)
//   src/lib/contract.gen.ts  runtime values types cannot carry: enum value lists, constraints
//                            (min/max, lengths, item counts, patterns, defaults) on schema
//                            properties, query parameters and request bodies, and the `x-`
//                            extensions of operations
//
// Every spec fragment is merged in memory, including specs the API does not serve yet (the
// repo-level scripts/assemble_contracts.py only assembles contracts/features.txt): every
// cross-file $ref ("./core.yaml#/components/schemas/X",
// "../../001-platform-foundation/contracts/core.yaml#/...") becomes a local ref, identical
// duplicate components merge, and conflicting duplicates are reported.
//
//   node scripts/gen-api.mjs           write both files
//   node scripts/gen-api.mjs --check   exit 1 when either committed file is stale
import { readFileSync, writeFileSync, readdirSync, existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parse } from "yaml";
import openapiTS, { astToString } from "openapi-typescript";

const here = dirname(fileURLToPath(import.meta.url));
const webRoot = resolve(here, "..");
const repoRoot = resolve(webRoot, "../..");
const specsDir = join(repoRoot, "specs");
const outFile = join(webRoot, "src/api/schema.d.ts");
const valuesFile = join(webRoot, "src/lib/contract.gen.ts");
const check = process.argv.includes("--check");

/** Rewrites every $ref that points into another file to a local "#/..." ref. */
function localizeRefs(node) {
  if (Array.isArray(node)) return node.map(localizeRefs);
  if (node && typeof node === "object") {
    const out = {};
    for (const [k, v] of Object.entries(node)) {
      if (k === "$ref" && typeof v === "string" && v.includes("#") && !v.startsWith("#")) {
        out[k] = v.slice(v.indexOf("#"));
      } else {
        out[k] = localizeRefs(v);
      }
    }
    return out;
  }
  return node;
}

const same = (a, b) => JSON.stringify(sortDeep(a)) === JSON.stringify(sortDeep(b));
function sortDeep(v) {
  if (Array.isArray(v)) return v.map(sortDeep);
  if (v && typeof v === "object") {
    return Object.fromEntries(
      Object.keys(v)
        .sort()
        .map((k) => [k, sortDeep(v[k])]),
    );
  }
  return v;
}

const merged = {
  openapi: "3.1.0",
  info: { title: "Callwright API (assembled for apps/web)", version: "1.0.0" },
  servers: [{ url: "/v1" }],
  paths: {},
  components: {},
};
const conflicts = [];
const sources = [];

const specDirs = readdirSync(specsDir, { withFileTypes: true })
  .filter((d) => d.isDirectory() && /^\d{3}-/.test(d.name))
  .map((d) => d.name)
  .sort();

for (const spec of specDirs) {
  const cdir = join(specsDir, spec, "contracts");
  if (!existsSync(cdir)) continue;
  const files = readdirSync(cdir)
    .filter((f) => f.endsWith(".yaml") || f.endsWith(".yml"))
    .sort();
  for (const file of files) {
    const rel = `${spec}/contracts/${file}`;
    let doc;
    try {
      doc = localizeRefs(parse(readFileSync(join(cdir, file), "utf8")));
    } catch (err) {
      conflicts.push(`${rel}: unreadable YAML (${err.message})`);
      continue;
    }
    sources.push(rel);
    for (const [path, item] of Object.entries(doc.paths ?? {})) {
      const existing = merged.paths[path];
      if (!existing) {
        merged.paths[path] = item;
        continue;
      }
      for (const [method, op] of Object.entries(item)) {
        if (existing[method] && !same(existing[method], op)) {
          conflicts.push(`${rel}: duplicate operation ${method.toUpperCase()} ${path}`);
        } else {
          existing[method] = op;
        }
      }
    }
    for (const [section, entries] of Object.entries(doc.components ?? {})) {
      merged.components[section] ??= {};
      for (const [name, value] of Object.entries(entries ?? {})) {
        const prev = merged.components[section][name];
        if (prev === undefined) merged.components[section][name] = value;
        else if (!same(prev, value)) conflicts.push(`${rel}: components.${section}.${name} differs from an earlier fragment (first one kept)`);
      }
    }
  }
}

/**
 * openapi-typescript makes a property with a `default` non-optional, which is right for responses
 * (the server fills it) but wrong for what a caller sends. Schemas reached only from request
 * bodies keep the default as documentation without making the property required.
 */
function requestOnlyDefaults(doc) {
  const refsIn = (node, out = new Set()) => {
    if (Array.isArray(node)) node.forEach((n) => refsIn(n, out));
    else if (node && typeof node === "object") {
      for (const [k, v] of Object.entries(node)) {
        if (k === "$ref" && typeof v === "string" && v.startsWith("#/components/schemas/")) out.add(v.split("/").pop());
        else refsIn(v, out);
      }
    }
    return out;
  };
  const closure = (names) => {
    const seen = new Set();
    const todo = [...names];
    while (todo.length) {
      const n = todo.pop();
      if (seen.has(n)) continue;
      seen.add(n);
      todo.push(...refsIn(doc.components.schemas?.[n]));
    }
    return seen;
  };
  const ops = Object.values(doc.paths).flatMap((item) => Object.values(item).filter((op) => op && typeof op === "object"));
  const fromResponses = closure(refsIn([ops.map((op) => op.responses), doc.components.responses]));
  const requestOnly = [...closure(refsIn(ops.map((op) => op.requestBody)))].filter((n) => !fromResponses.has(n));
  const optional = (schema) => {
    if (Array.isArray(schema)) return schema.forEach(optional);
    if (!schema || typeof schema !== "object") return;
    for (const [k, v] of Object.entries(schema)) {
      if (k === "properties" && v && typeof v === "object") {
        for (const [name, prop] of Object.entries(v)) {
          if (prop && typeof prop === "object" && "default" in prop && !(schema.required ?? []).includes(name)) {
            prop.description = [prop.description, `Default: ${JSON.stringify(prop.default)}`].filter(Boolean).join(". ");
            delete prop.default;
          }
        }
      }
      optional(v);
    }
  };
  for (const n of requestOnly) optional(doc.components.schemas[n]);
  for (const op of ops) optional(op.requestBody);
  return doc;
}

const ast = await openapiTS(requestOnlyDefaults(structuredClone(merged)), { alphabetize: false, exportType: false });
const header = [
  "/**",
  " * Generated by apps/web/scripts/gen-api.mjs from specs/*/contracts/*.yaml. Do not edit.",
  ` * Sources: ${sources.length} contract fragments.`,
  " */",
  "",
].join("\n");
const output = header + astToString(ast);

// Later specs carry local copies of 001's shared components (Problem, PageMeta, ...). 001 is
// processed first, so its definitions win; report the differing names once, grouped.
if (conflicts.length) {
  const names = new Map();
  for (const c of conflicts) {
    const m = c.match(/components\.(\w+)\.(\w+)/);
    const key = m ? `${m[1]}.${m[2]}` : c;
    names.set(key, (names.get(key) ?? 0) + 1);
  }
  console.warn(
    `warn: ${conflicts.length} duplicate definitions differ from the first fragment (first kept): ` +
      [...names.entries()].map(([k, n]) => `${k} x${n}`).join(", "),
  );
}

/** Constraint keywords copied into contract.gen.ts, plus every `x-` extension. */
const CONSTRAINTS = [
  "minimum",
  "maximum",
  "exclusiveMinimum",
  "exclusiveMaximum",
  "minLength",
  "maxLength",
  "minItems",
  "maxItems",
  "pattern",
  "enum",
  "default",
];

function constraintsOf(schema) {
  if (!schema || typeof schema !== "object") return null;
  const out = {};
  // Beside a $ref only extensions belong to this property; the rest describes the referenced schema.
  if (!schema.$ref) for (const k of CONSTRAINTS) if (schema[k] !== undefined) out[k] = schema[k];
  for (const [k, v] of Object.entries(schema)) if (k.startsWith("x-")) out[k] = v;
  const items = schema.items ? constraintsOf(schema.items) : null;
  if (items) out.items = items;
  return Object.keys(out).length ? out : null;
}

/** Properties of an object schema, following allOf parts that are inline objects. */
function propertiesOf(schema) {
  const props = { ...(schema.properties ?? {}) };
  for (const part of schema.allOf ?? []) Object.assign(props, part.properties ?? {});
  return props;
}

function contractValues() {
  const enums = {};
  const scalars = {};
  const schemas = {};
  for (const [name, schema] of Object.entries(merged.components.schemas ?? {})) {
    if (Array.isArray(schema.enum)) {
      enums[name] = schema.enum;
      const ext = Object.fromEntries(Object.entries(schema).filter(([k]) => k.startsWith("x-")));
      if (Object.keys(ext).length) scalars[name] = ext;
    } else if (schema.type && schema.type !== "object" && schema.type !== "array") {
      const c = constraintsOf(schema);
      if (c) scalars[name] = c;
    }
    const props = {};
    for (const [prop, ps] of Object.entries(propertiesOf(schema))) {
      const c = constraintsOf(ps);
      if (c) props[prop] = c;
    }
    if (Object.keys(props).length) schemas[name] = props;
  }
  const dataChannelTopics = {};
  for (const [name, schema] of Object.entries(merged.components.schemas ?? {})) {
    const topic = schema["x-data-channel"]?.topic;
    if (topic) dataChannelTopics[name] = topic;
  }
  const queries = {};
  const bodies = {};
  const extensions = {};
  for (const [path, item] of Object.entries(merged.paths)) {
    for (const [method, op] of Object.entries(item)) {
      if (!op || typeof op !== "object" || method === "parameters") continue;
      const key = `${method.toUpperCase()} ${path}`;
      const params = {};
      for (const p of [...(item.parameters ?? []), ...(op.parameters ?? [])]) {
        const param = p.$ref ? merged.components.parameters?.[p.$ref.split("/").pop()] : p;
        if (param?.in !== "query") continue;
        const c = constraintsOf(param.schema);
        if (c) params[param.name] = c;
      }
      if (Object.keys(params).length) queries[key] = params;
      let body = op.requestBody?.content?.["application/json"]?.schema;
      if (body?.$ref) body = merged.components.schemas?.[body.$ref.split("/").pop()];
      const bodyProps = {};
      for (const [prop, ps] of Object.entries(body ? propertiesOf(body) : {})) {
        const c = constraintsOf(ps);
        if (c) bodyProps[prop] = c;
      }
      if (Object.keys(bodyProps).length) bodies[key] = bodyProps;
      const ext = Object.fromEntries(Object.entries(op).filter(([k]) => k.startsWith("x-")));
      if (Object.keys(ext).length) extensions[key] = ext;
    }
  }
  const sorted = (o) =>
    Object.fromEntries(
      Object.keys(o)
        .sort()
        .map((k) => [k, o[k]]),
    );
  const block = (name, doc, value) => `/** ${doc} */\nexport const ${name} = ${JSON.stringify(sorted(value), null, 2)} as const;\n`;
  return [
    "/**",
    " * Generated by apps/web/scripts/gen-api.mjs from the spec contract fragments. Do not edit.",
    " * Values the types in src/api/schema.d.ts cannot carry at runtime. No imports, so any layer may read it.",
    " */",
    "",
    block("enums", "Every named enum schema, in contract order.", enums),
    block("scalarLimits", "Constraints on named string and number schemas (ids, names, phone numbers), and enum extensions.", scalars),
    block("schemaLimits", "Constraints on the properties of named schemas.", schemas),
    block("queryLimits", 'Constraints on query parameters, by "METHOD /path".', queries),
    block("bodyLimits", 'Constraints on JSON request body properties, by "METHOD /path".', bodies),
    block("dataChannelTopics", "The data-channel topic each worker message schema is published on (`x-data-channel.topic`).", dataChannelTopics),
    block("operationExtensions", 'The `x-` extensions of each operation, by "METHOD /path".', extensions),
  ].join("\n");
}

const values = contractValues();

if (check) {
  const current = existsSync(outFile) ? readFileSync(outFile, "utf8") : "";
  const currentValues = existsSync(valuesFile) ? readFileSync(valuesFile, "utf8") : "";
  if (current !== output || currentValues !== values) {
    console.error("src/api/schema.d.ts or src/lib/contract.gen.ts is stale; run pnpm gen:api");
    process.exit(1);
  }
  console.log("src/api/schema.d.ts and src/lib/contract.gen.ts are up to date");
} else {
  writeFileSync(outFile, output);
  writeFileSync(valuesFile, values);
  console.log(`wrote ${outFile} and ${valuesFile} from ${sources.length} fragments, ${Object.keys(merged.paths).length} paths`);
}
