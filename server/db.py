from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def database_path() -> Path:
    configured = os.getenv("COLLABML_DATABASE_PATH", "./data/collabml.db")
    path = Path(configured).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(database_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                description TEXT NOT NULL DEFAULT '',
                primary_metric TEXT NOT NULL DEFAULT '',
                metric_goal TEXT NOT NULL DEFAULT 'maximize'
                    CHECK(metric_goal IN ('maximize', 'minimize')),
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS experiments (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                parent_id TEXT REFERENCES experiments(id) ON DELETE SET NULL,
                title TEXT NOT NULL,
                hypothesis TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running'
                    CHECK(status IN ('running', 'completed', 'failed', 'abandoned')),
                params_json TEXT NOT NULL DEFAULT '{}',
                metrics_json TEXT NOT NULL DEFAULT '{}',
                conclusion TEXT NOT NULL DEFAULT '',
                notebook_url TEXT NOT NULL DEFAULT '',
                tags_json TEXT NOT NULL DEFAULT '[]',
                starred INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                completed_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_experiments_project
                ON experiments(project_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_experiments_parent
                ON experiments(parent_id);
            """
        )


def _project_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def _experiment_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if not row:
        return None
    item = dict(row)
    item["params"] = json.loads(item.pop("params_json"))
    item["metrics"] = json.loads(item.pop("metrics_json"))
    item["tags"] = json.loads(item.pop("tags_json"))
    item["starred"] = bool(item["starred"])
    return item


def create_project(
    name: str,
    description: str = "",
    primary_metric: str = "",
    metric_goal: str = "maximize",
) -> dict[str, Any]:
    item = {
        "id": f"prj_{uuid.uuid4().hex[:10]}",
        "name": name.strip(),
        "description": description.strip(),
        "primary_metric": primary_metric.strip(),
        "metric_goal": metric_goal,
        "created_at": utc_now(),
    }
    with connection() as conn:
        conn.execute(
            """INSERT INTO projects
               (id, name, description, primary_metric, metric_goal, created_at)
               VALUES (:id, :name, :description, :primary_metric, :metric_goal, :created_at)""",
            item,
        )
    return item


def list_projects() -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            """SELECT p.*,
                      COUNT(e.id) AS experiment_count,
                      MAX(e.created_at) AS last_experiment_at
               FROM projects p
               LEFT JOIN experiments e ON e.project_id = p.id
               GROUP BY p.id
               ORDER BY COALESCE(MAX(e.created_at), p.created_at) DESC"""
        ).fetchall()
    return [dict(row) for row in rows]


def get_project(identifier: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM projects WHERE id = ? OR name = ? COLLATE NOCASE",
            (identifier, identifier),
        ).fetchone()
    return _project_dict(row)


def list_experiments(project_id: str) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM experiments WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,),
        ).fetchall()
    return [_experiment_dict(row) for row in rows]  # type: ignore[arg-type]


def get_experiment(experiment_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM experiments WHERE id = ?", (experiment_id,)
        ).fetchone()
    return _experiment_dict(row)


def create_experiment(
    project_identifier: str,
    title: str,
    hypothesis: str,
    params: dict[str, Any] | None = None,
    parent_id: str | None = None,
    notebook_url: str = "",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    project = get_project(project_identifier)
    if not project:
        raise LookupError("Project not found")

    inherited: dict[str, Any] = {}
    if parent_id:
        parent = get_experiment(parent_id)
        if not parent:
            raise LookupError("Parent experiment not found")
        if parent["project_id"] != project["id"]:
            raise ValueError("Parent experiment belongs to another project")
        inherited.update(parent["params"])
    inherited.update(params or {})

    item = {
        "id": f"exp_{uuid.uuid4().hex[:10]}",
        "project_id": project["id"],
        "parent_id": parent_id,
        "title": title.strip(),
        "hypothesis": hypothesis.strip(),
        "status": "running",
        "params_json": json.dumps(inherited, separators=(",", ":"), default=str),
        "metrics_json": "{}",
        "conclusion": "",
        "notebook_url": notebook_url.strip(),
        "tags_json": json.dumps(sorted(set(tags or []))),
        "starred": 0,
        "created_at": utc_now(),
        "completed_at": None,
    }
    with connection() as conn:
        conn.execute(
            """INSERT INTO experiments
               (id, project_id, parent_id, title, hypothesis, status, params_json,
                metrics_json, conclusion, notebook_url, tags_json, starred,
                created_at, completed_at)
               VALUES (:id, :project_id, :parent_id, :title, :hypothesis, :status,
                :params_json, :metrics_json, :conclusion, :notebook_url, :tags_json,
                :starred, :created_at, :completed_at)""",
            item,
        )
    return get_experiment(item["id"])  # type: ignore[return-value]


def update_metrics(experiment_id: str, metrics: dict[str, Any]) -> dict[str, Any]:
    item = get_experiment(experiment_id)
    if not item:
        raise LookupError("Experiment not found")
    merged = {**item["metrics"], **metrics}
    with connection() as conn:
        conn.execute(
            "UPDATE experiments SET metrics_json = ? WHERE id = ?",
            (json.dumps(merged, separators=(",", ":"), default=str), experiment_id),
        )
    return get_experiment(experiment_id)  # type: ignore[return-value]


def finish_experiment(
    experiment_id: str,
    status: str,
    conclusion: str,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if metrics:
        update_metrics(experiment_id, metrics)
    if not get_experiment(experiment_id):
        raise LookupError("Experiment not found")
    with connection() as conn:
        conn.execute(
            """UPDATE experiments
               SET status = ?, conclusion = ?, completed_at = ?
               WHERE id = ?""",
            (status, conclusion.strip(), utc_now(), experiment_id),
        )
    return get_experiment(experiment_id)  # type: ignore[return-value]


def toggle_star(experiment_id: str) -> dict[str, Any]:
    if not get_experiment(experiment_id):
        raise LookupError("Experiment not found")
    with connection() as conn:
        conn.execute(
            "UPDATE experiments SET starred = CASE starred WHEN 0 THEN 1 ELSE 0 END WHERE id = ?",
            (experiment_id,),
        )
    return get_experiment(experiment_id)  # type: ignore[return-value]


def compare_experiments(left_id: str, right_id: str) -> dict[str, Any]:
    left = get_experiment(left_id)
    right = get_experiment(right_id)
    if not left or not right:
        raise LookupError("Experiment not found")
    if left["project_id"] != right["project_id"]:
        raise ValueError("Experiments belong to different projects")

    def diff(first: dict[str, Any], second: dict[str, Any]) -> list[dict[str, Any]]:
        result = []
        for key in sorted(set(first) | set(second)):
            a, b = first.get(key), second.get(key)
            if a != b:
                delta = None
                if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                    delta = b - a
                result.append({"name": key, "left": a, "right": b, "delta": delta})
        return result

    return {
        "left": left,
        "right": right,
        "parameter_changes": diff(left["params"], right["params"]),
        "metric_changes": diff(left["metrics"], right["metrics"]),
    }


def build_forest(experiments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chronological = sorted(experiments, key=lambda item: item["created_at"])
    nodes = {item["id"]: {**item, "children": []} for item in chronological}
    roots: list[dict[str, Any]] = []
    for item in chronological:
        node = nodes[item["id"]]
        parent = nodes.get(item["parent_id"])
        if parent:
            parent["children"].append(node)
        else:
            roots.append(node)
    return roots

