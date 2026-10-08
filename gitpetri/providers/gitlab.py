"""GitLab (gitlab.com or self-managed), REST v4."""

import time

from ..http import ApiError, Http, parallel
from ..model import Branch, Commit, Pull, Repo, Run, parse_ts, run_status

DEFAULT_URL = "https://gitlab.com"
SCOPES = "read_api"


class GitLab:
    kind = "gitlab"

    def __init__(self, url, token, opts):
        self.api = (url or DEFAULT_URL).rstrip("/").removesuffix("/api/v4") + "/api/v4"
        self.http = Http({"PRIVATE-TOKEN": token})
        self.opts = opts
        self.commits = {}  # (project, branch) -> (head sha, [Commit])

    def whoami(self):
        return self.http.get(self.api + "/user")["username"]

    def _projects(self):
        out, page, limit = [], 1, self.opts["max_repos"]
        while len(out) < limit:
            batch = self.http.get(self.api + "/projects", {
                "membership": "true", "archived": "false", "simple": "true",
                "order_by": "last_activity_at", "sort": "desc",
                "per_page": min(100, limit), "page": page})
            out += batch
            if len(batch) < min(100, limit):
                break
            page += 1
        return out[:limit]

    def _optional(self, url, params):
        try:
            return self.http.get(url, params)
        except ApiError as e:
            if e.status in (401, 429):
                raise
            return []  # feature disabled, empty repository, or not visible

    def fetch(self):
        o = self.opts
        repos = []
        for p in self._projects():
            ns = p.get("namespace") or {}
            repos.append((p["id"], Repo(
                owner=ns.get("full_path") or p["path_with_namespace"].rsplit("/", 1)[0],
                name=p["path"], ts=parse_ts(p.get("last_activity_at")),
                url=p.get("web_url", ""), default_branch=p.get("default_branch") or "")))

        horizon = time.time() - o["active_days"] * 86400
        active = [x for x in sorted(repos, key=lambda x: -x[1].ts)[: o["active_repos"]]
                  if x[1].ts >= horizon]

        def detail(item):
            pid, repo = item
            base = f"{self.api}/projects/{pid}"
            branches = self._optional(base + "/repository/branches", {
                "per_page": 30, "sort": "updated_desc"})
            head = [b for b in branches if b.get("default")]
            rest = sorted((b for b in branches if not b.get("default")),
                          key=lambda b: b["commit"]["committed_date"], reverse=True)
            for b in (head + rest)[: o["branches"]]:
                sha = b["commit"]["id"]
                key = (pid, b["name"])
                if self.commits.get(key, ("",))[0] != sha:
                    raw = self._optional(base + "/repository/commits", {
                        "ref_name": b["name"], "per_page": o["commits"]})
                    self.commits[key] = (sha, [Commit(
                        c["id"], c.get("title", ""), c.get("author_name", ""),
                        parse_ts(c.get("committed_date"))) for c in raw])
                repo.branches.append(Branch(
                    b["name"], parse_ts(b["commit"]["committed_date"]),
                    self.commits[key][1], bool(b.get("default"))))
            for m in self._optional(base + "/merge_requests", {
                    "state": "opened", "order_by": "updated_at", "per_page": o["pulls"]}):
                repo.pulls.append(Pull(
                    m["iid"], m["title"], m.get("source_branch", ""),
                    parse_ts(m.get("updated_at")), (m.get("author") or {}).get("username", ""),
                    bool(m.get("draft") or m.get("work_in_progress")), m.get("web_url", "")))
            for r in self._optional(base + "/pipelines", {"per_page": o["runs"]}):
                repo.runs.append(Run(
                    r["id"], "pipeline", r.get("ref") or "", r.get("sha") or "",
                    run_status(r.get("status")), parse_ts(r.get("created_at")),
                    r.get("web_url", ""), r.get("source") or ""))

        parallel(detail, active)
        return [r for _, r in repos]
