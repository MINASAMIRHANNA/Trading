import { useMemo, useState, type ReactNode } from "react";

type Tone = "neutral" | "good" | "bad" | "warn" | "info";

export function SectionHeader(props: { title: string; subtitle?: string; right?: ReactNode }) {
  return (
    <div className="section-header">
      <div>
        <h2>{props.title}</h2>
        {props.subtitle ? <p>{props.subtitle}</p> : null}
      </div>
      {props.right ? <div className="section-header-right">{props.right}</div> : null}
    </div>
  );
}

export function Panel(props: { title?: string; subtitle?: string; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`mina-panel${props.className ? ` ${props.className}` : ""}`}>
      {props.title ? (
        <div className="panel-head">
          <div>
            <h3>{props.title}</h3>
            {props.subtitle ? <p>{props.subtitle}</p> : null}
          </div>
          {props.right ? <div>{props.right}</div> : null}
        </div>
      ) : null}
      <div>{props.children}</div>
    </section>
  );
}

export function KpiCard(props: { label: string; value: ReactNode; hint?: ReactNode; tone?: Tone }) {
  return (
    <div className={`kpi-card tone-${props.tone || "neutral"}`}>
      <div className="kpi-label">{props.label}</div>
      <div className="kpi-value">{props.value}</div>
      {props.hint ? <div className="kpi-hint">{props.hint}</div> : null}
    </div>
  );
}

export function StatCard(props: { label: string; value: ReactNode; hint?: ReactNode; tone?: Tone }) {
  return <KpiCard {...props} />;
}

export function StatusBadge(props: { text: ReactNode; tone?: Tone }) {
  return <span className={`status-badge tone-${props.tone || "neutral"}`}>{props.text}</span>;
}

export function StatusPill(props: { text: ReactNode; tone?: Tone }) {
  return <StatusBadge {...props} />;
}

