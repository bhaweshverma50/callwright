// The mock API's demo account for the screenshot and recording scripts, read from the one place
// that defines it (src/mocks/demoAccount.ts), which plain Node cannot import as TypeScript.
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/mocks/demoAccount.ts", import.meta.url), "utf8");
const value = (name) => {
  const m = new RegExp(`export const ${name} = "([^"]+)";`).exec(source);
  if (!m) throw new Error(`src/mocks/demoAccount.ts no longer defines ${name} as a string`);
  return m[1];
};

export const DEMO = { email: value("DEMO_EMAIL"), password: value("DEMO_PASSWORD") };
