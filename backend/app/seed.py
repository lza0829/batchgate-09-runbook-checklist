from app.db import connect


def init_db():
    conn = connect()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS jobs(
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            fixture_path TEXT NOT NULL,
            depends_on_json TEXT NOT NULL,
            max_attempts INTEGER NOT NULL DEFAULT 1,
            enabled INTEGER NOT NULL DEFAULT 1,
            note TEXT
        );
        CREATE TABLE IF NOT EXISTS orchestrations(
            id INTEGER PRIMARY KEY,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            report_json TEXT NOT NULL,
            runbook_batch_id INTEGER,
            runbook_batch_no TEXT
        );
        CREATE TABLE IF NOT EXISTS job_attempts(
            id INTEGER PRIMARY KEY,
            orchestration_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL,
            attempt_no INTEGER NOT NULL,
            status TEXT NOT NULL,
            detail TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS watermarks(
            job_id INTEGER PRIMARY KEY,
            watermark_ts TEXT,
            artifact_rows INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS runbook_steps(
            id INTEGER PRIMARY KEY,
            seq INTEGER NOT NULL,
            title TEXT NOT NULL,
            required INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'pending',
            note TEXT NOT NULL DEFAULT '',
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS runbook_step_events(
            id INTEGER PRIMARY KEY,
            step_id INTEGER,
            seq INTEGER NOT NULL,
            title TEXT NOT NULL,
            required INTEGER NOT NULL,
            from_status TEXT NOT NULL,
            to_status TEXT NOT NULL,
            batch_id INTEGER,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS runbook_batches(
            id INTEGER PRIMARY KEY,
            batch_no TEXT NOT NULL UNIQUE,
            decision TEXT NOT NULL,
            orchestration_id INTEGER,
            snapshot_json TEXT NOT NULL,
            reasons_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    if conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"] == 0:
        jobs = [
            (
                "ingest_orders",
                "ingest_orders.json",
                "[]",
                1,
                1,
                "无依赖：写出订单水位",
            ),
            (
                "dim_customer",
                "dim_customer.json",
                "[]",
                1,
                1,
                "无依赖：写出客户维表水位",
            ),
            (
                "fact_order_daily",
                "fact_order_daily.json",
                '["ingest_orders","dim_customer"]',
                1,
                1,
                "依赖两路上游成功后才执行（底座仅查上游成功）",
            ),
        ]
        conn.executemany(
            """
            INSERT INTO jobs(name, fixture_path, depends_on_json, max_attempts, enabled, note)
            VALUES (?,?,?,?,?,?)
            """,
            jobs,
        )
        for row in conn.execute("SELECT id FROM jobs").fetchall():
            conn.execute(
                "INSERT OR IGNORE INTO watermarks(job_id, watermark_ts, artifact_rows, updated_at) VALUES (?,?,?,?)",
                (row["id"], None, 0, None),
            )
        conn.execute(
            "INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
            ("default_max_attempts", "1"),
        )
    if conn.execute("SELECT COUNT(*) c FROM runbook_steps").fetchone()["c"] == 0:
        from app.repositories.runbook import reset_steps

        reset_steps(
            conn,
            [
                ("核对上游数据源已就绪", True),
                ("确认今日备份已完成并校验", True),
                ("确认失败重试预算与告警接收人", True),
                ("通知下游相关方编排窗口", False),
            ],
        )
    conn.commit()
    _ensure_columns(conn)
    conn.close()


def _ensure_columns(conn):
    """Lightweight migrations for DB files created before the column existed."""
    cols = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(orchestrations)").fetchall()
    }
    if "runbook_batch_id" not in cols:
        conn.execute("ALTER TABLE orchestrations ADD COLUMN runbook_batch_id INTEGER")
    if "runbook_batch_no" not in cols:
        conn.execute("ALTER TABLE orchestrations ADD COLUMN runbook_batch_no TEXT")
    conn.commit()
