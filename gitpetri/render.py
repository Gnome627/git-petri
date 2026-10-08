"""Braille canvas: organisms are stippled from sub-pixels, labels are plain text on top."""

import random
from math import atan2, exp, pi, sin, cos, sqrt

from .theme import mix, pack

TAU = 2 * pi
BOLD = 1 << 24
UNDERLINE = 1 << 25
DOTS = (0x01, 0x08, 0x02, 0x10, 0x04, 0x20, 0x40, 0x80)  # [row * 2 + column] within a cell
CHARS = [" "] + [chr(0x2800 + i) for i in range(1, 256)]
SCRAMBLE = "░▒▓▚▞/\\<>=+*"
SPIN = "◐◓◑◒"
DRAW = {"org": 0, "repo": 1, "branch": 2, "pr": 3, "ci": 4}
EVENT = {"push": "↑", "branch": "+", "pr": "⇄", "fail": "✗", "heal": "✓", "run": "◐", "note": "!"}
HINTS = "tab select · o open · l labels · d dormant · r sync · q quit"


def _stipples():
    # Per-cell fill orders: entry k lights k of the 8 dots, each a superset of the last,
    # so a colony thickens dot by dot instead of flickering as its density changes.
    rng, out = random.Random(1), []
    for _ in range(64):
        order = list(DOTS)
        rng.shuffle(order)
        acc, masks = 0, [0]
        for bit in order:
            acc |= bit
            masks.append(acc)
        out.append(tuple(masks))
    return out


STIPPLE = _stipples()


def clip(s, n):
    return s if len(s) <= n else s[: n - 1] + "…"


