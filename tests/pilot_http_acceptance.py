"""Real loopback HTTP acceptance against pilot_browser_fixture.py.

Agents and GitHub are simulated by that fixture. This is not browser or live
provider acceptance. Run with the fixture listening on 127.0.0.1:8766.
"""
import json
import time
from uuid import uuid4

import httpx

ORIGIN = "http://127.0.0.1:8766"
checks = []


def check(name, condition):
    assert condition, name
    checks.append(name)


def call(client, method, path, body=None, expected=200):
    response = client.request(method, path, json=body)
    assert response.status_code == expected, (method, path, response.status_code, response.text)
    return response.json()


def settle(client, proxy, identifier, expected="awaiting_approval"):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        value = call(client, "GET", proxy + "/workflows/" + identifier)
        if value["status"] == expected:
            return value
        assert value["status"] not in {"needs_attention", "cancelled", "rejected"}, value
        time.sleep(.15)
    raise AssertionError("Workflow did not reach " + expected)


with httpx.Client(base_url=ORIGIN, headers={"Origin": ORIGIN}, follow_redirects=True, timeout=30) as owner, \
        httpx.Client(base_url=ORIGIN, headers={"Origin": ORIGIN}, follow_redirects=True, timeout=30) as reviewer:
    owner.get("/demo-session/owner").raise_for_status()
    reviewer.get("/demo-session/reviewer").raise_for_status()
    own_session = call(owner, "GET", "/api/session")
    review_session = call(reviewer, "GET", "/api/session")
    check("Two distinct authenticated humans share the explicit team", own_session["account"]["id"] != review_session["account"]["id"]
          and own_session["workspace"]["id"] == review_session["workspace"]["id"])
    worker = call(owner, "GET", "/api/executors")[0]
    proxy = "/api/executors/" + worker["id"] + "/proxy"
    original = next(value for value in call(owner, "GET", proxy + "/workflows") if value["status"] == "awaiting_approval")
    original = call(owner, "GET", proxy + "/workflows/" + original["id"])
    value = original
    for generation in range(1, 3):
        body = {"request_id": str(uuid4()), "candidate_digest": value["candidate"]["digest"], "correction": "Clarify the addition, correction " + str(generation)}
        parent = value
        child = call(owner, "POST", proxy + "/workflows/" + parent["id"] + "/revise", body)
        retry = call(owner, "POST", proxy + "/workflows/" + parent["id"] + "/revise", body)
        check("Revision " + str(generation) + " retry returns the same immutable workflow", retry["id"] == child["id"])
        value = settle(owner, proxy, child["id"])
        check("Revision " + str(generation) + " has new digest and original lineage", value["candidate"]["digest"] != parent["candidate"]["digest"]
              and value["revision"]["lineage"] == original["id"])
        saved_parent = call(owner, "GET", proxy + "/workflows/" + parent["id"])
        check("Revision " + str(generation) + " supersedes only its saved parent", saved_parent["status"] == "superseded"
              and saved_parent["candidate"]["digest"] == parent["candidate"]["digest"])
    identifier = value["id"]
    candidate = value["candidate"]["digest"]
    path = proxy + "/workflows/" + identifier
    call(owner, "POST", path + "/reviewer", {"reviewer": review_session["account"]["id"]})
    listed = call(reviewer, "GET", proxy + "/workflows")
    check("Assigned candidate is visible in the peer review queue", any(row["id"] == identifier and row["reviewer"] == review_session["account"]["id"] for row in listed))
    refused = owner.post(path + "/approve", json={"request_id": str(uuid4()), "candidate_digest": candidate})
    check("Owner requester cannot self-approve", refused.status_code == 400 and "different human" in refused.text)
    refused = reviewer.post(path + "/apply", json={"request_id": str(uuid4()), "candidate_digest": candidate})
    check("Reviewer cannot apply developer files", refused.status_code == 403)
    call(reviewer, "POST", path + "/approve", {"request_id": str(uuid4()), "candidate_digest": candidate})
    approved = settle(owner, proxy, identifier, "approved")
    check("Peer approval is separate from local application", approved["delivery"]["local"] == "pending")
    preview = call(owner, "POST", path + "/publication-preview", {"request_id": str(uuid4()), "candidate_digest": candidate})
    check("Publication preview binds repository/base/branch and digest", preview["repository"] == "fixture/repo" and preview["base"] == "main"
          and preview["branch"] == "parallax/" + identifier and preview["digest"] == candidate)
    request = {"request_id": str(uuid4()), "workflow": identifier, "binding": approved["github_target"]["id"],
               "candidate_digest": candidate, "title": "HTTP acceptance correction", "description": "Disposable simulated GitHub delivery."}
    refused = reviewer.post("/api/github/publish", json=request)
    check("Reviewer cannot publish", refused.status_code == 403)
    publication = call(owner, "POST", "/api/github/publish", request)
    check("Explicit publication records a draft PR and commit", publication["pr"] == 1 and bool(publication["commit"]))
    retry = call(owner, "POST", "/api/github/publish", request)
    check("Publication retry returns the same PR and commit", retry["pr"] == publication["pr"] and retry["commit"] == publication["commit"])
    delivered = settle(owner, proxy, identifier, "published")
    check("Worker records delivery separately from approval/local files", delivered["delivery"] == {"local": "pending", "github": "published"})
    feedback = call(owner, "GET", "/api/github/feedback/" + identifier)
    check("Refreshed CI and review retain file locations", feedback["checks"][0]["conclusion"] == "success" and feedback["comments"][0]["path"] == "maths.py")
    report = call(owner, "GET", proxy + "/pilot/report")
    outcome = next(row for row in report["outcomes"] if row["workflow"] == identifier)
    check("Outcome includes publication with unknown cost preserved", outcome["provider_cost_usd"] is None and outcome["cost_status"] == "unknown")
    print(json.dumps({"passed": len(checks), "checks": checks, "workflow": identifier, "simulation": "fake providers and GitHub; actual native worker/relay HTTP"}, indent=2))