export function Tabs(props: {
  value: string;
  items: Array<{ key: string; label: ReactNode }>;
  onChange: (next: string) => void;
  className?: string;
}) {
  return (
    <div className={`filters-row${props.className ? ` ${props.className}` : ""}`}>
      {props.items.map((item) => (
        <button
          key={item.key}
          className={`action-btn${props.value === item.key ? " primary" : ""}`}
          onClick={() => props.onChange(item.key)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

export function DateRangePickerUTC(props: {
  from: string;
  to: string;
  onFromChange: (next: string) => void;
  onToChange: (next: string) => void;
  onApply?: () => void;
  className?: string;
}) {
  return (
    <div className={`filters-row${props.className ? ` ${props.className}` : ""}`}>
      <input
        className="dark-input"
        type="datetime-local"
        value={props.from}
        onChange={(e) => props.onFromChange(e.target.value)}
      />
      <input
        className="dark-input"
        type="datetime-local"
        value={props.to}
        onChange={(e) => props.onToChange(e.target.value)}
      />
      {props.onApply ? (
        <button className="action-btn primary" onClick={() => props.onApply?.()}>
          Apply UTC
        </button>
      ) : null}
    </div>
  );
}

export function TerminalBox(props: { lines: Array<{ level?: string; message: ReactNode; ts?: ReactNode; source?: ReactNode }>; maxHeight?: number }) {
  return (
    <div className="terminal-box" style={{ maxHeight: props.maxHeight ? `${props.maxHeight}px` : "320px" }}>
      {props.lines.length === 0 ? (
        <div className="terminal-empty">No logs yet.</div>
      ) : (
        props.lines.map((line, idx) => (
          <div className="log-line" key={idx}>
            <span className={`log-level lvl-${(line.level || "INFO").toUpperCase()}`}>{line.level || "INFO"}</span>
            <span className="log-ts">{line.ts ?? "—"}</span>
            {line.source ? <span className="log-source">{line.source}</span> : null}
            <span className="log-message">{line.message}</span>
          </div>
        ))
      )}
    </div>
  );
}

export function LogViewer(props: { lines: Array<{ level?: string; message: ReactNode; ts?: ReactNode; source?: ReactNode }>; maxHeight?: number }) {
  return <TerminalBox {...props} />;
}

type Column<T> = {
  key: string;
  title: ReactNode;
  render: (row: T) => ReactNode;
  align?: "left" | "right" | "center";
  width?: string;
  sortValue?: (row: T) => string | number;
};

export function DataTable<T>(props: {
  columns: Array<Column<T>>;
  rows: T[];
  emptyText?: string;
  className?: string;
  pageSize?: number;
  enableCopy?: boolean;
}) {
  const [sortKey, setSortKey] = useState<string>("");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [page, setPage] = useState(1);
  const pageSize = Math.max(1, Number(props.pageSize || 25));

  const sortedRows = useMemo(() => {
    if (!sortKey) return props.rows;
    const col = props.columns.find((c) => c.key === sortKey);
    if (!col) return props.rows;
    const arr = [...props.rows];
    arr.sort((a, b) => {
      const av = col.sortValue ? col.sortValue(a) : (a as any)?.[sortKey];
      const bv = col.sortValue ? col.sortValue(b) : (b as any)?.[sortKey];
      const an = Number(av);
      const bn = Number(bv);
      let cmp = 0;
      if (Number.isFinite(an) && Number.isFinite(bn)) cmp = an - bn;
      else cmp = String(av ?? "").localeCompare(String(bv ?? ""));
      return sortDir === "asc" ? cmp : -cmp;
    });
    return arr;
  }, [props.rows, props.columns, sortKey, sortDir]);

  const totalPages = Math.max(1, Math.ceil(sortedRows.length / pageSize));
  const currentPage = Math.min(page, totalPages);
  const pageRows = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return sortedRows.slice(start, start + pageSize);
  }, [sortedRows, currentPage, pageSize]);

  const onSort = (key: string) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
      return;
    }
    setSortKey(key);
    setSortDir("asc");
    setPage(1);
  };

  const copyRow = async (row: T) => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(row, null, 2));
    } catch {
      // ignore copy failures
    }
  };

  return (
    <div className={`table-wrap${props.className ? ` ${props.className}` : ""}`}>
      <div className="table-toolbar">
        <span className="muted">{props.rows.length} rows</span>
        <div className="filters-row">
          <button className="mini-btn" disabled={currentPage <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
            Prev
          </button>
          <span className="muted">
            {currentPage}/{totalPages}
          </span>
          <button className="mini-btn" disabled={currentPage >= totalPages} onClick={() => setPage((p) => Math.min(totalPages, p + 1))}>
            Next
          </button>
        </div>
      </div>
      <table className="mina-table">
        <thead>
          <tr>
            {props.columns.map((col) => (
              <th key={col.key} style={{ textAlign: col.align || "left", width: col.width }}>
                <button className="th-sortable" onClick={() => onSort(col.key)}>
                  <span>{col.title}</span>
                  {sortKey === col.key ? <span>{sortDir === "asc" ? " ▲" : " ▼"}</span> : null}
                </button>
              </th>
            ))}
            {props.enableCopy ? <th style={{ textAlign: "right", width: "80px" }}>Copy</th> : null}
          </tr>
        </thead>
        <tbody>
          {pageRows.length === 0 ? (
            <tr>
              <td colSpan={props.columns.length + (props.enableCopy ? 1 : 0)} className="table-empty">
                {props.emptyText || "No data yet."}
              </td>
            </tr>
          ) : (
            pageRows.map((row, idx) => (
              <tr key={idx}>
                {props.columns.map((col) => (
                  <td key={col.key} style={{ textAlign: col.align || "left" }}>
                    {col.render(row)}
                  </td>
                ))}
                {props.enableCopy ? (
                  <td style={{ textAlign: "right" }}>
                    <button className="mini-btn" onClick={() => void copyRow(row)}>
                      Copy
                    </button>
                  </td>
                ) : null}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

export function formatNum(v: unknown, digits = 2): string {
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

export function toneFromValue(v: unknown): Tone {
  const n = Number(v);
  if (!Number.isFinite(n)) return "neutral";
  if (n > 0) return "good";
  if (n < 0) return "bad";
  return "neutral";
}
