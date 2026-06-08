import nextConfig from "eslint-config-next";
import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";
import testingLibrary from "eslint-plugin-testing-library";
import vitest from "eslint-plugin-vitest";

const unitTestFiles = ["**/*.test.ts", "**/*.test.tsx"];

const eslintConfig = [
  ...nextConfig,
  ...nextCoreWebVitals,
  ...nextTypescript,
  {
    ignores: [".next/**", "node_modules/**", "out/**", "build/**"],
  },
  {
    rules: {
      // Downgrade to warn — pre-existing patterns to address incrementally
      "react-hooks/purity": "warn",
      "react-hooks/set-state-in-effect": "warn",
    },
  },
  {
    files: unitTestFiles,
    ...testingLibrary.configs["flat/react"],
    rules: {
      // Antd integration tests legitimately need DOM inspection
      "testing-library/no-container": "warn",
      "testing-library/no-node-access": "warn",
    },
  },
  {
    files: unitTestFiles,
    ...vitest.configs.recommended,
  },
];

export default eslintConfig;
