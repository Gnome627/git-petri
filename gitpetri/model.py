"""Provider-neutral data model and CI state reduction."""

from dataclasses import dataclass, field
from datetime import datetime

RUNNING = "running"
SUCCESS = "success"
FAILURE = "failure"
NEUTRAL = "neutral"

_RUNNING = {
    "queued", "in_progress", "waiting", "requested", "pending", "running",
    "created", "preparing", "waiting_for_resource", "scheduled", "blocked",
}
_FAILURE = {"failure", "failed", "timed_out", "startup_failure"}


def run_status(status, conclusion=None):
    """Fold the status vocabularies of GitHub, GitLab and Gitea into four states."""
    s = (conclusion or status or "").lower()
    if s == "success":
        return SUCCESS
    if s in _FAILURE:
        return FAILURE
    if s in _RUNNING:
        return RUNNING
    return NEUTRAL


def parse_ts(s):
    if not s:
        return 0.0
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


@dataclass(slots=True)
class Commit:
    sha: str
    title: str
    author: str
    ts: float


@dataclass(slots=True)
class Branch:
    name: str
    ts: float
    commits: list = field(default_factory=list)
    default: bool = False


@dataclass(slots=True)
class Pull:
    number: int
    title: str
    branch: str
    ts: float
    author: str = ""
    draft: bool = False
    url: str = ""


@dataclass(slots=True)
class Run:
    id: int
    workflow: str
    branch: str
    sha: str
    status: str
    ts: float
    url: str = ""
    title: str = ""


@dataclass(slots=True)
class Repo:
    owner: str
    name: str
    ts: float
    url: str = ""
    default_branch: str = ""
    private: bool = False
    branches: list = field(default_factory=list)
    pulls: list = field(default_factory=list)
    runs: list = field(default_factory=list)
    # How much is going on, beyond the few branches and PRs fetched in detail:
    branch_ts: list = field(default_factory=list)  # head commit time of every branch seen
    open_pulls: int = 0


@dataclass(slots=True)
class Snapshot:
    account: str
    repos: list
    fetched: float


@dataclass(slots=True)
class Pipeline:
    """Reduced state of one workflow on one branch."""

    workflow: str
    branch: str
    state: str  # ok | failed | running
    red: bool  # an unresolved failure is outstanding
    ts: float
    sha: str
    url: str
    title: str


def pipelines(runs):
    """Reduce raw runs to one Pipeline per (branch, workflow).

    A failure stays outstanding (`red`) until a later run of the same workflow
    on the same branch succeeds, whichever commit that run is on. Cancelled and
    skipped runs neither clear nor set it.
    """
    groups = {}
    for r in sorted(runs, key=lambda r: (r.ts, r.id)):
        groups.setdefault((r.branch, r.workflow), []).append(r)
    out = []
    for (branch, workflow), rs in groups.items():
        red = False
        decided = False
        last = rs[-1]
        for r in rs:
            if r.status == SUCCESS:
                red, decided = False, True
            elif r.status == FAILURE:
                red, decided = True, True
        running = any(r.status == RUNNING for r in rs[-5:])
        if running:
            state = "running"
        elif not decided:
            continue
        else:
            state = "failed" if red else "ok"
        out.append(Pipeline(workflow, branch, state, red, last.ts, last.sha, last.url, last.title))
    return out
