from __future__ import annotations

import json
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Form, Header, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from . import db


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    yield


app = FastAPI(
    title="CollabML",
    description="A branchable experiment trail for Google Colab",
    version="0.1.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def configured_token() -> str:
    return os.getenv("COLLABML_API_TOKEN", "dev-token")


def public_url(request: Request | None = None) -> str:
    configured = os.getenv("COLLABML_PUBLIC_URL", "").rstrip("/")
    if configured:
        return configured
    return str(request.base_url).rstrip("/") if request else "http://localhost:8000"


def require_api_token(authorization: str | None = Header(default=None)) -> None:
    expected = configured_token()
    if not authorization or authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="Invalid or missing API token")


def web_is_authorized(request: Request) -> bool:
    return request.cookies.get("collabml_token") == configured_token()


def require_web(request: Request) -> RedirectResponse | None:
    if not web_is_authorized(request):
        return RedirectResponse("/login", status_code=303)
    return None


def redirect_with_error(path: str, message: str) -> RedirectResponse:
    from urllib.parse import quote

    separator = "&" if "?" in path else "?"
    return RedirectResponse(f"{path}{separator}error={quote(message)}", status_code=303)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    primary_metric: str = Field(default="", max_length=100)
    metric_goal: str = Field(default="maximize", pattern="^(maximize|minimize)$")


class ExperimentCreate(BaseModel):
    project: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=160)
    hypothesis: str = Field(min_length=1, max_length=2000)
    params: dict[str, Any] = Field(default_factory=dict)
    parent: str | None = None
    notebook_url: str = ""
    tags: list[str] = Field(default_factory=list)


class ForkCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    hypothesis: str = Field(min_length=1, max_length=2000)
    changes: dict[str, Any] = Field(default_factory=dict)
    notebook_url: str = ""
    tags: list[str] = Field(default_factory=list)


class MetricsUpdate(BaseModel):
    metrics: dict[str, Any]
    step: int | None = None


class FinishUpdate(BaseModel):
    conclusion: str = Field(default="", max_length=4000)
    metrics: dict[str, Any] = Field(default_factory=dict)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "collabml"}


@app.get("/api/projects", dependencies=[Depends(require_api_token)])
def api_projects() -> list[dict[str, Any]]:
    return db.list_projects()


@app.post("/api/projects", status_code=201, dependencies=[Depends(require_api_token)])
def api_create_project(payload: ProjectCreate) -> dict[str, Any]:
    try:
        return db.create_project(**payload.model_dump())
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "A project with this name already exists") from exc


@app.get("/api/projects/{identifier}", dependencies=[Depends(require_api_token)])
def api_project(identifier: str) -> dict[str, Any]:
    project = db.get_project(identifier)
    if not project:
        raise HTTPException(404, "Project not found")
    project["experiments"] = db.list_experiments(project["id"])
    return project


@app.post("/api/experiments", status_code=201, dependencies=[Depends(require_api_token)])
def api_create_experiment(payload: ExperimentCreate) -> dict[str, Any]:
    try:
        return db.create_experiment(
            project_identifier=payload.project,
            title=payload.title,
            hypothesis=payload.hypothesis,
            params=payload.params,
            parent_id=payload.parent,
            notebook_url=payload.notebook_url,
            tags=payload.tags,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/experiments/{experiment_id}", dependencies=[Depends(require_api_token)])
def api_experiment(experiment_id: str) -> dict[str, Any]:
    experiment = db.get_experiment(experiment_id)
    if not experiment:
        raise HTTPException(404, "Experiment not found")
    return experiment


@app.post(
    "/api/experiments/{experiment_id}/fork",
    status_code=201,
    dependencies=[Depends(require_api_token)],
)
def api_fork(experiment_id: str, payload: ForkCreate) -> dict[str, Any]:
    parent = db.get_experiment(experiment_id)
    if not parent:
        raise HTTPException(404, "Parent experiment not found")
    return db.create_experiment(
        project_identifier=parent["project_id"],
        title=payload.title,
        hypothesis=payload.hypothesis,
        params=payload.changes,
        parent_id=experiment_id,
        notebook_url=payload.notebook_url or parent["notebook_url"],
        tags=payload.tags,
    )


@app.post(
    "/api/experiments/{experiment_id}/log",
    dependencies=[Depends(require_api_token)],
)
def api_log(experiment_id: str, payload: MetricsUpdate) -> dict[str, Any]:
    try:
        return db.update_metrics(experiment_id, payload.metrics)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post(
    "/api/experiments/{experiment_id}/complete",
    dependencies=[Depends(require_api_token)],
)
def api_complete(experiment_id: str, payload: FinishUpdate) -> dict[str, Any]:
    try:
        return db.finish_experiment(
            experiment_id, "completed", payload.conclusion, payload.metrics
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post(
    "/api/experiments/{experiment_id}/fail",
    dependencies=[Depends(require_api_token)],
)
def api_fail(experiment_id: str, payload: FinishUpdate) -> dict[str, Any]:
    try:
        return db.finish_experiment(
            experiment_id, "failed", payload.conclusion, payload.metrics
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/compare", dependencies=[Depends(require_api_token)])
def api_compare(left: str, right: str) -> dict[str, Any]:
    try:
        return db.compare_experiments(left, right)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = ""):
    if web_is_authorized(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request=request, name="login.html", context={"error": error}
    )


@app.post("/login")
def login(token: str = Form(...)):
    if token != configured_token():
        return RedirectResponse("/login?error=Incorrect+token", status_code=303)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        "collabml_token", token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30
    )
    return response


@app.post("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("collabml_token")
    return response


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, error: str = ""):
    redirect = require_web(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"projects": db.list_projects(), "error": error},
    )


