/** Three independent evidence paths converge into one observation. */
export function BrandMark({ className = "size-9" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 40 40"
      fill="none"
      className={className}
      aria-hidden="true"
    >
      <path
        d="M7 8h8l9 12-9 12H7M7 20h17"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="28" cy="20" r="6" stroke="var(--accent)" strokeWidth="2.5" />
      <path
        d="M28 11V7m0 26v-4m9-9h-3"
        stroke="var(--accent)"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  );
}
export type IconName =
  | "simulator"
  | "upload"
  | "connector"
  | "logs"
  | "metrics"
  | "traces"
  | "changes"
  | "dependency"
  | "book";
const paths: Record<IconName, string> = {
  simulator: "M4 17h3l3-10 4 14 3-10 3 6h4",
  upload: "M14 19V5m-5 5 5-5 5 5M5 18v6h18v-6",
  connector: "M9 5v5m10-5v5M7 10h14v4a7 7 0 0 1-14 0v-4m7 11v5",
  logs: "M6 5h16v20H6zM10 10h8m-8 5h8m-8 5h5",
  metrics: "M5 23V5m0 18h19M9 18l5-8 4 4 6-9",
  traces: "M5 6h8v5H5zM15 17h8v5h-8zM9 11v8h6",
  changes: "M8 5v18m0-11h7a5 5 0 0 0 5-5V5M5 5h6M5 23h6m6-18h6",
  dependency: "M4 4h7v7H4zM17 17h7v7h-7zM11 7h9v10M7 11v9h10",
  book: "M14 7C10 4 6 4 3 6v17c4-2 7-2 11 0m0-16c4-3 8-3 11-1v17c-4-2-7-2-11 0V7",
};
export function SignalIcon({
  name,
  className = "size-5",
}: {
  name: IconName;
  className?: string;
}) {
  return (
    <svg
      viewBox="0 0 28 28"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path d={paths[name]} />
    </svg>
  );
}
