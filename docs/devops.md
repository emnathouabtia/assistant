# C2 — Azure DevOps REST integration

Owner: Arij

## What it does

`app/devops/ado_client.py` does from Python what you would click in Azure DevOps: it puts a pipeline YAML file into the `demo-app` repository, creates a pipeline that uses it, starts a run, and follows the run until it succeeds or fails.

The YAML text comes from C1 (`generate_pipeline`). A2 calls `publish_pipeline` after the user confirms, and polls `pipeline_status`.

## Setup (Azure DevOps)

| Item | Value |
| --- | --- |
| Organization | `ai-assistant-enicar` |
| Project | `ai-assistant` (private, Git) |
| Target repository | `demo-app` (initialised with a README, so `main` exists) |
| Authentication | Personal Access Token (PAT), scopes **Code: Read & write** and **Build: Read & execute**, short expiry |

Each developer creates their own PAT. Settings go in `.env` (never committed):
ADO_ORG=ai-assistant-enicar
ADO_PROJECT=ai-assistant
ADO_REPO=demo-app
ADO_PAT=<token>


The PAT is sent with HTTP Basic authentication: empty username, PAT as password. It never appears in code, logs or error messages (a test checks this).

## Functions

| Function | REST call | Returns |
| --- | --- | --- |
| `_req(method, path, **kw)` | any call: adds the base URL, the PAT and `api-version=7.1`; raises `AdoError` on any status code of 400 or more | the JSON response |
| `repo_id()` | `GET git/repositories/{repo}` | the repository id (needed to create a pipeline) |
| `branch_head(branch)` | `GET git/repositories/{repo}/refs` | the latest commit id of the branch, or 40 zeros if the branch does not exist |
| `file_exists(path, branch)` | `GET git/repositories/{repo}/items` with `$format=json` | `True` / `False` |
| `push_file(path, content, message, branch)` | `POST git/repositories/{repo}/pushes` | the push; uses `add` or `edit` depending on `file_exists` |
| `create_pipeline(name, yaml_path)` | `POST pipelines` | the pipeline (with its `id`), in the folder `\ai-assistant` |
| `run_pipeline(pipeline_id, branch)` | `POST pipelines/{id}/runs` | the run (with its `id`) |
| `run_status(pipeline_id, run_id)` | `GET pipelines/{id}/runs/{runId}` | a status in the project's contract |
| `publish_pipeline(yaml_text, pipeline_name)` | push + create + run | `{"deployment_id": "<pipelineId>:<runId>", "state": "running", ...}` |
| `pipeline_status(deployment_id)` | splits the id, calls `run_status` | a status in the project's contract |

## Status translation

| Azure DevOps | Project contract |
| --- | --- |
| `state: inProgress` | `running` |
| `state: completed` + `result: succeeded` | `succeeded` |
| `state: completed` + any other result (`failed`, `canceled`) | `failed` |
| anything else (`notStarted`…) | `pending` |

This is the same Status contract as B3, so A2 and the web UI do not need to know whether a status comes from a Bicep deployment or a pipeline.

## How to test

Unit tests (no network, `requests` is replaced with a fake):

```bash
pytest tests/test_ado.py -v
```

They cover: reading the repo id and branch head, an empty repo (40 zeros), errors raising `AdoError`, `add` versus `edit`, the status translation, the PAT never appearing in errors, and the order of steps in `publish_pipeline`.

Manual test against the real organization (creates a real pipeline, use a new name each time):

```bash
python -c "from app.devops.ado_client import publish_pipeline; print(publish_pipeline('trigger:\n- main\npool:\n  vmImage: ubuntu-latest\nsteps:\n- script: echo Published by C2!', 'c2-manual-test'))"
python -c "from app.devops.ado_client import pipeline_status; print(pipeline_status('<pipelineId>:<runId>'))"
```

Tested on 2026-11-12: push, pipeline creation, run and status all worked against `ai-assistant-enicar`.

## Known limits and pitfalls

- **Bug found and fixed:** the `items` API returns the raw file content (YAML, not JSON) when the file exists, which broke JSON parsing. Fixed by asking for metadata with `$format=json`.
- **Pipeline names must be unique:** creating a pipeline with an existing name returns 409.
- **Pushing to `main` triggers every pipeline** whose YAML has `trigger: - main`.
- **Service connection:** a deploy stage needs an Azure Resource Manager service connection, created by hand in Project settings. If it is missing, the run fails at run time, not at creation.
- **New organizations** may need Microsoft's free hosted parallelism grant before pipelines can run. Ours did not.
- **PATs expire:** a sudden 401 usually means the token expired; a 403 with a valid token usually means a missing scope.