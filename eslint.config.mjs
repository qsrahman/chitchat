// The one JavaScript check: names that are used but never defined or imported (the mistake a missing import
// makes, which only shows when that line runs), and imports that are never used. The libraries are classic scripts
// that define globals, so they are declared here. Run by `uv run python scripts/check.py`; needs Node.
const browser = Object.fromEntries(
  ("document window location history fetch localStorage navigator requestAnimationFrame cancelAnimationFrame " +
    "setTimeout clearTimeout URL FormData AbortController TextDecoderStream CSS matchMedia getComputedStyle " +
    "innerWidth performance Option CustomEvent Event EventTarget console DOMPurify marked hljs katex")
    .split(" ").map((name) => [name, "readonly"]),
);

export default [
  { ignores: ["app/static/vendor/**", "tests/**", ".venv/**"] },
  {
    files: ["app/static/**/*.js"],
    languageOptions: { ecmaVersion: "latest", sourceType: "module", globals: browser },
    rules: {
      "no-undef": "error",
      "no-unused-vars": ["error", { args: "none", caughtErrors: "none" }],
      "no-redeclare": "error",
      "no-import-assign": "error",
      "no-dupe-keys": "error",
    },
  },
];
