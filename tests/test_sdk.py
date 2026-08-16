from collabml.client import Client, Run


class RecordingClient(Client):
    def __init__(self):
        super().__init__("https://example.test", "secret")
        self.requests = []

    def _request(self, method, path, payload=None):
        self.requests.append((method, path, payload))
        if path == "/api/experiments":
            return {"id": "exp_1", "status": "running"}
        if path.endswith("/log"):
            return {"id": "exp_1", "status": "running", "metrics": payload["metrics"]}
        if path.endswith("/complete"):
            return {"id": "exp_1", "status": "completed"}
        return {"id": "exp_1", "status": "running"}


def test_notebook_run_workflow():
    client = RecordingClient()
    run = client.start(
        "classifier",
        "A lower rate should help",
        title="Lower rate",
        params={"learning_rate": 0.0001},
    )

    assert isinstance(run, Run)
    assert run.url == "https://example.test/experiments/exp_1"
    run.log({"val_accuracy": 0.86}).complete("It helped")
    assert [request[1] for request in client.requests] == [
        "/api/experiments",
        "/api/experiments/exp_1/log",
        "/api/experiments/exp_1/complete",
    ]

