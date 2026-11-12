import os

import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth

load_dotenv()

API = "7.1"
ZERO = "0" * 40


class AdoError(Exception):
    pass
def _base():
    org = os.environ["ADO_ORG"]
    project = os.environ["ADO_PROJECT"]
    return f"https://dev.azure.com/{org}/{project}/_apis"
def _req(method, path, **kw):
    params = {"api-version": API, **kw.pop("params", {})}
    r = requests.request(
        method,
        f"{_base()}/{path}",
        auth=HTTPBasicAuth("", os.environ["ADO_PAT"]),
        params=params,
        timeout=30,
        **kw,
    )
    if r.status_code >= 400:
        raise AdoError(f"Azure DevOps {r.status_code}: {r.text[:200]}")
    return r.json() if r.text else {}
def repo_id():
    repo = os.environ["ADO_REPO"]
    return _req("GET", f"git/repositories/{repo}")["id"]


def branch_head(branch="main"):
    repo = os.environ["ADO_REPO"]
    refs = _req("GET", f"git/repositories/{repo}/refs",
                params={"filter": f"heads/{branch}"})["value"]
    return refs[0]["objectId"] if refs else ZERO

def file_exists(path, branch="main"):
    repo = os.environ["ADO_REPO"]
    try:
        _req("GET", f"git/repositories/{repo}/items",
             params={"path": path, "versionDescriptor.version": branch, "$format": "json"})
        return True
    except AdoError:
        return False

def push_file(path, content, message, branch="main"):
    repo = os.environ["ADO_REPO"]
    change = "edit" if file_exists(path, branch) else "add"
    body = {
        "refUpdates": [{"name": f"refs/heads/{branch}", "oldObjectId": branch_head(branch)}],
        "commits": [{
            "comment": message,
            "changes": [{
                "changeType": change,
                "item": {"path": path},
                "newContent": {"content": content, "contentType": "rawtext"},
            }],
        }],
    }
    return _req("POST", f"git/repositories/{repo}/pushes", json=body)

def create_pipeline(name, yaml_path="/azure-pipelines.yml"):
    body = {
        "name": name,
        "folder": "\\ai-assistant",
        "configuration": {
            "type": "yaml",
            "path": yaml_path,
            "repository": {
                "id": repo_id(),
                "name": os.environ["ADO_REPO"],
                "type": "azureReposGit",
            },
        },
    }
    return _req("POST", "pipelines", json=body)

def run_pipeline(pipeline_id, branch="main"):
    body = {"resources": {"repositories": {"self": {"refName": f"refs/heads/{branch}"}}}}
    return _req("POST", f"pipelines/{pipeline_id}/runs", json=body)

def run_status(pipeline_id, run_id):
    r = _req("GET", f"pipelines/{pipeline_id}/runs/{run_id}")
    state, result = r.get("state"), r.get("result")
    if state == "completed":
        s = "succeeded" if result == "succeeded" else "failed"
    elif state == "inProgress":
        s = "running"
    else:
        s = "pending"
    return {
        "state": s,
        "message": f"{state} {result or ''}".strip(),
        "link": r.get("_links", {}).get("web", {}).get("href"),
    }

def publish_pipeline(yaml_text, pipeline_name):
    push_file("/azure-pipelines.yml", yaml_text, f"Add pipeline {pipeline_name} (AI assistant)")
    p = create_pipeline(pipeline_name)
    run = run_pipeline(p["id"])
    return {"deployment_id": f"{p['id']}:{run['id']}", "state": "running",
            "message": "Pipeline created and started"}

def pipeline_status(deployment_id):
    pipeline_id, run_id = deployment_id.split(":")
    st = run_status(int(pipeline_id), int(run_id))
    return {"deployment_id": deployment_id, **st}