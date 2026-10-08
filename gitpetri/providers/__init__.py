from . import gitea, github, gitlab
from .demo import Demo
from .gitea import Gitea
from .github import GitHub
from .gitlab import GitLab

KINDS = {
    "github": (GitHub, github),
    "gitlab": (GitLab, gitlab),
    "gitea": (Gitea, gitea),
}


def make(kind, url, token, opts):
    return KINDS[kind][0](url, token, opts)


__all__ = ["KINDS", "Demo", "make"]
