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