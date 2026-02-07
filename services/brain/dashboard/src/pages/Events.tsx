import { useEffect, useMemo, useRef, useState } from "react";
import {
  Box,
  Chip,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
  Button,
  TextField,
} from "@mui/material";
import { fetchEvents, openEventsStream, type SharedEvent } from "../api/events";

function typeChip(t: string) {
  const label = t || "-";
  return <Chip size="small" label={label} variant="outlined" />;
}

function summary(data: any) {
  if (!data || typeof data !== "object") return String(data ?? "");
  const trace = data.trace_id || data.traceId;
  const action = data.action || data.event || data.type;
  const msg = data.message || data.msg || data.reason || "";
  const parts = [];
  if (action) parts.push(`action=${action}`);
  if (trace) parts.push(`trace=${trace}`);
  if (msg) parts.push(`msg=${String(msg).slice(0, 120)}`);
  return parts.join(" · ") || "—";
}

export default function Events() {
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState<SharedEvent[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [role, setRole] = useState<string>("all");
  const [etype, setEtype] = useState<string>("all");
  const [q, setQ] = useState<string>("");
  const [traceId, setTraceId] = useState<string>("");

  const [streaming, setStreaming] = useState(false);
  const [streamStatus, setStreamStatus] = useState<string>("offline");
  const esRef = useRef<EventSource | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchEvents({
        role: role === "all" ? undefined : role,
        event_type: etype === "all" ? undefined : etype,
        limit: 200,
        order: "desc",
      });
      if (!res.ok) throw new Error(res.error || "events_error");
      setItems(res.items || []);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Stream toggle
  useEffect(() => {
    if (!streaming) {
      esRef.current?.close();
      esRef.current = null;
      setStreamStatus("offline");
      return;
    }

    const lastId = items.length ? Math.max(...items.map((x) => Number(x.id || 0))) : 0;
    const es = openEventsStream({
      role: role === "all" ? undefined : role,
      event_type: etype === "all" ? undefined : etype,
      since_id: lastId,
      interval_ms: 1000,
    });
    esRef.current = es;

    setStreamStatus("connecting");

    es.onopen = () => setStreamStatus("online");

    es.onerror = () => {
      // Browser will auto-reconnect. Keep status visible.
      setStreamStatus("error/reconnecting");
    };

    es.onmessage = (evt) => {
      try {
        const parsed = JSON.parse(evt.data) as SharedEvent;
        if (!parsed || typeof parsed.id !== "number") return;
        setItems((prev) => {
          const exists = prev.some((p) => p.id === parsed.id);
          if (exists) return prev;
          const next = [parsed, ...prev];
          return next.slice(0, 300);
        });
      } catch {
        // ignore
      }
    };

    // Also listen to typed events (SignalEvent/TradeEvent/HealthEvent)
    const typedHandler = (evt: MessageEvent) => {
      try {
        const parsed = JSON.parse(evt.data) as SharedEvent;
        if (!parsed || typeof parsed.id !== "number") return;
        setItems((prev) => {
          const exists = prev.some((p) => p.id === parsed.id);
          if (exists) return prev;
          const next = [parsed, ...prev];
          return next.slice(0, 300);
        });
      } catch {
        // ignore
      }
    };
    ["SignalEvent", "TradeEvent", "HealthEvent"].forEach((t) => es.addEventListener(t, typedHandler));

    return () => {
      ["SignalEvent", "TradeEvent", "HealthEvent"].forEach((t) => es.removeEventListener(t, typedHandler));
      es.close();
      esRef.current = null;
      setStreamStatus("offline");
    };
    // We intentionally keep dependencies small; switching filters should restart stream manually.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [streaming]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const traceNeedle = traceId.trim().toLowerCase();
    return items.filter((it) => {
      if (role !== "all" && it.bot_role !== role) return false;
      if (etype !== "all" && it.event_type !== etype) return false;
      if (traceNeedle) {
        const trace = String(it?.data?.trace_id || it?.data?.traceId || "").toLowerCase();
        if (!trace.includes(traceNeedle)) return false;
      }
      if (!needle) return true;
      const blob = JSON.stringify(it).toLowerCase();
      return blob.includes(needle);
    });
  }, [items, role, etype, q, traceId]);

  const roles = useMemo(() => {
    const s = new Set<string>();
    items.forEach((it) => it.bot_role && s.add(it.bot_role));
    return Array.from(s).sort();
  }, [items]);

  const etypes = useMemo(() => {
    const s = new Set<string>();
    items.forEach((it) => it.event_type && s.add(it.event_type));
    return Array.from(s).sort();
  }, [items]);

  return (
    <Box>
      <Typography variant="h4" sx={{ mb: 1 }}>
        Events
      </Typography>
      <Typography sx={{ opacity: 0.8, mb: 2 }}>
        Shared event stream (Postgres shared_events). Use this for cross-service tracing.
      </Typography>

      <Box sx={{ display: "flex", gap: 2, flexWrap: "wrap", mb: 2 }}>
        <FormControl sx={{ minWidth: 180 }} size="small">
          <InputLabel>Role</InputLabel>
          <Select label="Role" value={role} onChange={(e: any) => setRole(e.target.value)}>
            <MenuItem value="all">All</MenuItem>
            {roles.map((r) => (
              <MenuItem key={r} value={r}>
                {r}
              </MenuItem>
            ))}
            {/* common roles */}
            {["paper", "live", "pump"].filter((r) => !roles.includes(r)).map((r) => (
              <MenuItem key={r} value={r}>
                {r}
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        <FormControl sx={{ minWidth: 220 }} size="small">
          <InputLabel>Event Type</InputLabel>
          <Select label="Event Type" value={etype} onChange={(e: any) => setEtype(e.target.value)}>
            <MenuItem value="all">All</MenuItem>
            {etypes.map((t) => (
              <MenuItem key={t} value={t}>
                {t}
              </MenuItem>
            ))}
            {["SignalEvent", "TradeEvent", "HealthEvent"].filter((t) => !etypes.includes(t)).map((t) => (
              <MenuItem key={t} value={t}>
                {t}
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        <TextField size="small" label="Trace ID" value={traceId} onChange={(e) => setTraceId(e.target.value)} sx={{ minWidth: 220 }} />
        <TextField size="small" label="Search" value={q} onChange={(e) => setQ(e.target.value)} sx={{ minWidth: 260 }} />

        <Button variant="contained" onClick={load} disabled={loading}>
          {loading ? "Loading…" : "Refresh"}
        </Button>

        <Button
          variant={streaming ? "outlined" : "contained"}
          onClick={() => setStreaming((s) => !s)}
          disabled={loading}
        >
          {streaming ? "Stop Stream" : "Start Stream"}
        </Button>

        <Chip size="small" label={`stream: ${streamStatus}`} variant="outlined" />
      </Box>

      {error ? (
        <Box sx={{ p: 2, border: "1px solid #333", borderRadius: 2, mb: 2 }}>
          <Typography color="error">Error: {error}</Typography>
        </Box>
      ) : null}

      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>ID</TableCell>
            <TableCell>Time (UTC)</TableCell>
            <TableCell>Role</TableCell>
            <TableCell>Type</TableCell>
            <TableCell>Data (preview)</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {filtered.map((it) => (
            <TableRow key={it.id} hover>
              <TableCell>{it.id}</TableCell>
              <TableCell sx={{ whiteSpace: "nowrap" }}>{it.created_at}</TableCell>
              <TableCell>{it.bot_role}</TableCell>
              <TableCell>{typeChip(it.event_type)}</TableCell>
              <TableCell sx={{ maxWidth: 680, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {summary(it.data)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <Typography sx={{ mt: 2, opacity: 0.7 }}>Showing {filtered.length} / {items.length}</Typography>
    </Box>
  );
}
