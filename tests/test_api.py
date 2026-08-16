from pathlib import Path

from fastapi.testclient import TestClient

from server.app import app


def test_end_to_end_api_and_dashboard(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("COLLABML_DATABASE_PATH", str(tmp_path / "api.db"))
    monkeypatch.setenv("COLLABML_API_TOKEN", "test-token")
    headers = {"Authorization": "Bearer test-token"}

    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "ok"
        assert client.get("/api/projects").status_code == 401

        project_response = client.post(
            "/api/projects",
            headers=headers,
            json={
                "name": "colab-demo",
                "description": "End-to-end verification",
                "primary_metric": "val_accuracy",
                "metric_goal": "maximize",
            },
        )
        assert project_response.status_code == 201
        project = project_response.json()

        baseline_response = client.post(
            "/api/experiments",
            headers=headers,
            json={
                "project": project["id"],
                "title": "Baseline",
                "hypothesis": "A baseline should establish performance",
                "params": {"learning_rate": 0.001, "epochs": 5},
                "notebook_url": "https://colab.research.google.com/",
            },
        )
        assert baseline_response.status_code == 201
        baseline = baseline_response.json()
        client.post(
            f"/api/experiments/{baseline['id']}/complete",
            headers=headers,
            json={"conclusion": "Baseline recorded", "metrics": {"val_accuracy": 0.81}},
        )

        fork_response = client.post(
            f"/api/experiments/{baseline['id']}/fork",
            headers=headers,
            json={
                "title": "Lower learning rate",
                "hypothesis": "A lower learning rate should improve accuracy",
                "changes": {"learning_rate": 0.0001},
            },
        )
        assert fork_response.status_code == 201
        fork = fork_response.json()
        assert fork["parent_id"] == baseline["id"]
        assert fork["params"]["epochs"] == 5
        client.post(
            f"/api/experiments/{fork['id']}/complete",
            headers=headers,
            json={"conclusion": "Accuracy improved", "metrics": {"val_accuracy": 0.86}},
        )

        comparison = client.get(
            "/api/compare",
            headers=headers,
            params={"left": baseline["id"], "right": fork["id"]},
        )
        assert comparison.status_code == 200
        assert comparison.json()["metric_changes"][0]["delta"] > 0

        login = client.post("/login", data={"token": "test-token"}, follow_redirects=False)
        assert login.status_code == 303
        cookie = login.cookies.get("collabml_token")
        assert cookie == "test-token"

        project_page = client.get(f"/projects/{project['id']}", cookies={"collabml_token": cookie})
        assert project_page.status_code == 200
        assert "How the model evolved" in project_page.text
        assert "Lower learning rate" in project_page.text

        detail_page = client.get(f"/experiments/{fork['id']}", cookies={"collabml_token": cookie})
        assert detail_page.status_code == 200
        assert "Compared with parent" in detail_page.text
        assert "Accuracy improved" in detail_page.text

        compare_page = client.get(
            "/compare",
            params={"left": baseline["id"], "right": fork["id"]},
            cookies={"collabml_token": cookie},
        )
        assert compare_page.status_code == 200
        assert "Parameter changes" in compare_page.text
        assert "Metric differences" in compare_page.text