@app.post("/projects")
def create_project_form(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    primary_metric: str = Form(""),
    metric_goal: str = Form("maximize"),
):
    redirect = require_web(request)
    if redirect:
        return redirect
    try:
        project = db.create_project(name, description, primary_metric, metric_goal)
        return RedirectResponse(f"/projects/{project['id']}", status_code=303)
    except sqlite3.IntegrityError:
        return redirect_with_error("/", "A project with this name already exists")


@app.get("/projects/{project_id}", response_class=HTMLResponse)
def project_page(request: Request, project_id: str, error: str = ""):
    redirect = require_web(request)
    if redirect:
        return redirect
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    experiments = db.list_experiments(project_id)
    best = None
    metric = project["primary_metric"]
    candidates = [item for item in experiments if isinstance(item["metrics"].get(metric), (int, float))]
    if candidates:
        best = sorted(
            candidates,
            key=lambda item: item["metrics"][metric],
            reverse=project["metric_goal"] == "maximize",
        )[0]
    return templates.TemplateResponse(
        request=request,
        name="project.html",
        context={
            "project": project,
            "experiments": experiments,
            "forest": db.build_forest(experiments),
            "best": best,
            "error": error,
        },
    )


@app.post("/projects/{project_id}/experiments")
def create_experiment_form(
    request: Request,
    project_id: str,
    title: str = Form(...),
    hypothesis: str = Form(...),
    params_json: str = Form("{}"),
    notebook_url: str = Form(""),
    parent_id: str = Form(""),
):
    redirect = require_web(request)
    if redirect:
        return redirect
    try:
        params = json.loads(params_json or "{}")
        if not isinstance(params, dict):
            raise ValueError("Parameters must be a JSON object")
        experiment = db.create_experiment(
            project_id, title, hypothesis, params, parent_id or None, notebook_url
        )
        return RedirectResponse(f"/experiments/{experiment['id']}", status_code=303)
    except (json.JSONDecodeError, ValueError, LookupError) as exc:
        return redirect_with_error(f"/projects/{project_id}", str(exc))


@app.get("/experiments/{experiment_id}", response_class=HTMLResponse)
def experiment_page(request: Request, experiment_id: str, error: str = ""):
    redirect = require_web(request)
    if redirect:
        return redirect
    experiment = db.get_experiment(experiment_id)
    if not experiment:
        raise HTTPException(404, "Experiment not found")
    project = db.get_project(experiment["project_id"])
    parent = db.get_experiment(experiment["parent_id"]) if experiment["parent_id"] else None
    children = [
        item
        for item in db.list_experiments(experiment["project_id"])
        if item["parent_id"] == experiment_id
    ]
    comparison = db.compare_experiments(parent["id"], experiment_id) if parent else None
    snippet = (
        "run = collabml.fork(\n"
        f'    "{experiment_id}",\n'
        '    title="Describe the next attempt",\n'
        '    hypothesis="What do you expect to happen?",\n'
        "    changes={\n        # Add only changed parameters\n    },\n"
        ")"
    )
    return templates.TemplateResponse(
        request=request,
        name="experiment.html",
        context={
            "experiment": experiment,
            "project": project,
            "parent": parent,
            "children": children,
            "comparison": comparison,
            "snippet": snippet,
            "error": error,
        },
    )


@app.post("/experiments/{experiment_id}/star")
def star_experiment(request: Request, experiment_id: str):
    redirect = require_web(request)
    if redirect:
        return redirect
    db.toggle_star(experiment_id)
    return RedirectResponse(f"/experiments/{experiment_id}", status_code=303)


@app.get("/compare", response_class=HTMLResponse)
def compare_page(request: Request, left: str, right: str):
    redirect = require_web(request)
    if redirect:
        return redirect
    try:
        comparison = db.compare_experiments(left, right)
    except (LookupError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    project = db.get_project(comparison["left"]["project_id"])
    return templates.TemplateResponse(
        request=request,
        name="compare.html",
        context={"comparison": comparison, "project": project},
    )

