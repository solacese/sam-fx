"""Single-process SQLite incident journal and restartable investigation queue.

No claim of broker exactly-once delivery. Unique IDs suppress local duplicate
requests. Running work is requeued after process restart.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import AgentAssessment, Incident, RegimeChange


class IncidentStore:
    def __init__(self, path: str = ":memory:") -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS incidents (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, payload TEXT NOT NULL, incident_id TEXT,
                status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                result TEXT, error TEXT);
            UPDATE jobs SET status='pending' WHERE status='running';
        """)
        self.db.commit()

    def save(self, incident: Incident) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO incidents VALUES (?,?)",
                (incident.incident_id, incident.model_dump_json()),
            )

    def incidents(self) -> list[Incident]:
        rows = self.db.execute("SELECT payload FROM incidents ORDER BY rowid DESC").fetchall()
        return [Incident.model_validate_json(row[0]) for row in rows]

    def enqueue(self, change: RegimeChange, incident: Incident | None = None) -> bool:
        # Incident creation and the evidence job share one commit.
        with self.db:
            if incident:
                self.db.execute(
                    "INSERT OR REPLACE INTO incidents VALUES (?,?)",
                    (incident.incident_id, incident.model_dump_json()),
                )
            cursor = self.db.execute(
                "INSERT OR IGNORE INTO jobs(id,payload,incident_id) VALUES (?,?,?)",
                (
                    change.correlation_id,
                    change.model_dump_json(),
                    incident.incident_id if incident else None,
                ),
            )
            return cursor.rowcount == 1

    def claim(self) -> tuple[RegimeChange, str | None] | None:
        with self.db:
            row = self.db.execute(
                "SELECT id,payload,incident_id FROM jobs WHERE status='pending' ORDER "
                "BY rowid LIMIT 1"
            ).fetchone()
            if not row:
                return None
            self.db.execute(
                "UPDATE jobs SET status='running', attempts=attempts+1 WHERE id=?", (row[0],)
            )
        return RegimeChange.model_validate_json(row[1]), row[2]

    def complete(self, job_id: str, result: AgentAssessment) -> None:
        with self.db:
            row = self.db.execute("SELECT incident_id FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row and row[0]:
                saved = self.db.execute(
                    "SELECT payload FROM incidents WHERE id=?", (row[0],)
                ).fetchone()
                if saved:
                    incident = Incident.model_validate_json(saved[0])
                    incident.assessment = result
                    self.db.execute(
                        "UPDATE incidents SET payload=? WHERE id=?",
                        (incident.model_dump_json(), incident.incident_id),
                    )
            self.db.execute(
                "UPDATE jobs SET status='complete', result=? WHERE id=?",
                (result.model_dump_json(), job_id),
            )

    def fail(self, job_id: str) -> None:
        with self.db:
            self.db.execute(
                (
                    "UPDATE jobs SET status=CASE WHEN attempts<2 THEN 'pending' ELSE "
                    "'failed' END, error='Investigation failed; review numeric evidence' WHERE id=?"
                ),
                (job_id,),
            )

    def pending(self) -> int:
        return int(
            self.db.execute(
                "SELECT COUNT(*) FROM jobs WHERE status IN ('pending','running')"
            ).fetchone()[0]
        )

    def failed(self) -> int:
        row = self.db.execute("SELECT COUNT(*) FROM jobs WHERE status='failed'").fetchone()
        return int(row[0])

    def handover(self) -> dict[str, object]:
        return {
            "mode": "Synthetic demo; not a bank production record",
            "incidents": [item.model_dump(mode="json") for item in self.incidents()],
            "pending_investigations": self.pending(),
            "failed_investigations": self.failed(),
            "evidence_packages": [
                {
                    "event": RegimeChange.model_validate_json(row[0]).model_dump(mode="json"),
                    "status": row[1],
                    "attempts": row[2],
                }
                for row in self.db.execute(
                    "SELECT payload,status,attempts FROM jobs ORDER BY rowid DESC LIMIT 100"
                ).fetchall()
            ],
        }
