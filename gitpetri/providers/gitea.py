"""Gitea / Forgejo, REST v1."""

import time

from ..http import ApiError, Http, parallel
from ..model import Branch, Commit, Pull, Repo, Run, parse_ts, run_status

DEFAULT_URL = ""
SCOPES = "read:user, read:repository, read:organization"


class Gitea:
    kind = "gitea"

    def __init__(self, url, token, opts):
        if not url:
            raise ApiError(0, "Gitea needs the instance URL")
        self.api = url.rstrip("/").removesuffix("/api/v1") + "/api/v1"
        self.http = Http({"Authorization": f"token {token}"})
        self.opts = opts
        self.commits = {}  # (repo, branch) -> (head sha, [Commit])
        self.actions = {}  # repo -> endpoint that answered, or None

    def whoami(self):
        return self.http.get(self.api + "/user")["login"]

    def _repos(self):
        out, page, limit = [], 1, self.opts["max_repos"]
        while len(out) < limit:
            batch = self.http.get(self.api + "/user/repos", {"limit": 50, "page": page})
            out += batch
            if len(batch) < 50:
                break
            page += 1
        out = [r for r in out if not r.get("archived")]
        out.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
        return out[:limit]

    def _optional(self, url, params):
        try:
            return self.http.get(url, params)
        except ApiError as e:
            if e.status in (401, 429):
                raise
            return None

    def _runs(self, full, base):
        # /actions/runs is Gitea >= 1.24; older Gitea and Forgejo only have /actions/tasks.
        endpoints = [self.actions[full]] if full in self.actions else ["runs", "tasks"]
        for ep in endpoints:
            if ep is None:
                return []
            body = self._optional(f"{base}/actions/{ep}", {"limit": self.opts["runs"]})
            if body is not None:
                self.actions[full] = ep
                return body.get("workflow_runs") or []
        self.actions[full] = None
        return []

    def fetch(self):
        o = self.opts
        repos = []
        for r in self._repos():
            repos.append(Repo(
                owner=r["owner"]["login"], name=r["name"], ts=parse_ts(r.get("updated_at")),
                url=r.get("html_url", ""), default_branch=r.get("default_branch") or "",
                private=bool(r.get("private"))))

        horizon = time.time() - o["active_days"] * 86400
        def detail(repo):
            full = f"{repo.owner}/{repo.name}"
            base = f"{self.api}/repos/{full}"
            branches = self._optional(base + "/branches", {"limit": 30}) or []
            branches.sort(key=lambda b: (b["name"] != repo.default_branch,
                                         -parse_ts(b["commit"].get("timestamp"))))
            for b in branches[: o["branches"]]:
                sha = b["commit"]["id"]
                key = (full, b["name"])
                if self.commits.get(key, ("",))[0] != sha:
                    raw = self._optional(base + "/commits", {
                        "sha": b["name"], "limit": o["commits"],
                        "stat": "false", "verification": "false", "files": "false"}) or []
                    self.commits[key] = (sha, [Commit(
                        c["sha"], (c["commit"].get("message") or "").split("\n", 1)[0],
                        ((c["commit"].get("author") or {}).get("name")) or "",
                        parse_ts((c["commit"].get("author") or {}).get("date") or c.get("created")),
                    ) for c in raw])
                repo.branches.append(Branch(
                    b["name"], parse_ts(b["commit"].get("timestamp")),
                    self.commits[key][1], b["name"] == repo.default_branch))
            for p in self._optional(base + "/pulls", {
                    "state": "open", "sort": "recentupdate", "limit": o["pulls"]}) or []:
                repo.pulls.append(Pull(
                    p["number"], p["title"], (p.get("head") or {}).get("ref", ""),
                    parse_ts(p.get("updated_at")), (p.get("user") or {}).get("login", ""),
                    bool(p.get("draft")), p.get("html_url", "")))
            for w in self._runs(full, base):
                name = w.get("name") or (w.get("path") or "").split("@")[0].rsplit("/", 1)[-1]
                repo.runs.append(Run(
                    w["id"], name or "workflow", w.get("head_branch") or "",
                    w.get("head_sha") or "", run_status(w.get("status"), w.get("conclusion")),
                    parse_ts(w.get("created_at") or w.get("run_started_at") or w.get("started_at")),
                    w.get("html_url") or w.get("url") or "", w.get("display_title", "")))

        parallel(detail, [r for r in repos[: o["active_repos"]] if r.ts >= horizon])
        return repos
