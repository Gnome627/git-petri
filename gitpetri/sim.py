"""The culture: which organisms exist, how big they are and how they move.

Coordinates are braille sub-pixels (square), origin at the centre of the dish.
"""

import math
import random
from collections import deque
from math import exp, sqrt

from .model import pipelines

DAY = 86400.0
ORDER = {"org": 0, "repo": 1, "ci": 2, "pr": 3, "branch": 4}
FILL = 0.55  # share of the dish the colonies (an organisation and all it shed) may claim
KC, KS = 7.0, 5.0  # collision and tether stiffness
VISCOSITY = 0.45  # how unhurriedly the culture rearranges after new data (1 = brisk)
STILL = 0.01  # sub-pixels per step below which the dish counts as at rest
COOLING = 30.0  # seconds over which a disturbed dish stiffens back to a standstill
LEGIBLE = 0.7  # below this zoom the dish sheds detail instead of shrinking further
ROOM = 180  # sub-pixels of dish each organism should have to itself
# Detail tiers for small windows, coarsest last:
# (satellites per repo, min repo activity to be drawn, min repo activity to get satellites,
#  min branch activity, max age in days of a passing pipeline, commits per branch)
TIERS = (
    (6, 0.0, 0.0, 0.0, 3.0, 8),
    (3, 0.0, 0.05, 0.05, 1.0, 6),
    (3, 0.02, 0.3, 0.3, 0.15, 4),
    (2, 0.1, 0.5, 0.7, 0.05, 3),
)


def ago(seconds):
    s = max(0, int(seconds))
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if s >= size:
            return f"{s // size}{unit} ago"
    return "just now"


class Node:
    __slots__ = ("id", "kind", "acct", "parent", "label", "sub", "x", "y", "r", "base", "rest",
                 "act", "born", "dead", "pulse", "heal", "state", "red", "info", "url", "seed",
                 "spores", "head", "show", "mark", "i", "ext")

    def __init__(self, id, kind, acct, parent, t, seed):
        self.id, self.kind, self.acct, self.parent = id, kind, acct, parent
        self.label = self.sub = self.url = self.head = self.state = ""
        self.x = self.y = self.r = 0.0
        self.base, self.rest, self.act = 1.0, 0.0, 0.0
        self.born, self.pulse, self.heal = t, -99.0, -99.0
        self.dead = self.red = False
        self.show = True
        self.info, self.spores = [], []
        self.seed, self.mark, self.i = seed, 0, 0
        self.ext = 0.0  # unscaled reach of this organism plus everything tethered to it


