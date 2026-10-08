"""Synthetic forge for `--demo`: no network, events on every fetch."""

import copy
import random
import time

from ..model import FAILURE, RUNNING, SUCCESS, Branch, Commit, Pull, Repo, Run

H, D = 3600.0, 86400.0
WORDS = "fix add bump refactor drop wire cache retry tune guard".split()
THINGS = "parser healthcheck chart deps renderer probe token timeout ingress layout".split()
SHAPE = {
    "you": [("git-petri", 0.02), ("dotfiles", 1.5), ("homelab", 0.4), ("notes", 40), ("blog", 9)],
    "acme": [("api", 0.05), ("web", 0.3), ("infra", 0.1), ("charts", 3), ("docs", 20),
             ("billing", 6), ("legacy-cron", 200), ("mobile", 75)],
    "forge": [("runner-images", 0.8), ("ansible", 4), ("backup", 31)],
}


class Demo:
    kind = "demo"

    def __init__(self, seed=3):
        self.rng = rng = random.Random(seed)
        self.ids = 1000
        self.repos = []
        self.pending = []  # (due tick, repo, run)
        self.tick = 0
        now = time.time()
        for owner, items in SHAPE.items():
            for name, age_days in items:
                ts = now - age_days * D
                repo = Repo(owner, name, ts, f"https://example.test/{owner}/{name}", "main")
                self.repos.append(repo)
                if age_days > 12:
                    continue
                repo.branches.append(self._branch("main", ts, 5, True))
                for b in rng.sample(["feat/dish", "fix/ci", "renovate/deps", "wip"],
                                    rng.randint(1, 3)):
                    bts = ts - rng.random() * 4 * D if b != "feat/dish" else ts
                    repo.branches.append(self._branch(b, bts, rng.randint(1, 4)))
                    if rng.random() < 0.6:
                        repo.pulls.append(Pull(
                            self._id() % 400, f"{b}: {self._msg()}", b, bts, "you",
                            rng.random() < 0.2, repo.url + "/pulls"))
                if age_days < 5:
                    for wf in ("ci", "deploy")[: rng.randint(1, 2)]:
                        br = "main" if wf == "deploy" else rng.choice(repo.branches).name
                        st = FAILURE if rng.random() < 0.45 else SUCCESS
                        repo.runs.append(self._run(wf, br, st, ts - 0.2 * H, repo))

    def _id(self):
        self.ids += 1
        return self.ids

    def _msg(self):
        return f"{self.rng.choice(WORDS)} {self.rng.choice(THINGS)}"

    def _commit(self, ts):
        return Commit(f"{self.rng.getrandbits(64):016x}", self._msg(), "you", ts)

    def _branch(self, name, ts, n, default=False):
        commits = [self._commit(ts - i * self.rng.random() * 9 * H) for i in range(n)]
        return Branch(name, ts, commits, default)

    def _run(self, wf, branch, status, ts, repo):
        return Run(self._id(), wf, branch, "", status, ts, repo.url + "/actions", self._msg())

    def whoami(self):
        return "demo"

    def fetch(self):
        rng, now = self.rng, time.time()
        self.tick += 1
        for item in [p for p in self.pending if p[0] <= self.tick]:
            self.pending.remove(item)
            _, repo, run = item
            was_red = any(r.status == FAILURE for r in repo.runs
                          if (r.workflow, r.branch) == (run.workflow, run.branch))
            run.status = SUCCESS if rng.random() < (0.85 if was_red else 0.7) else FAILURE
        live = [r for r in self.repos if r.branches]
        if rng.random() < 0.75:
            repo = rng.choice(live)
            br = rng.choice(repo.branches)
            br.commits.insert(0, self._commit(now))
            del br.commits[8:]
            br.ts = repo.ts = now
            wfs = {r.workflow for r in repo.runs} or {"ci"}
            for wf in wfs:
                run = self._run(wf, br.name, RUNNING, now, repo)
                repo.runs.append(run)
                self.pending.append((self.tick + rng.randint(2, 4), repo, run))
        # Nudge an outstanding failure so the heal animation is never far away.
        red = [(repo, r) for repo in live for r in repo.runs if r.status == FAILURE]
        if red and rng.random() < 0.3:
            repo, r = rng.choice(red)
            if not any(p[2].workflow == r.workflow and p[2].branch == r.branch
                       for p in self.pending if p[1] is repo):
                run = self._run(r.workflow, r.branch, RUNNING, now, repo)
                repo.runs.append(run)
                self.pending.append((self.tick + 2, repo, run))
        if rng.random() < 0.08:
            repo = rng.choice(live)
            name = f"feat/{rng.choice(THINGS)}"
            if all(b.name != name for b in repo.branches) and len(repo.branches) < 6:
                repo.branches.append(self._branch(name, now, 1))
                repo.pulls.append(Pull(self._id() % 400, self._msg(), name, now, "you",
                                       False, repo.url + "/pulls"))
                repo.ts = now
        if rng.random() < 0.05:
            repo = rng.choice(live)
            if repo.pulls:
                pull = repo.pulls.pop(rng.randrange(len(repo.pulls)))
                repo.branches = [b for b in repo.branches if b.name != pull.branch or b.default]
        for repo in live:
            del repo.runs[:-40]
        return copy.deepcopy(self.repos)
