import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

from app.domain.models import Project, ReportRecord, Resource, now_iso


class SQLiteRepository:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self._initialize()

    @contextmanager
    def connection(self):
        con = sqlite3.connect(self.database_path)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def _initialize(self):
        with self.connection() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects(
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS resources(
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL,
                    media_type TEXT NOT NULL, path TEXT NOT NULL, extracted_text TEXT NOT NULL,
                    error TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chunks(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, resource_id TEXT NOT NULL,
                    resource_name TEXT NOT NULL, content TEXT NOT NULL, embedding TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, role TEXT NOT NULL,
                    content TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reports(
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, format TEXT NOT NULL, path TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def add_project(self, project: Project) -> Project:
        with self.connection() as con:
            con.execute("INSERT INTO projects VALUES(?,?,?,?)", tuple(project.model_dump().values()))
        return project

    def list_projects(self) -> list[dict]:
        with self.connection() as con:
            rows = con.execute(
                """SELECT p.*, COUNT(DISTINCT r.id) resource_count, COUNT(DISTINCT o.id) report_count
                   FROM projects p LEFT JOIN resources r ON r.project_id=p.id
                   LEFT JOIN reports o ON o.project_id=p.id GROUP BY p.id ORDER BY p.created_at DESC"""
            ).fetchall()
        return [dict(row) for row in rows]

    def get_project(self, project_id: str) -> dict | None:
        with self.connection() as con:
            project = con.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            if not project:
                return None
            resources = con.execute(
                "SELECT * FROM resources WHERE project_id=? ORDER BY created_at", (project_id,)
            ).fetchall()
            reports = con.execute(
                "SELECT * FROM reports WHERE project_id=? ORDER BY created_at DESC", (project_id,)
            ).fetchall()
            messages = con.execute(
                "SELECT role,content,created_at FROM messages WHERE project_id=? ORDER BY id", (project_id,)
            ).fetchall()
        result = dict(project)
        result.update(resources=[dict(x) for x in resources], reports=[dict(x) for x in reports], messages=[dict(x) for x in messages])
        return result

    def add_resource(self, resource: Resource) -> Resource:
        with self.connection() as con:
            con.execute("INSERT INTO resources VALUES(?,?,?,?,?,?,?,?,?)", tuple(resource.model_dump().values()))
        return resource

    def add_chunks(self, rows: Iterable[tuple[str, str, str, str, list[float]]]):
        with self.connection() as con:
            con.executemany(
                "INSERT INTO chunks(project_id,resource_id,resource_name,content,embedding) VALUES(?,?,?,?,?)",
                [(a, b, c, d, json.dumps(e)) for a, b, c, d, e in rows],
            )

    def get_chunks(self, project_id: str) -> list[dict]:
        with self.connection() as con:
            rows = con.execute("SELECT * FROM chunks WHERE project_id=?", (project_id,)).fetchall()
        result = [dict(row) for row in rows]
        for row in result:
            row["embedding"] = json.loads(row["embedding"])
        return result

    def add_message(self, project_id: str, role: str, content: str):
        with self.connection() as con:
            con.execute("INSERT INTO messages(project_id,role,content,created_at) VALUES(?,?,?,?)", (project_id, role, content, now_iso()))

    def add_report(self, report: ReportRecord):
        with self.connection() as con:
            con.execute("INSERT INTO reports VALUES(?,?,?,?,?)", tuple(report.model_dump().values()))

    def get_report(self, report_id: str) -> dict | None:
        with self.connection() as con:
            row = con.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
        return dict(row) if row else None

