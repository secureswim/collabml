from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class CollabMLError(RuntimeError):
    """Raised when CollabML cannot complete a request."""


class Client:
    def __init__(self, api_url: str, token: str, timeout: float = 20):
        if not api_url or not token:
            raise ValueError("Both api_url and token are required")
        self.api_url = api_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    @classmethod
    def from_environment(cls) -> "Client":
        api_url = os.getenv("COLLABML_API_URL", "")
        token = os.getenv("COLLABML_API_TOKEN", "")
        if not api_url or not token:
            raise CollabMLError(
                "Configure CollabML first with collabml.configure(api_url=..., token=...) "
                "or set COLLABML_API_URL and COLLABML_API_TOKEN."
            )
        return cls(api_url, token)

    def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> Any:
        body = json.dumps(payload).encode() if payload is not None else None
        request = Request(
            f"{self.api_url}{path}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "collabml-python/0.1.0",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode())
        except HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode()).get("detail", str(exc))
            except (json.JSONDecodeError, UnicodeDecodeError):
                detail = str(exc)
            raise CollabMLError(f"CollabML API error ({exc.code}): {detail}") from exc
        except URLError as exc:
            raise CollabMLError(f"Could not reach CollabML at {self.api_url}: {exc.reason}") from exc

    def create_project(
        self,
        name: str,
        description: str = "",
        primary_metric: str = "",
        goal: str = "maximize",
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/projects",
            {
                "name": name,
                "description": description,
                "primary_metric": primary_metric,
                "metric_goal": goal,
            },
        )

    def projects(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/projects")

    def start(
        self,
        project: str,
        hypothesis: str,
        title: str = "Untitled experiment",
        params: dict[str, Any] | None = None,
        parent: str | None = None,
        notebook_url: str = "",
        tags: list[str] | None = None,
    ) -> "Run":
        data = self._request(
            "POST",
            "/api/experiments",
            {
                "project": project,
                "title": title,
                "hypothesis": hypothesis,
                "params": params or {},
                "parent": parent,
                "notebook_url": notebook_url,
                "tags": tags or [],
            },
        )
        return Run(self, data)

    def fork(
        self,
        experiment_id: str,
        hypothesis: str,
        title: str = "Untitled fork",
        changes: dict[str, Any] | None = None,
        notebook_url: str = "",
        tags: list[str] | None = None,
    ) -> "Run":
        data = self._request(
            "POST",
            f"/api/experiments/{experiment_id}/fork",
            {
                "title": title,
                "hypothesis": hypothesis,
                "changes": changes or {},
                "notebook_url": notebook_url,
                "tags": tags or [],
            },
        )
        return Run(self, data)


@dataclass
class Run:
    client: Client
    data: dict[str, Any]

    @property
    def id(self) -> str:
        return self.data["id"]

    @property
    def url(self) -> str:
        return f"{self.client.api_url}/experiments/{self.id}"

    def __repr__(self) -> str:
        return f"Run(id={self.id!r}, status={self.data.get('status')!r}, url={self.url!r})"

    def log(self, metrics: dict[str, Any], step: int | None = None) -> "Run":
        self.data = self.client._request(
            "POST", f"/api/experiments/{self.id}/log", {"metrics": metrics, "step": step}
        )
        return self

    def complete(
        self, conclusion: str = "", metrics: dict[str, Any] | None = None
    ) -> "Run":
        self.data = self.client._request(
            "POST",
            f"/api/experiments/{self.id}/complete",
            {"conclusion": conclusion, "metrics": metrics or {}},
        )
        return self

    def fail(self, reason: str, metrics: dict[str, Any] | None = None) -> "Run":
        self.data = self.client._request(
            "POST",
            f"/api/experiments/{self.id}/fail",
            {"conclusion": reason, "metrics": metrics or {}},
        )
        return self

    def refresh(self) -> "Run":
        self.data = self.client._request("GET", f"/api/experiments/{self.id}")
        return self

    def __enter__(self) -> "Run":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        if exc_value is not None and self.data.get("status") == "running":
            try:
                self.fail(f"{exc_type.__name__}: {exc_value}")
            except CollabMLError:
                pass
        return False

