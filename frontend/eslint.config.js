import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

export default tseslint.config(
  // ".claude" holds nested agent worktrees, each a full checkout.
  { ignores: ["dist", "coverage", ".claude"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": [
        "warn",
        { allowConstantExport: true },
      ],
    },
  },
  {
    // shadcn-style primitives export their variant helpers (buttonVariants,
    // …) beside the component; the router and test helpers export non-components.
    files: [
      "src/components/ui/**/*.{ts,tsx}",
      "src/test/**/*.{ts,tsx}",
      "src/router.tsx",
      "src/components/shell/workspace-context.tsx",
    ],
    rules: { "react-refresh/only-export-components": "off" },
  },
);
