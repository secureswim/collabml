# CollabML

CollabML is a lightweight, branchable experiment trail for Google Colab. It lets you record why you are running an experiment, log the choices and outcome, fork a promising run, and see how the work evolved in a shared dashboard.

This repository contains the complete v0.1 product:

- A dependency-light Python SDK that works in Colab.
- A FastAPI JSON API.
- SQLite persistence.
- A private web dashboard.
- Experiment lineage and parent/child relationships.
- Automatic parameter and metric comparisons.
- A sample Colab notebook.

## What the first release supports

1. Create a project with a primary metric.
2. Start a root experiment from Colab or the dashboard.
3. Record a hypothesis, parameters and notebook URL.
4. Log final/checkpoint metrics.
5. Complete or fail the experiment with a conclusion.
6. Fork any run while inheriting its parameters.
7. View the branching lineage in the dashboard.
8. Compare a child with its parent.
9. Star promising experiments.

## Repository layout

```text
collabml/
├── src/collabml/       # notebook SDK
├── server/             # API and web application
│   ├── templates/      # Jinja dashboard views
│   └── static/         # CSS and browser JavaScript
├── examples/           # Colab demo notebook
├── tests/              # database and SDK tests
├── Dockerfile
└── pyproject.toml
```

## Run locally

From this directory:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[server,dev]"
$env:COLLABML_API_TOKEN = "choose-a-long-random-token"
$env:COLLABML_DATABASE_PATH = ".\data\collabml.db"
$env:COLLABML_PUBLIC_URL = "http://localhost:8000"
uvicorn server.app:app --reload
```

Open `http://localhost:8000` and enter the same token. API documentation is available at `http://localhost:8000/docs`.

If no token is configured, local development uses `dev-token`. Never use that default on a public deployment.

## Use the SDK

Install this repository in the notebook environment. While developing locally, use:

```powershell
python -m pip install -e .
```

After pushing the repository to GitHub, a Colab notebook can install it with:

```python
!pip install -q "collabml @ git+https://github.com/YOUR_USERNAME/collabml.git"
```

Configure the notebook:

```python
import collabml

collabml.configure(
    api_url="https://YOUR-SERVER.example.com",
    token="YOUR_PRIVATE_TOKEN",
)
```

Create a project once:

```python
collabml.create_project(
    name="plant-disease-classifier",
    description="Classify diseases from leaf images",
    primary_metric="val_accuracy",
    goal="maximize",
)
```

Record a baseline:

```python
run = collabml.start(
    project="plant-disease-classifier",
    title="ResNet18 baseline",
    hypothesis="A pretrained ResNet18 should provide a strong baseline",
    params={
        "model": "resnet18",
        "learning_rate": 0.001,
        "batch_size": 32,
        "epochs": 10,
    },
    notebook_url="https://colab.research.google.com/...",
)

run.log({"val_accuracy": 0.84, "val_loss": 0.46})
run.complete("Good baseline; validation loss rises after epoch 7")
print(run.url)
```

Fork the run and specify only changes:

```python
child = collabml.fork(
    run.id,
    title="Lower learning rate",
    hypothesis="A lower rate should prevent late overfitting",
    changes={"learning_rate": 0.0001},
)

child.log({"val_accuracy": 0.872, "val_loss": 0.398})
child.complete("Accuracy improved and validation loss fell")
```

The child automatically inherits all unchanged parameters from its parent.

### Capture notebook failures

Using a context manager marks uncaught exceptions as failed experiments:

```python
with collabml.start(
    project="plant-disease-classifier",
    title="Large batch",
    hypothesis="A larger batch should reduce training time",
    params={"batch_size": 256},
) as run:
    train_model()  # an uncaught exception records a failed run
```

## Deploy the personal server

The included Dockerfile works with any platform that can run a container.

Configure these environment variables:

| Variable | Required | Meaning |
|---|---:|---|
| `COLLABML_API_TOKEN` | Yes | A long, random private token shared by your dashboard and notebooks |
| `COLLABML_DATABASE_PATH` | Yes | Database location, such as `/app/data/collabml.db` |
| `COLLABML_PUBLIC_URL` | Yes | Public HTTPS URL of the deployed dashboard |

The deployment must use a persistent disk mounted at the directory containing the SQLite file. Without persistent storage, a service restart may erase your experiments.

Build and run the container locally:

```powershell
docker build -t collabml .
docker run --rm -p 8000:8000 `
  -e COLLABML_API_TOKEN="choose-a-long-random-token" `
  -e COLLABML_PUBLIC_URL="http://localhost:8000" `
  -v "${PWD}\data:/app/data" `
  collabml
```

For an initial public deployment, choose a service that supports containers, environment secrets and a persistent volume. Keep a copy of the SQLite file as your backup.

## Run tests

```powershell
python -m pytest
```

## Security scope

Version 0.1 is a private, single-workspace alpha:

- One server token protects both the API and dashboard.
- The browser stores the token in an HTTP-only cookie.
- There are no user accounts, invitations or roles yet.
- Use HTTPS for any public deployment.
- Do not put the token directly into a public notebook.

For a private Colab notebook, use Colab Secrets instead of hardcoding the token:

```python
from google.colab import userdata
import collabml

collabml.configure(
    api_url=userdata.get("COLLABML_API_URL"),
    token=userdata.get("COLLABML_API_TOKEN"),
)
```

## Deliberate limitations

This alpha stores the latest value for each metric. It does not yet provide full time-series charts, model or dataset storage, notebook snapshots, reproducible environments, multiple users, comments or real-time collaboration. Those should be added only after the core start → fork → compare workflow is useful in real experiments.

