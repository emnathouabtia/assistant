import os

import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth

load_dotenv()

org = os.environ["ADO_ORG"]
pat = os.environ["ADO_PAT"]

r = requests.get(
    f"https://dev.azure.com/{org}/_apis/projects",
    auth=HTTPBasicAuth("", pat),
    params={"api-version": "7.1"},
    timeout=30,
)

print("Status code:", r.status_code)
if r.ok:
    for p in r.json()["value"]:
        print("Project:", p["name"])