class Renderer:
    def __init__(self, theme):
        self.theme = theme
        self.W = self.H = 0
        self.pch = self.pcol = None
        self.labels = True
        self._sgr = {}
        self._shades = {}

    # -- geometry -----------------------------------------------------------

    def resize(self, w, h):
        self.W, self.H = w, h
        self.cx = float(w)  # dish centre, in sub-pixels
        top, bottom = 4, 4 * (h - 1)  # rows 0 and h-1 are the status lines
        self.cy = (top + bottom) / 2
        self.B = max(8.0, (bottom - top) / 2 - 1)
        self.A = max(8.0, min(w - 2.0, self.B * 2.6))
        self.compact = w < 100 or h < 28  # quarter-screen tiles: fewer labels, terser status
        self.retheme()

    def retheme(self):
        self._shades.clear()
        self._sgr.clear()
        self.pch = None
        rim, specks = {}, {}
        cx, cy, a, b = self.cx, self.cy, self.A, self.B
        steps = int(7 * max(a, b))
        for k in range(steps):
            ang = TAU * k / steps
            self._acc(rim, cx + a * cos(ang), cy + b * sin(ang))
            if k % 6 == 0:
                self._acc(rim, cx + (a - 3) * cos(ang), cy + (b - 3) * sin(ang))
        rng = random.Random(5)
        for _ in range(int(a * b / 220)):
            ang, rad = rng.uniform(0, TAU), sqrt(rng.random()) * 0.96
            self._acc(specks, cx + a * rad * cos(ang), cy + b * rad * sin(ang))
        self.rim, self.specks = list(rim.items()), list(specks.items())

    def _acc(self, cells, x, y):
        px, py = int(x), int(y)
        if 0 <= px < 2 * self.W and 0 <= py < 4 * self.H:
            i = (py >> 2) * self.W + (px >> 1)
            cells[i] = cells.get(i, 0) | DOTS[(py & 3) * 2 + (px & 1)]

    # -- primitives ---------------------------------------------------------

    def begin(self):
        n = self.W * self.H
        self.bits, self.col, self.own = [0] * n, [0] * n, [0] * n
        self.txt = {}
        self.me = 0
        self.panel = self.link = None  # (x0, y0, x1, y1) of the info panel; (y, x0, x1, url)
        th = self.theme
        c = pack(th.speck)
        for i, b in self.specks:
            self.bits[i], self.col[i] = b, c
        c = pack(th.rim)
        for i, b in self.rim:
            self.bits[i], self.col[i] = b, c

    def px(self, x, y, c, me):
        if 0 <= x < 2 * self.W and 0 <= y < 4 * self.H:
            i = (y >> 2) * self.W + (x >> 1)
            b = DOTS[(y & 3) * 2 + (x & 1)]
            if self.own[i] == me:
                self.bits[i] |= b
            else:
                self.own[i], self.bits[i] = me, b
            self.col[i] = c

    def line(self, x0, y0, x1, y1, c, step, phase):
        dx, dy = x1 - x0, y1 - y0
        length = sqrt(dx * dx + dy * dy)
        if length < 1:
            return
        ux, uy = dx / length, dy / length
        s = float(phase % step)
        while s < length:
            self.px(int(x0 + ux * s), int(y0 + uy * s), c, -1)
            s += step

    def ring(self, cx, cy, rad, c):
        self.me += 1
        n = max(8, int(rad * 2.2))
        for k in range(n):
            a = TAU * k / n
            self.px(int(cx + rad * cos(a)), int(cy + rad * sin(a)), c, self.me)

    def disc(self, cx, cy, r, c, diamond=False):
        """A small solid organism, exact to the sub-pixel."""
        self.me += 1
        me, w = self.me, self.W
        bits, col, own = self.bits, self.col, self.own
        x0, x1 = max(0, int(cx - r)), min(2 * w - 1, int(cx + r))
        y0, y1 = max(0, int(cy - r)), min(4 * self.H - 1, int(cy + r))
        r2 = r * r
        for py in range(y0, y1 + 1):
            dy = py + 0.5 - cy
            row, rb = (py >> 2) * w, (py & 3) * 2
            for px in range(x0, x1 + 1):
                dx = px + 0.5 - cx
                if (abs(dx) + abs(dy) > r) if diamond else (dx * dx + dy * dy > r2):
                    continue
                i = row + (px >> 1)
                if own[i] == me:
                    bits[i] |= DOTS[rb + (px & 1)]
                else:
                    own[i], bits[i], col[i] = me, DOTS[rb + (px & 1)], c

    def blob(self, cx, cy, r, shades, t, seed, lobes, dens):
        """A large colony: one sample per cell, stippled denser towards the middle."""
        self.me += 1
        me, w = self.me, self.W
        bits, col, own = self.bits, self.col, self.own
        amp = 0.09
        reach = r * (1 + 2 * amp)
        x0, x1 = max(0, int((cx - reach) // 2)), min(w - 1, int((cx + reach) // 2))
        y0, y1 = max(0, int((cy - reach) // 4)), min(self.H - 1, int((cy + reach) // 4))
        inv = 1.0 / (r * r)
        ph, ph2 = float(seed), seed * 1.7
        gain = dens * 11
        for y in range(y0, y1 + 1):
            py = y * 4 + 2 - cy
            py2, row = py * py, y * w
            for x in range(x0, x1 + 1):
                dx = x * 2 + 1 - cx
                q = (dx * dx + py2) * inv
                if q >= 1.45:
                    continue
                a = atan2(py, dx)
                wob = 1 + amp * sin(lobes * a + ph) + amp * 0.6 * sin((lobes + 2) * a + ph2)
                q /= wob * wob
                if q >= 1:
                    continue
                k = int((1 - q) * gain)
                if k <= 0:
                    continue
                if k > 8:
                    k = 8
                h = x * 31 + y * 17 + seed
                i = row + x
                bits[i] = STIPPLE[h & 63][k]
                col[i] = shades[k]
                own[i] = me

    def cell(self, n, cx, cy, r, t):
        """A CI organism: a membrane round a sparse interior, coloured by pipeline state."""
        th = self.theme
        self.me += 1
        me, w = self.me, self.W
        bits, col, own = self.bits, self.col, self.own
        running, failed = n.state == "running", n.state == "failed"
        main = pack(self.ci_colour(n, t))
        heal = t - n.heal
        front = r * 1.15 * heal / 1.2 if heal < 1.2 else -1.0
        healed, sick = pack(th.bright_green), pack(th.red)
        spike = 0.14 if failed else 0.0
        reach = r * (1 + spike)
        x0, x1 = max(0, int(cx - reach)), min(2 * w - 1, int(cx + reach))
        y0, y1 = max(0, int(cy - reach)), min(4 * self.H - 1, int(cy + reach))
        beat = int(t)  # a running pipeline is the one thing that keeps ticking, slowly
        spin, flow, seed = beat * 0.7, beat, n.seed
        for py in range(y0, y1 + 1):
            dy = py + 0.5 - cy
            row, rb = (py >> 2) * w, (py & 3) * 2
            for px in range(x0, x1 + 1):
                dx = px + 0.5 - cx
                d = sqrt(dx * dx + dy * dy)
                if d > reach:
                    continue
                edge = r
                if failed:
                    edge = r * (1 + spike * sin(7 * atan2(dy, dx) + seed))
                if d > edge:
                    continue
                if d >= edge - 1.7:
                    if running and (atan2(dy, dx) - spin) % TAU > 4.4:
                        continue  # a gap that travels round the membrane
                elif running:
                    if (px + py * 2 + flow) % 6:
                        continue  # streaming cytoplasm
                else:
                    h = px * 374761393 + py * 668265263 + seed
                    if ((h ^ (h >> 13)) * 1274126177 >> 16) & 7 > 1:
                        continue
                i = row + (px >> 1)
                if own[i] == me:
                    bits[i] |= DOTS[rb + (px & 1)]
                else:
                    own[i], bits[i] = me, DOTS[rb + (px & 1)]
                col[i] = main if front < 0 else healed if d < front else sick

    # -- colour -------------------------------------------------------------

    def ci_colour(self, n, t):
        th = self.theme
        if n.state == "ok":
            heal = t - n.heal
            if heal < 3:
                return mix(th.bright_green, th.green, max(0.0, (heal - 1.2) / 1.8))
            return th.green
        if n.red:  # failing, or retrying a failure: red until a run on this branch passes
            return th.red
        return th.yellow

    def tint(self, n, t):
        th = self.theme
        if n.kind == "ci":
            return self.ci_colour(n, t)
        c = mix(th.bg, th.kind[n.kind], 0.45 + 0.55 * round(n.act * 8) / 8)
        flash = t - n.pulse
        if flash < 1.2:
            c = mix(c, th.bright, 0.7 * (1 - flash / 1.2))
        return c

    def shades(self, c):
        s = self._shades.get(c)
        if s is None:
            if len(self._shades) > 4000:
                self._shades.clear()
            bg = self.theme.bg
            s = self._shades[c] = tuple(pack(mix(bg, c, 0.3 + 0.7 * k / 8)) for k in range(9))
        return s

    # -- text ---------------------------------------------------------------

    def put(self, x, y, s, c, used=None):
        w = self.W
        if not s or y < 0 or y >= self.H:
            return False
        x = max(0, min(w - len(s), x))
        base = y * w + x
        if used is not None:
            span = range(max(y * w, base - 1), min(y * w + w, base + len(s) + 1))
            if any(i in used for i in span):
                return False
            used.update(span)
        for j, ch in enumerate(s[: w - x]):
            self.txt[base + j] = (ch, c)
        return True

    def reveal(self, s, age, salt, t):
        """Resolve text out of noise, the way omarchy's text effects do."""
        k = int(len(s) * age / 0.8)
        if k >= len(s):
            return s
        k = max(0, k)
        noise = "".join(SCRAMBLE[(salt + i * 7 + int(t * 18)) % len(SCRAMBLE)]
                        for i in range(k, len(s)))
        return s[:k] + noise

    # -- frame --------------------------------------------------------------

    def draw(self, sim, ui, t, wall):
        self.begin()
        th, cx, cy, bg = self.theme, self.cx, self.cy, self.theme.bg
        nodes = sorted(sim.nodes.values(), key=lambda n: DRAW[n.kind])
        thread = pack(mix(bg, th.muted, 1.15))
        for n in nodes:
            p = n.parent
            if p is None:
                continue
            c = pack(mix(bg, self.ci_colour(n, t), 0.7)) if n.kind == "ci" else thread
            self.line(cx + n.x, cy + n.y, cx + p.x, cy + p.y, c, 2, 0)
            if n.kind == "pr":
                b = sim.nodes.get(n.head)
                if b:
                    self.line(cx + n.x, cy + n.y, cx + b.x, cy + b.y,
                              pack(mix(bg, th.kind["pr"], 0.55)), 2, 0)

        for n in nodes:
            x, y, r, kind = cx + n.x, cy + n.y, n.r, n.kind
            if r < 0.5:
                continue
            c = self.tint(n, t)
            if kind == "ci":
                self.cell(n, x, y, r, t)
                heal = t - n.heal
                if 1.2 <= heal < 3:
                    f = (heal - 1.2) / 1.8
                    self.ring(x, y, r + 1 + f * 22, pack(mix(th.bright_green, bg, f)))
            elif r >= 5.5:
                lobes = 3 + n.seed % 3 if kind == "org" else 2 + n.seed % 3
                self.blob(x, y, r, self.shades(c), t, n.seed, lobes, 0.6 + 0.6 * n.act)
            else:
                self.disc(x, y, r, pack(c), kind == "pr")
            pulse = t - n.pulse
            if pulse < 1.5:
                self.ring(x, y, r + 2 + pulse * 14, pack(mix(c, bg, pulse / 1.5)))
            if n.spores and n.parent:
                self.spores(n, x, y, t, wall, sim.scale)

        used = set()
        sel = sim.nodes.get(ui.selected)
        if sel:
            self.label(sel, sim, t, used, True)
        rank = {"ci": 0, "org": 1, "repo": 2, "pr": 3, "branch": 4}
        for n in sorted(nodes, key=lambda n: (rank[n.kind], -n.act)):
            if n is sel or n.r < 1 or n.dead:
                continue
            if self.compact and (n.kind in ("branch", "pr") or n.kind == "repo" and n.act < 0.25):
                continue
            if n.kind in ("ci", "org") or (self.labels and n.show):
                self.label(n, sim, t, used, False)
        if sel:
            self.focus(sel)
        if not sim.nodes:
            self.waiting(sim, ui, t)
        self.header(sim, ui, t)
        self.footer(sim, t)

    def spores(self, n, x, y, t, wall, scale):
        """Commits: shed from the branch, newest closest, drifting outwards as they age."""
        th, p = self.theme, n.parent
        dx, dy = n.x - p.x, n.y - p.y
        d = sqrt(dx * dx + dy * dy) or 1.0
        ux, uy = dx / d, dy / d
        gap = 2.6 * max(0.75, scale)
        hue = th.kind["branch"]
        self.me += 1
        me = self.me
        for sp in n.spores:
            pos = sp[3]
            dist = n.r + 1.5 + (pos + 1) * gap
            wig = sin(pos * 1.3 + n.seed) * 1.3
            sx, sy = x + ux * dist - uy * wig, y + uy * dist + ux * wig
            age, fresh = wall - sp[1], t - sp[4]
            c = mix(th.bg, mix(hue, th.fg, 0.4), 0.35 + 0.65 * exp(-age / 172800))
            size = 1.5 if age < 7200 else 1.1 if age < 86400 else 0.0
            if fresh < 2:
                c, size = mix(th.bright, c, fresh / 2), 2.2 - fresh * 0.35
            if size:
                self.disc(sx, sy, size, pack(c))
            else:
                self.px(int(sx), int(sy), pack(c), me)

    def label(self, n, sim, t, used, force):
        th = self.theme
        x, y, r = self.cx + n.x, self.cy + n.y, n.r
        col, row = int(x) >> 1, int(y) >> 2
        age = t - n.born - 0.4
        kind = n.kind
        if kind == "org":
            s = self.reveal(clip(n.label, 22), age, n.seed, t)
            c = th.bright if force else mix(th.bg, th.bright, 0.55 + 0.45 * n.act)
            self.put(col - len(s) // 2, row, s, pack(c) | BOLD, None if force else used)
            return
        if kind == "ci":
            heal = t - n.heal
            glyph = "✓" if n.state == "ok" else "✗" if n.state == "failed" else SPIN[int(t) % 4]
            if heal < 1.2:
                glyph = SCRAMBLE[int(t * 18) % len(SCRAMBLE)]
            c = pack(self.ci_colour(n, t)) | BOLD
            self.put(col, row, glyph, pack(th.bright) | BOLD)
            used.add(row * self.W + col)
            below = int(y + r) // 4 + 1
            s = self.reveal(clip(n.label, 16), age, n.seed, t)
            if force or not (self.compact and n.state == "ok"):
                self.put(col - len(s) // 2, below, s, c, None if force else used)
            return
        hue = th.fg if kind == "repo" else th.kind[kind]
        c = pack(mix(th.bg, hue, 0.55 + 0.45 * n.act))
        if force:
            c = pack(th.bright) | BOLD
        s = self.reveal(clip(n.label, 18), age, n.seed, t)
        guard = None if force else used
        if kind == "repo":
            below = int(y + r) // 4 + 1
            if not self.put(col - len(s) // 2, below, s, c, guard):
                self.put(col - len(s) // 2, int(y - r) // 4 - 1, s, c, guard)
            return
        p = n.parent
        if p is None or n.x >= p.x:
            self.put((int(x + r) >> 1) + 2, row, s, c, guard)
        else:
            self.put((int(x - r) >> 1) - 1 - len(s), row, s, c, guard)

    def focus(self, n):
        th = self.theme
        x, y, r = self.cx + n.x, self.cy + n.y, max(n.r, 2.0)
        x0, x1 = (int(x - r) >> 1) - 1, (int(x + r) >> 1) + 1
        y0, y1 = (int(y - r) >> 2) - 1, (int(y + r) >> 2) + 1
        c = pack(th.accent) | BOLD
        for cx, cy, ch in ((x0, y0, "┌"), (x1, y0, "┐"), (x0, y1, "└"), (x1, y1, "┘")):
            if 0 <= cx < self.W and 0 < cy < self.H - 1:
                self.txt[cy * self.W + cx] = (ch, c)

        title = {"org": "organisation", "repo": "repository", "branch": "branch",
                 "pr": "pull request", "ci": "pipeline"}[n.kind]
        lines = list(n.info) + ([n.url] if n.url else [])
        inner = min(self.W - 6, max(20, max(len(s) for s in lines + [title])))
        left = 2 if n.x > 0 else self.W - inner - 6
        frame, dim = pack(th.muted), pack(th.dim)
        top = f"╭─ {title} " + "─" * (inner - len(title) - 1) + "╮"
        self.put(left, 2, top, frame)
        self.panel = (left, 2, left + inner + 4, 4 + len(lines))
        for k, s in enumerate(lines):
            s = clip(s, inner)
            self.put(left, 3 + k, "│ " + " " * inner + " │", frame)
            c = pack(th.bright) | BOLD if k == 0 else dim
            if n.url and k == len(lines) - 1:
                c = pack(th.accent) | UNDERLINE
                self.link = (3 + k, left + 2, left + 2 + len(s), n.url)
            self.put(left + 2, 3 + k, s, c)
        self.put(left, 3 + len(lines), "╰" + "─" * (inner + 2) + "╯", frame)

    def waiting(self, sim, ui, t):
        th = self.theme
        row = int(self.cy) >> 2
        s = "inoculating " + SPIN[int(t) % 4]
        if sim.seen:
            s = "nothing active lately — d shows dormant"
        self.put(self.W // 2 - len(s) // 2, row - 1, s, pack(th.accent) | BOLD)
        for k, (name, state, error) in enumerate(ui.accounts):
            s = f"{name}: {error or state}"
            c = th.red if state == "error" else th.dim
            self.put(self.W // 2 - len(s) // 2, row + 1 + k, clip(s, self.W - 4), pack(c))

    def header(self, sim, ui, t):
        th, w = self.theme, self.W
        self.put(0, 0, " " * w, 0)
        self.put(1, 0, "◉ git-petri", pack(th.accent) | BOLD)
        right = w - 1
        for name, state, error in reversed(ui.accounts):
            mark = {"ok": "●", "error": "✗"}.get(state, "◌")  # static: a sync is not news
            s = clip(f"{name} {mark}" + (f" {error}" if error else ""), max(12, w // 3))
            if right - len(s) < 16:
                break
            right -= len(s)
            hue = {"ok": th.green, "error": th.red}.get(state, th.yellow)
            self.put(right, 0, s, pack(mix(th.bg, hue, 0.8)))
            right -= 2
        # Left to right in order of importance; whatever does not fit is dropped.
        c = sim.counts()
        parts = []
        if c["red"]:
            parts.append((f"✗ {c['red']} failing", pack(th.red) | BOLD))
        if c["running"]:
            parts.append((f"{SPIN[int(t) % 4]} {c['running']} running", pack(th.yellow)))
        quiet = f" · {c['dormant']} dormant" if c["dormant"] else ""
        parts.append((f"{c['org']} orgs · {c['repo']} repos{quiet}", pack(th.dim)))
        parts.append((f"{c['branch']} branches · {c['pr']} PRs", pack(th.dim)))
        x = 14
        for s, colour in parts:
            if x + len(s) > right:
                break
            self.put(x, 0, s, colour)
            x += len(s) + 3

    def footer(self, sim, t):
        th, w, y = self.theme, self.W, self.H - 1
        self.put(0, y, " " * w, 0)
        room = w - 2
        if w > len(HINTS) + 40:
            self.put(w - len(HINTS) - 1, y, HINTS, pack(th.muted))
            room -= len(HINTS) + 3
        hues = {"push": th.kind["branch"], "branch": th.kind["branch"], "pr": th.kind["pr"],
                "fail": th.red, "heal": th.green, "run": th.yellow, "note": th.yellow}
        x = 1
        for k, (when, kind, text) in enumerate(sim.events):
            age = t - when
            s = f"{EVENT[kind]} {text}"
            if k == 0:
                s = self.reveal(s, age * 0.8 * 60 / max(1, len(s)), 0, t)
            fade = 1.0 if k == 0 else 0.45
            s = clip(s, room - x)
            if len(s) < 8:
                break
            c = pack(mix(th.bg, hues[kind], fade)) | (BOLD if k == 0 and age < 6 else 0)
            self.put(x, y, s, c)
            x += len(s) + 3
            if x >= room - 8:
                break

    # -- output -------------------------------------------------------------

    def sgr(self, k):
        s = self._sgr.get(k)
        if s is None:
            bold = ("1;" if k & BOLD else "") + ("4;" if k & UNDERLINE else "")
            s = self._sgr[k] = f"\x1b[0;{bold}38;2;{k >> 16 & 255};{k >> 8 & 255};{k & 255}m"
        return s

    def compose(self):
        ch = [CHARS[b] for b in self.bits]
        col = self.col
        for i, (c, k) in self.txt.items():
            ch[i], col[i] = c, k
        return ch, col

    def emit(self):
        """ANSI for the cells that changed since the previous frame."""
        w, h = self.W, self.H
        ch, col = self.compose()
        pch, pcol = self.pch, self.pcol
        full = pch is None or len(pch) != len(ch)
        out, cur = ["\x1b[?2026h"], -1
        if full:
            out.append("\x1b[0m\x1b[2J")
        for y in range(h):
            a, b = y * w, y * w + w
            if not full and ch[a:b] == pch[a:b] and col[a:b] == pcol[a:b]:
                continue
            pos = -1
            for i in range(a, b):
                c, k = ch[i], col[i]
                if full:
                    if c == " " and pos != i:
                        continue
                elif c == pch[i] and (k == pcol[i] or c == " "):
                    continue
                if pos != i:
                    out.append(f"\x1b[{y + 1};{i - a + 1}H")
                if c == " ":
                    if cur > 0 and cur & UNDERLINE:  # a blank still shows an underline
                        out.append("\x1b[0m")
                        cur = -1
                elif k != cur:
                    out.append(self.sgr(k))
                    cur = k
                out.append(c)
                pos = i + 1
        out.append("\x1b[0m\x1b[?2026l")
        self.pch, self.pcol = ch, col
        return "".join(out)

    def plain(self, colour=False):
        ch, col = self.compose()
        rows = []
        for y in range(self.H):
            if not colour:
                rows.append("".join(ch[y * self.W:(y + 1) * self.W]).rstrip())
                continue
            row, cur = [], -1
            for i in range(y * self.W, (y + 1) * self.W):
                if col[i] != cur and ch[i] != " ":
                    cur = col[i]
                    row.append(self.sgr(cur))
                row.append(ch[i])
            rows.append("".join(row) + "\x1b[0m")
        return "\n".join(rows)
