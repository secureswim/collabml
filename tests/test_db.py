import os
from pathlib import Path

import pytest

from server import db


@pytest.fixture(autouse=True)
def isolated_database(tmp_path: Path):
    os.environ["COLLABML_DATABASE_PATH"] = str(tmp_path / "collabml.db")
    db.init_db()


def test_project_experiment_fork_and_comparison():
    project = db.create_project(
        "classifier", "A test project", "val_accuracy", "maximize"
    )
    baseline = db.create_experiment(
        project["id"],
        "Baseline",
        "A simple model establishes the baseline",
        {"learning_rate": 0.001, "epochs": 5},
    )
    db.finish_experiment(
        baseline["id"], "completed", "Useful baseline", {"val_accuracy": 0.81}
    )

    child = db.create_experiment(
        project["id"],
        "Lower learning rate",
        "A lower rate should improve validation accuracy",
        {"learning_rate": 0.0001},
        parent_id=baseline["id"],
    )
    assert child["params"] == {"learning_rate": 0.0001, "epochs": 5}

    db.finish_experiment(
        child["id"], "completed", "Accuracy improved", {"val_accuracy": 0.86}
    )
    comparison = db.compare_experiments(baseline["id"], child["id"])

    assert comparison["parameter_changes"] == [
        {"name": "learning_rate", "left": 0.001, "right": 0.0001, "delta": -0.0009}
    ]
    assert comparison["metric_changes"][0]["delta"] == pytest.approx(0.05)


def test_lineage_forest_preserves_branches():
    project = db.create_project("lineage")
    root = db.create_experiment(project["id"], "Root", "Baseline")
    first = db.create_experiment(project["id"], "First", "Branch one", parent_id=root["id"])
    second = db.create_experiment(project["id"], "Second", "Branch two", parent_id=root["id"])

    forest = db.build_forest(db.list_experiments(project["id"]))

    assert [node["id"] for node in forest] == [root["id"]]
    assert {node["id"] for node in forest[0]["children"]} == {first["id"], second["id"]}


def test_rejects_parent_from_another_project():
    one = db.create_project("one")
    two = db.create_project("two")
    parent = db.create_experiment(one["id"], "Parent", "Baseline")

    with pytest.raises(ValueError, match="another project"):
        db.create_experiment(two["id"], "Invalid", "Wrong project", parent_id=parent["id"])

