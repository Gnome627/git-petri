import time
import unittest

from gitpetri import config
from gitpetri.http import ApiError
from gitpetri.model import FAILURE, NEUTRAL, RUNNING, SUCCESS, Repo, Run, Snapshot, pipelines, run_status
from gitpetri.providers.gitea import Gitea
from gitpetri.providers.gitlab import GitLab
from gitpetri.sim import Sim

NOW = "2099-01-01T00:00:00Z"


def run(i, status, branch="main", wf="ci"):
    return Run(i, wf, branch, f"sha{i}", status, float(i))


def state(runs):
    (p,) = pipelines(runs)
    return p.state, p.red


class Pipelines(unittest.TestCase):
    def test_statuses(self):
        self.assertEqual(run_status("completed", "success"), SUCCESS)
        self.assertEqual(run_status("completed", "timed_out"), FAILURE)
        self.assertEqual(run_status("in_progress", None), RUNNING)
        self.assertEqual(run_status("failed"), FAILURE)
        self.assertEqual(run_status("canceled"), NEUTRAL)

    def test_failure_stays_red_until_success_on_same_branch(self):
        self.assertEqual(state([run(1, SUCCESS), run(2, FAILURE)]), ("failed", True))
        self.assertEqual(state([run(1, FAILURE), run(2, NEUTRAL)]), ("failed", True))
        self.assertEqual(state([run(1, FAILURE), run(2, RUNNING)]), ("running", True))
        self.assertEqual(state([run(1, FAILURE), run(2, SUCCESS)]), ("ok", False))

    def test_other_branch_or_workflow_does_not_heal(self):
        by = {(p.branch, p.workflow): p for p in pipelines([
            run(1, FAILURE), run(2, SUCCESS, branch="dev"), run(3, SUCCESS, wf="lint")])}
        self.assertTrue(by[("main", "ci")].red)
        self.assertFalse(by[("dev", "ci")].red)


class Heal(unittest.TestCase):
    def test_heal_fires_once_when_red_pipeline_passes(self):
        sim = Sim()
        repo = lambda runs: [Repo("o", "r", time.time(), runs=runs)]
        sim.apply(Snapshot("a", repo([run(1, FAILURE)]), 0), 1.0, time.time())
        (ci,) = [n for n in sim.nodes.values() if n.kind == "ci"]
        self.assertTrue(ci.red)
        sim.apply(Snapshot("a", repo([run(1, FAILURE), run(2, RUNNING)]), 0), 2.0, time.time())
        self.assertTrue(ci.red)
        self.assertLess(ci.heal, 0)
        runs = [run(1, FAILURE), run(2, SUCCESS)]
        runs[1].ts = time.time()
        sim.apply(Snapshot("a", repo(runs), 0), 3.0, time.time())
        self.assertEqual((ci.state, ci.red, ci.heal), ("ok", False, 3.0))
        sim.apply(Snapshot("a", repo(runs), 0), 4.0, time.time())
        self.assertEqual(ci.heal, 3.0)
        self.assertEqual([e[1] for e in sim.events], ["heal", "run"])


class FakeHttp:
    def __init__(self, routes):
        self.routes = routes

    def get(self, url, params=None):
        for suffix, body in self.routes.items():
            if url.endswith(suffix):
                if isinstance(body, Exception):
                    raise body
                return body
        raise ApiError(404, "not found")


class Providers(unittest.TestCase):
    def check(self, repos):
        (repo,) = repos
        self.assertEqual((repo.owner, repo.name), ("grp", "app"))
        self.assertEqual([b.name for b in repo.branches], ["main", "feat"])
        self.assertTrue(repo.branches[0].default)
        self.assertEqual(repo.branches[1].commits[0].title, "add thing")
        self.assertEqual((repo.pulls[0].number, repo.pulls[0].branch), (7, "feat"))
        (p,) = pipelines(repo.runs)
        self.assertEqual((p.branch, p.state, p.red), ("feat", "failed", True))

    def test_gitlab(self):
        commit = {"id": "c1", "title": "add thing", "author_name": "me", "committed_date": NOW}
        g = GitLab("https://gl.test", "t", config.DEFAULTS)
        g.http = FakeHttp({
            "/projects": [{"id": 5, "path": "app", "path_with_namespace": "grp/app",
                           "namespace": {"full_path": "grp"}, "last_activity_at": NOW,
                           "default_branch": "main", "web_url": "https://gl.test/grp/app"}],
            "/repository/branches": [{"name": "feat", "commit": commit},
                                     {"name": "main", "default": True, "commit": commit}],
            "/repository/commits": [commit],
            "/merge_requests": [{"iid": 7, "title": "x", "source_branch": "feat",
                                 "updated_at": NOW, "author": {"username": "me"}}],
            "/pipelines": [{"id": 2, "ref": "feat", "sha": "c1", "status": "failed",
                            "created_at": NOW},
                           {"id": 1, "ref": "feat", "sha": "c0", "status": "success",
                            "created_at": "2098-12-31T00:00:00Z"}],
        })
        self.check(g.fetch())

    def test_gitea_falls_back_to_tasks_endpoint(self):
        commit = {"id": "c1", "message": "add thing\n\nbody", "timestamp": NOW,
                  "author": {"name": "me"}}
        g = Gitea("https://gt.test", "t", config.DEFAULTS)
        g.http = FakeHttp({
            "/user/repos": [{"name": "app", "owner": {"login": "grp"}, "updated_at": NOW,
                             "default_branch": "main", "html_url": "https://gt.test/grp/app"}],
            "/branches": [{"name": "feat", "commit": commit}, {"name": "main", "commit": commit}],
            "/commits": [{"sha": "c1", "commit": {"message": "add thing\n\nbody",
                                                  "author": {"name": "me", "date": NOW}}}],
            "/pulls": [{"number": 7, "title": "x", "head": {"ref": "feat"}, "updated_at": NOW,
                        "user": {"login": "me"}}],
            "/actions/tasks": {"workflow_runs": [
                {"id": 2, "name": "ci", "head_branch": "feat", "head_sha": "c1",
                 "status": "failure", "created_at": NOW}]},
        })
        self.check(g.fetch())
        self.assertEqual(g.actions["grp/app"], "tasks")


if __name__ == "__main__":
    unittest.main()