class Sim:
    def __init__(self):
        self.nodes = {}
        self.events = deque(maxlen=40)  # (t, kind, text)
        self.seen = set()
        self.rng = random.Random(11)
        self.A, self.B = 100.0, 50.0
        self.scale = self.goal = self.fit = 1.0
        self.mark = 0
        self.tier = 0
        self.awake = False  # the dish only simulates while it is still rearranging
        self.calm = 0
        self.woke, self.cool = 0.0, COOLING
        self.last = {}  # account -> latest snapshot, replayed when the level of detail changes

    # -- population ---------------------------------------------------------

    def resize(self, a, b, t=0.0, wall=0.0):
        self.A, self.B = a, b
        self.tier = 0  # a new window size gets to try full detail again
        self._replay(t, wall)
        while self._crowded() and self.tier < len(TIERS) - 1:
            self.tier += 1
            self._replay(t, wall)
        self.settle(t)

    def _replay(self, t, wall):
        for snap in list(self.last.values()):
            self._fold(snap, t, wall, True)
        self._rescale()

    def _rescale(self):
        """Pick the zoom at which every colony, tethers included, fits on the dish."""
        live = [n for n in self.nodes.values() if not n.dead]
        for n in live:
            n.ext = n.base + (8.0 if n.spores else 0.0)
        for n in sorted(live, key=lambda n: -ORDER[n.kind]):  # leaves first
            p = n.parent
            if p is not None:
                p.ext = max(p.ext, n.rest + n.ext)
        # Tethers fan out rather than line up, so a colony spans less than its longest chain.
        orgs = [n.ext * 0.62 for n in live if n.parent is None]
        if orgs:
            fit = sqrt(FILL * self.A * self.B / sum(e * e for e in orgs))
            self.fit = min(fit, 0.94 * self.B / max(orgs))
            self.goal = max(0.42, min(1.6, self.fit))

    def _node(self, id, kind, acct, parent, t):
        n = self.nodes.get(id)
        if n:
            n.dead, n.mark, n.parent = False, self.mark, parent
            return n, False
        rng = self.rng
        n = self.nodes[id] = Node(id, kind, acct, parent, t, rng.randrange(1 << 16))
        if parent:
            n.x, n.y = parent.x + rng.uniform(-1, 1), parent.y + rng.uniform(-1, 1)
        else:
            n.x, n.y = rng.uniform(-0.4, 0.4) * self.A, rng.uniform(-0.4, 0.4) * self.B
        n.mark = self.mark
        return n, True

    def _say(self, t, kind, text):
        self.events.appendleft((t, kind, text))

    def apply(self, snap, t, wall):
        """Fold a fresh snapshot of one account into the dish."""
        quiet = snap.account not in self.seen  # the first load populates without announcing
        self.seen.add(snap.account)
        self.last[snap.account] = snap
        before = self._shape()
        self._fold(snap, t, wall, quiet)
        self._rescale()
        while self._crowded() and self.tier < len(TIERS) - 1:
            self.tier += 1
            self._replay(t, wall)
        if quiet:
            self.settle(t)  # a dish first appears fully grown; only later changes creep
        else:
            after = self._shape()
            if after != before:  # a poll that changed nothing leaves the dish asleep
                # Sizes drifting as activity ages need a nudge; real news gets the full flow.
                news = after.keys() != before.keys() or any(
                    after[k][2:] != before[k][2:] for k in after)
                self.awake, self.calm, self.woke = True, 0, t
                self.cool = COOLING if news else COOLING / 6

    def _shape(self):
        # Coarse enough that activity merely ageing between polls does not count as change.
        return {n.id: (round(n.base * 10), round(n.rest * 5), n.dead, n.state, n.red, n.head,
                       len(n.spores)) for n in self.nodes.values()}

    def settle(self, t):
        """Jump straight to the resting layout instead of flowing there."""
        self.scale = self.goal
        for n in self.nodes.values():
            if not n.dead:
                n.r = n.base * self.goal
            for k, sp in enumerate(n.spores):
                sp[3] = float(k)
        for k in range(500):
            self.step(0.05, t, 1 / VISCOSITY, 2.5 * (1 - k / 500))
        self.awake = False

    def tick(self, dt, t):
        """Advance if anything is still moving; returns whether the picture changed."""
        if not self.awake:
            return False
        # A crowded culture never quite stops sliding, so it is annealed: mobility fades
        # to nothing over COOLING seconds, which also makes the motion ease out.
        heat = max(0.0, 1 - (t - self.woke) / self.cool)
        self.calm = self.calm + 1 if self.step(dt, t, 1.0, heat) < STILL else 0
        if self.calm > 8:
            self.awake = False
        return True

    def animating(self, t):
        """Short event animations: pulses, the heal wave, labels resolving, the ticker."""
        if self.events and t - self.events[0][0] < 2.5:
            return True
        return any(t - n.heal < 3.1 or t - n.pulse < 1.6 or t - n.born < 1.4
                   for n in self.nodes.values())

    def _crowded(self):
        live = sum(not n.dead for n in self.nodes.values())
        return self.fit < LEGIBLE or live > 3.14 * self.A * self.B / ROOM

    def _fold(self, snap, t, wall, quiet):
        acct = snap.account
        self.mark += 1
        floor = TIERS[self.tier][1]
        owners = {}
        for repo in snap.repos:
            owners.setdefault(repo.owner, []).append(repo)
        for owner, repos in owners.items():
            acts = [exp(-max(0.0, wall - r.ts) / (5 * DAY)) for r in repos]
            org, _ = self._node(f"{acct}:{owner}", "org", acct, None, t)
            org.label, org.act = owner, max(acts)
            org.base = min(24.0, 9 + 2.6 * sqrt(len(repos)))
            org.info = [owner, f"{len(repos)} repositories · {acct}"]
            org.url = repos[0].url.rsplit("/", 1)[0] if repos[0].url else ""
            newest = set(sorted(range(len(repos)), key=lambda i: -repos[i].ts)[:4])
            for i, repo in enumerate(repos):
                if acts[i] >= floor or i in newest:
                    self._repo(org, repo, acts[i], i in newest, t, wall, quiet)
        for n in self.nodes.values():
            if n.acct == acct and n.mark != self.mark and not n.dead:
                n.dead = True
                if n.kind == "pr" and not quiet:
                    self._say(t, "pr", f"{n.info[0]} closed")

    def _repo(self, org, repo, act, newest, t, wall, quiet):
        n, _ = self._node(f"{org.id}/{repo.name}", "repo", org.acct, org, t)
        full = f"{repo.owner}/{repo.name}"
        n.label, n.act, n.url = repo.name, act, repo.url
        n.base = 3 + 7 * act ** 0.5
        # Dormant repositories stay fused into the organisation; active ones bud off.
        n.rest = org.base + n.base * (-0.35 + 2.8 * act ** 0.7)
        n.show = newest or act > 0.08
        n.info = [full, f"pushed {ago(wall - repo.ts)}",
                  f"{len(repo.branches)} branches · {len(repo.pulls)} open PRs"]

        cap, _, satellites, twig, passing, ncommits = TIERS[self.tier]
        if act < satellites:
            cap = 0
        seen = set()
        branches = sorted(repo.branches, key=lambda b: (not b.default, -b.ts))
        for b in branches[:cap]:
            ba = exp(-max(0.0, wall - b.ts) / (3 * DAY))
            if (not b.default and wall - b.ts > 30 * DAY) or ba < twig:
                continue
            fresh = [c for c in b.commits
                     if c.sha not in seen and wall - c.ts < 30 * DAY][:ncommits]
            seen.update(c.sha for c in b.commits)
            bn, created = self._node(f"{n.id}@{b.name}", "branch", org.acct, n, t)
            bn.label, bn.act, bn.url = b.name, ba, repo.url
            bn.base = 2.2 + 2.8 * ba
            bn.rest = n.base + bn.base * (0.3 + 1.6 * ba) + 2
            bn.show = not b.default and ba > 0.15
            head = b.commits[0] if b.commits else None
            bn.info = [f"{full} @ {b.name}"]
            if head:
                bn.info += [head.title, f"{head.author} · {ago(wall - head.ts)}"]
            sha = head.sha if head else ""
            if not quiet:
                if created:
                    self._say(t, "branch", f"{full} @ {b.name} created")
                elif sha != bn.head and head:
                    bn.pulse = n.pulse = t
                    self._say(t, "push", f"{full} @ {b.name}  {head.title}")
            bn.head = sha
            old = {s[0]: s for s in bn.spores}
            born = -99.0 if quiet or created else t
            bn.spores = [old.get(c.sha) or [c.sha, c.ts, c.title, -1.0, born] for c in fresh]

        for p in sorted(repo.pulls, key=lambda p: -p.ts)[:cap]:
            pn, created = self._node(f"{n.id}#{p.number}", "pr", org.acct, n, t)
            pa = exp(-max(0.0, wall - p.ts) / (4 * DAY))
            pn.label, pn.act, pn.url = f"#{p.number}", pa, p.url
            pn.base = (2.4 if p.draft else 3.0) + 1.2 * pa
            pn.rest = n.base + pn.base + 5
            pn.head = f"{n.id}@{p.branch}"
            pn.info = [f"{full} #{p.number}" + (" (draft)" if p.draft else ""), p.title,
                       f"{p.author} · {p.branch} · {ago(wall - p.ts)}"]
            if created and not quiet:
                pn.pulse = t
                self._say(t, "pr", f"{full} #{p.number} opened  {p.title}")

        # Unresolved failures are shown at every level of detail, however old.
        shown = [p for p in pipelines(repo.runs)
                 if p.state != "ok" or (cap and wall - p.ts < passing * DAY)]
        shown.sort(key=lambda p: (p.state == "ok", -p.ts))
        for p in shown[:4]:
            cn, created = self._node(f"{n.id}!{p.branch}/{p.workflow}", "ci", org.acct, n, t)
            ca = exp(-max(0.0, wall - p.ts) / DAY)
            what = f"{full} · {p.workflow} @ {p.branch}"
            if not quiet:
                if p.state == "ok" and cn.red:
                    cn.heal = t
                    self._say(t, "heal", f"{what} recovered")
                elif p.state == "failed" and cn.state != "failed":
                    cn.pulse = t
                    self._say(t, "fail", f"{what} failed")
                elif p.state == "running" and cn.state != "running":
                    self._say(t, "run", f"{what} running")
            cn.label, cn.sub, cn.url = p.workflow, p.branch, p.url
            cn.state, cn.red = p.state, p.red
            cn.act = ca if p.state == "ok" else 1.0
            cn.base = {"failed": 8.0, "running": 7.5}.get(p.state, 6 + 1.5 * ca)
            cn.rest = n.base + cn.base + 8
            status = {"ok": "passing", "failed": "failing", "running": "running"}[p.state]
            if p.state == "running" and p.red:
                status = "retrying after a failure"
            cn.info = [what, f"{status} · {ago(wall - p.ts)}"] + ([p.title] if p.title else [])

    # -- queries ------------------------------------------------------------

    def ordered(self):
        live = [n for n in self.nodes.values() if not n.dead]
        return sorted(live, key=lambda n: (n.acct, n.id.split("/")[0], ORDER[n.kind], -n.act))

    def pick(self, x, y):
        best, best_d = None, 1e9
        for n in self.nodes.values():
            d = math.hypot(n.x - x, n.y - y) - n.r
            if d < best_d and not n.dead:
                best, best_d = n, d
        return best if best_d < 4 else None

    def counts(self):
        c = {"org": 0, "repo": 0, "branch": 0, "pr": 0, "red": 0, "running": 0}
        for n in self.nodes.values():
            if n.dead:
                continue
            if n.kind == "ci":
                c["red"] += n.red
                c["running"] += n.state == "running"
            else:
                c[n.kind] += 1
        return c

    # -- motion -------------------------------------------------------------

    def step(self, dt, t, rate=1.0, heat=1.0):
        """One relaxation step; returns the largest change, in sub-pixels."""
        nodes, rng = self.nodes, self.rng
        rate *= VISCOSITY
        moved = abs(self.goal - self.scale) * 20
        s = self.scale = self.scale + (self.goal - self.scale) * min(1.0, dt * 2 * rate)
        grow = min(1.0, dt * 3 * rate)
        for n in list(nodes.values()):
            gap = (0.0 if n.dead else n.base * s) - n.r
            moved = max(moved, abs(gap) * 0.2)
            n.r += gap * grow
            if n.dead and n.r < 0.4:
                del nodes[n.id]
        ns = list(nodes.values())
        count = len(ns)
        for i, n in enumerate(ns):
            n.i = i
            if n.parent is not None and n.parent.id not in nodes:
                n.parent = None
        X = [n.x for n in ns]
        Y = [n.y for n in ns]
        R = [n.r for n in ns]
        P = [n.parent for n in ns]
        FX = [0.0] * count
        FY = [0.0] * count
        pad = 2.5 * s

        for i in range(count):
            a, ax, ay, ar, ap = ns[i], X[i], Y[i], R[i] + pad, P[i]
            for j in range(i + 1, count):
                lim = ar + R[j]
                dx = X[j] - ax
                if dx > lim or dx < -lim:
                    continue
                dy = Y[j] - ay
                if dy > lim or dy < -lim:
                    continue
                if ap is ns[j] or P[j] is a:
                    continue  # a tether, not a collision, positions a child on its parent
                d2 = dx * dx + dy * dy
                if d2 >= lim * lim:
                    continue
                d = sqrt(d2)
                if d < 0.01:
                    dx, dy, d = rng.uniform(-1, 1), rng.uniform(-1, 1), 1.0
                f = (lim - d) * KC / d
                FX[i] -= dx * f
                FY[i] -= dy * f
                FX[j] += dx * f
                FY[j] += dy * f

        orgs = [n for n in ns if n.parent is None]
        squash = self.B / self.A  # a wide dish pulls less along its long axis
        for k, a in enumerate(orgs):
            FX[a.i] -= a.x * 0.6 * squash
            FY[a.i] -= a.y * 0.6
            for b in orgs[k + 1:]:
                dx, dy = b.x - a.x, b.y - a.y
                d = sqrt(dx * dx + dy * dy) or 1.0
                reach = (a.ext + b.ext) * s * 0.95  # keep whole colonies, not just nuclei, apart
                if d < reach:
                    f = (reach - d) * 1.5 / d
                    FX[a.i] -= dx * f
                    FY[a.i] -= dy * f
                    FX[b.i] += dx * f
                    FY[b.i] += dy * f

        for i in range(count):
            p = P[i]
            if p is None:
                continue
            j = p.i
            dx, dy = X[i] - X[j], Y[i] - Y[j]
            d = sqrt(dx * dx + dy * dy)
            if d < 0.01:
                dx, dy, d = rng.uniform(-1, 1), rng.uniform(-1, 1), 1.0
            f = (d - ns[i].rest * s) * KS / d
            FX[i] -= dx * f
            FY[i] -= dy * f
            FX[j] += dx * f * 0.1
            FY[j] += dy * f * 0.1

        A, B = self.A, self.B
        for i, n in enumerate(ns):
            mob = dt * rate * heat / (1 + R[i] / 8)
            x = X[i] + max(-2.5, min(2.5, FX[i] * mob))
            y = Y[i] + max(-2.5, min(2.5, FY[i] * mob))
            keep = R[i] if P[i] is not None else max(R[i], n.ext * s * 0.55)
            ea, eb = max(4.0, A - keep - 3), max(4.0, B - keep - 3)
            f = (x / ea) ** 2 + (y / eb) ** 2
            if f > 1:
                f = 1 / sqrt(f)
                x *= f
                y *= f
            moved = max(moved, abs(x - X[i]), abs(y - Y[i]))
            n.x, n.y = x, y
            for k, sp in enumerate(n.spores):
                moved = max(moved, abs(k - sp[3]) * 0.2)
                sp[3] += (k - sp[3]) * min(1.0, dt * 2.5 * rate)
        return moved
