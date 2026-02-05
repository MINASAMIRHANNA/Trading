from __future__ import annotations

from sqlalchemy import inspect, text

from database.engine import get_db_schema


_TRADE_FEATURE_COLUMNS = {
    "trade_time": "TIMESTAMP",
    "entry_price": "DOUBLE PRECISION",
    "market_close_price": "DOUBLE PRECISION",
    "entry_vs_close_pct": "DOUBLE PRECISION",
    "entry_vs_ema_20_pct": "DOUBLE PRECISION",
    "entry_vs_ema_50_pct": "DOUBLE PRECISION",
    "atr_pct_at_entry": "DOUBLE PRECISION",
    "rsi_bucket": "VARCHAR(32)",
    "market_regime": "VARCHAR(64)",
    "market_regime_encoded": "DOUBLE PRECISION",
    "directional_alignment": "DOUBLE PRECISION",
    "pnl_pct": "DOUBLE PRECISION",
    "market_join_valid": "BOOLEAN",
    # lineage
    "source_role": "VARCHAR(32) NOT NULL DEFAULT 'unknown'",
    "source_trade_id": "BIGINT NOT NULL DEFAULT 0",
    "source_status": "VARCHAR(32)",
    "source_closed_at_ms": "BIGINT",
    "source_pnl": "DOUBLE PRECISION",
}

_VALID_ROLES = ("paper", "live", "pump")


def ensure_trade_features_columns(engine, schema: str | None = None) -> None:
    """Best-effort add missing columns to trade_features for existing DBs."""
    dialect = engine.dialect.name
    use_schema = schema or get_db_schema()
    schema_arg = use_schema if dialect.startswith("postgres") else None

    insp = inspect(engine)
    if not insp.has_table("trade_features", schema=schema_arg):
        return

    existing = {c["name"] for c in insp.get_columns("trade_features", schema=schema_arg)}
    missing = {k: v for k, v in _TRADE_FEATURE_COLUMNS.items() if k not in existing}

    table_ref = "trade_features"
    if schema_arg:
        table_ref = f'"{schema_arg}"."trade_features"'

    if missing:
        with engine.begin() as conn:
            for col, ddl in missing.items():
                conn.execute(text(f"ALTER TABLE {table_ref} ADD COLUMN {col} {ddl}"))

    # Cleanup invalid rows (always, even if columns already exist).
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    f"""
                    DELETE FROM {table_ref}
                    WHERE source_role IS NULL
                       OR source_role = 'unknown'
                       OR source_trade_id IS NULL
                       OR source_trade_id <= 0
                    """
                )
            )
    except Exception:
        pass

    # Ensure unique lineage index (cleanup duplicates first).
    try:
        idx_name = "uq_trade_features_source"
        if dialect.startswith("postgres"):
            with engine.begin() as conn:
                # Remove duplicates, keep highest id per (source_role, source_trade_id).
                conn.execute(
                    text(
                        f"""
                        DELETE FROM {table_ref} a
                        USING {table_ref} b
                        WHERE a.source_role = b.source_role
                          AND a.source_trade_id = b.source_trade_id
                          AND a.id < b.id
                        """
                    )
                )
                conn.execute(
                    text(
                        f'CREATE UNIQUE INDEX IF NOT EXISTS {idx_name} ON {table_ref} (source_role, source_trade_id)'
                    )
                )
                # Add CHECK constraints (if not exists)
                conn.execute(
                    text(
                        """
                        DO $$
                        BEGIN
                          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_trade_features_source_id') THEN
                            ALTER TABLE {table_ref} ADD CONSTRAINT chk_trade_features_source_id CHECK (source_trade_id > 0);
                          END IF;
                          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_trade_features_source_role') THEN
                            ALTER TABLE {table_ref} ADD CONSTRAINT chk_trade_features_source_role CHECK (source_role IN ('paper','live','pump'));
                          END IF;
                        END $$;
                        """.format(table_ref=table_ref)
                    )
                )
        else:
            # SQLite (no schema qualification)
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        DELETE FROM trade_features
                        WHERE rowid NOT IN (
                          SELECT MAX(rowid)
                          FROM trade_features
                          GROUP BY source_role, source_trade_id
                        )
                        """
                    )
                )
                conn.execute(
                    text(
                        f'CREATE UNIQUE INDEX IF NOT EXISTS {idx_name} ON trade_features (source_role, source_trade_id)'
                    )
                )
    except Exception:
        pass
