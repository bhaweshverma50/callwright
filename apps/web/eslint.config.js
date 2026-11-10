import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";
import prettier from "eslint-config-prettier";

const lazyTokenBan = {
  "no-restricted-syntax": [
    "error",
    {
      selector: "CallExpression[callee.name='useLazyToken']",
      message:
        "FR-020: optional-feature credentials are minted on first use only. Call useLazyToken inside the feature component, never in the shell or on page load.",
    },
  ],
};

/** Files under `files` may not import the given top-level folders of src. */
function layer(files, banned, message = `${files} sits below ${banned.join(", ")}: move the shared piece down instead of importing up.`) {
  return {
    files: [files],
    ignores: ["**/*.test.{ts,tsx}"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: banned.flatMap((dir) => [`**/${dir}`, `**/${dir}/**`]),
              message,
            },
          ],
        },
      ],
    },
  };
}

export default tseslint.config(
  { ignores: ["dist", "coverage", "playwright-report", "test-results", "docs", "public/mockServiceWorker.js", "src/api/schema.d.ts"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2023,
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
      "react-refresh/only-export-components": "off",
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
      "@typescript-eslint/consistent-type-imports": "error",
      "no-irregular-whitespace": "error",
    },
  },
  {
    // T098: the shell and the top-level router never request feature tokens.
    files: ["src/app/Shell.tsx", "src/app/TopBar.tsx", "src/app/Sidebar.tsx", "src/router.tsx", "src/main.tsx"],
    rules: lazyTokenBan,
  },
  // Layers, lowest first: lib < api < components < webCall < app < routes; src/router.tsx, App.tsx
  // and main.tsx compose them. Components may call api (ProblemAlert words a failed request); the app
  // shell (assistant bus, voice action registry, theme, tour) is a service the pages register with,
  // so routes sit above it. Mocks serve the contract from api and lib only, and only main.tsx and
  // tests load them: no layer imports mocks. Tests may reach anywhere.
  layer("src/lib/**", ["api", "components", "webCall", "app", "routes", "mocks"]),
  layer("src/api/**", ["components", "webCall", "app", "routes", "mocks"]),
  layer("src/components/**", ["webCall", "app", "routes", "mocks"]),
  layer("src/webCall/**", ["app", "routes", "mocks"]),
  layer("src/app/**", ["routes", "mocks"]),
  layer("src/routes/**", ["mocks"], "Pages never import mocks: main.tsx installs what mock mode needs (see lib/demoHints.ts)."),
  layer("src/mocks/**", ["components", "webCall", "app", "routes"]),
  {
    files: ["scripts/**/*.mjs", "*.config.{js,ts}", "tests/**/*.ts"],
    languageOptions: { globals: globals.node },
  },
  // T005: formatting belongs to Prettier (`pnpm lint` runs `prettier --check`); turn off clashing rules.
  prettier,
);
