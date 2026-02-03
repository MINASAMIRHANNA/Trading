// Minimal module declaration for react-plotly.js to satisfy TypeScript.
// We treat Plot component as `any` to avoid version-specific typing issues.

declare module "react-plotly.js" {
  const Plot: any;
  export default Plot;
}
