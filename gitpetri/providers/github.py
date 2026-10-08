"""GitHub (and GitHub Enterprise): one GraphQL query for structure, REST for Actions."""

import time

from ..http import ApiError, Http, parallel
from ..model import Branch, Commit, Pull, Repo, Run, parse_ts, run_status

DEFAULT_URL = "https://api.github.com"
SCOPES = (
    "classic: repo, read:org  ·  fine-grained: Metadata, Contents, "
    "Pull requests, Actions — all read-only"
)

QUERY = """
query($n:Int!,$b:Int!,$c:Int!,$p:Int!){viewer{repositories(first:$n,isArchived:false,
 orderBy:{field:PUSHED_AT,direction:DESC},
 affiliations:[OWNER,COLLABORATOR,ORGANIZATION_MEMBER],
 ownerAffiliations:[OWNER,COLLABORATOR,ORGANIZATION_MEMBER]){nodes{
  name url isPrivate pushedAt updatedAt owner{login} defaultBranchRef{name}
  refs(refPrefix:"refs/heads/",first:$b,orderBy:{field:TAG_COMMIT_DATE,direction:DESC}){nodes{
   name target{... on Commit{history(first:$c){nodes{
    oid messageHeadline committedDate author{name user{login}}}}}}}}
  pullRequests(first:$p,states:OPEN,orderBy:{field:UPDATED_AT,direction:DESC}){nodes{
   number title url isDraft updatedAt headRefName author{login}}}
}}}}
"""


class GitHub:
    kind = "github"

    def __init__(self, url, token, opts):
        url = (url or DEFAULT_URL).rstrip("/")
        if url == DEFAULT_URL:
            self.rest, self.graphql = url, url + "/graphql"
        else:  # GitHub Enterprise Server
            host = url.removesuffix("/api/v3")
            self.rest, self.graphql = host + "/api/v3", host + "/api/graphql"
        self.http = Http({
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        self.opts = opts

    def whoami(self):
        return self.http.get(self.rest + "/user")["login"]

    def _structure(self, n):
        o = self.opts
        body = self.http.post(self.graphql, {"query": QUERY, "variables": {
            "n": n, "b": o["branches"], "c": o["commits"], "p": o["pulls"]}})
        data = (body.get("data") or {}).get("viewer")
        if not data:
            errs = body.get("errors") or [{}]
            raise ApiError(0, errs[0].get("message", "graphql error")[:120])
        return data["repositories"]["nodes"]

    def fetch(self):
        o = self.opts
        n = min(100, o["max_repos"])
        try:
            nodes = self._structure(n)
        except ApiError as e:
            if e.status in (401, 403) or n <= 20:
                raise
            nodes = self._structure(20)  # big accounts can time the full query out
        repos = []
        for r in nodes:
            if not r:
                continue
            default = (r.get("defaultBranchRef") or {}).get("name", "")
            repo = Repo(
                owner=r["owner"]["login"], name=r["name"],
                ts=parse_ts(r.get("pushedAt") or r.get("updatedAt")),
                url=r["url"], default_branch=default, private=r["isPrivate"],
            )
            for ref in (r.get("refs") or {}).get("nodes") or []:
                hist = ((ref.get("target") or {}).get("history") or {}).get("nodes") or []
                commits = [Commit(
                    c["oid"], c["messageHeadline"],
                    ((c.get("author") or {}).get("user") or {}).get("login")
                    or (c.get("author") or {}).get("name") or "",
                    parse_ts(c["committedDate"]),
                ) for c in hist]
                repo.branches.append(Branch(
                    ref["name"], commits[0].ts if commits else 0.0, commits,
                    ref["name"] == default))
            for p in (r.get("pullRequests") or {}).get("nodes") or []:
                repo.pulls.append(Pull(
                    p["number"], p["title"], p["headRefName"], parse_ts(p["updatedAt"]),
                    (p.get("author") or {}).get("login", ""), p["isDraft"], p["url"]))
            repos.append(repo)

        horizon = time.time() - o["active_days"] * 86400
        active = [r for r in sorted(repos, key=lambda r: -r.ts)[: o["active_repos"]]
                  if r.ts >= horizon]

        def runs(repo):
            try:
                body = self.http.get(
                    f"{self.rest}/repos/{repo.owner}/{repo.name}/actions/runs",
                    {"per_page": o["runs"]})
            except ApiError as e:
                if e.status in (401, 429) or (e.status == 403 and "rate limit" in str(e)):
                    raise
                return  # Actions disabled or not visible to this token
            for w in body.get("workflow_runs") or []:
                repo.runs.append(Run(
                    w["id"], w.get("name") or "workflow", w.get("head_branch") or "",
                    w.get("head_sha") or "", run_status(w.get("status"), w.get("conclusion")),
                    parse_ts(w.get("created_at")), w.get("html_url", ""),
                    w.get("display_title", "")))

        parallel(runs, active)
        return repos
