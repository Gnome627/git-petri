"""Main loop: poll, simulate, draw."""

import contextlib
import queue
import subprocess
import time

from . import config
from .render import Renderer
from .sim import Sim
from .sync import Syncer
from .term import Terminal
from .theme import Theme

NEXT = {"next", "right", "down", "n"}
PREV = {"back", "left", "up", "p"}


class Ui:
    def __init__(self):
        self.selected = None
        self.accounts = []  # (name, state, error)


def start(providers, settings, notify):
    q = queue.Queue()
    syncers = [Syncer(name, p, q, settings["interval"], settings["max_interval"], notify)
               for name, p in providers]
    for s in syncers:
        s.start()
    return q, syncers


def browse(url):
    if url.startswith(("http://", "https://")):
        subprocess.Popen(["xdg-open", url], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)


def cycle(sim, ui, step):
    order = sim.ordered()
    if not order:
        return
    ids = [n.id for n in order]
    i = ids.index(ui.selected) + step if ui.selected in ids else (0 if step > 0 else -1)
    ui.selected = ids[i % len(ids)]


def run(providers, settings):
    theme, sim, ui = Theme(), Sim(settings["stale_days"]), Ui()
    renderer = Renderer(theme)
    frame = 1.0 / max(1, min(60, settings["fps"]))
    with Terminal() as term, contextlib.ExitStack() as stack:
        stack.callback(config.register().unlink, missing_ok=True)
        q, syncers = start(providers, settings, term.wake)
        last = time.monotonic()
        theme_check = last
        dirty, beat = True, -1
        config_seen = config.mtime()
        while True:
            t = time.monotonic()
            dt, last = min(0.1, t - last), t
            if term.resized:
                term.resized = False
                renderer.resize(*term.size())
                sim.resize(renderer.A, renderer.B, t, time.time())
                dirty = True
            if t - theme_check > 2 or config.mtime() != config_seen:
                theme_check = t
                if theme.changed():
                    renderer.retheme()
                    dirty = True
                if config.mtime() != config_seen:  # `git-petri activity 3d` from another shell
                    config_seen = config.mtime()
                    sim.set_stale(config.load()["settings"]["stale_days"], t, time.time())
                    dirty = True
            while True:
                try:
                    sim.apply(q.get_nowait(), t, time.time())
                    dirty = True
                except queue.Empty:
                    break
            accounts = [(s.account, s.state, s.error) for s in syncers]
            dirty |= accounts != ui.accounts
            ui.accounts = accounts
            if ui.selected not in sim.nodes:
                ui.selected = None

            # At rest the process sleeps until a key, a resize or a poller wakes it: no
            # timer at all. A running pipeline's spinner ticks once a second; only a
            # rearranging dish is drawn at the full rate.
            flowing = sim.tick(dt, t) or sim.animating(t)
            spinning = not sim.seen or sim.counts()["running"]
            if spinning and int(t) != beat:
                beat, dirty = int(t), True
            if dirty or flowing:
                renderer.draw(sim, ui, t, time.time())
                term.write(renderer.emit())
                dirty = False

            if flowing:
                wait = frame - (time.monotonic() - t)
            else:
                wait = 1.0 - t % 1 if spinning else None
            for key in term.keys(wait):
                dirty = True
                if key == "q":
                    return
                if key in NEXT:
                    cycle(sim, ui, 1)
                elif key in PREV:
                    cycle(sim, ui, -1)
                elif key == "esc":
                    ui.selected = None
                elif key == "r":
                    for s in syncers:
                        s.kick.set()
                elif key == "d":
                    sim.toggle_dormant(t, time.time())
                elif key == "l":
                    renderer.labels = not renderer.labels
                elif key in ("o", "enter"):
                    node = sim.nodes.get(ui.selected)
                    if node:
                        browse(node.url)
                elif isinstance(key, tuple):
                    _, col, row = key
                    link, panel = renderer.link, renderer.panel
                    if link and row == link[0] and link[1] <= col < link[2]:
                        browse(link[3])
                        continue
                    if panel and panel[0] <= col < panel[2] and panel[1] <= row < panel[3]:
                        continue  # a click on the panel itself is not a click on the dish
                    node = sim.pick(col * 2 + 1 - renderer.cx, row * 4 + 2 - renderer.cy)
                    ui.selected = node.id if node else None


def snapshot(provider, seconds, size, colour):
    """Headless run: simulate `seconds`, print the final frame."""
    theme, sim, ui = Theme(), Sim(), Ui()
    renderer = Renderer(theme)
    renderer.resize(*size)
    sim.resize(renderer.A, renderer.B)
    ui.accounts = [("demo", "ok", "")]
    from .model import Snapshot
    t, dt, n = 100.0, 0.05, 0
    while t < 100.0 + seconds:
        if n % 50 == 0:
            sim.apply(Snapshot("demo", provider.fetch(), time.time()), t, time.time())
        sim.step(dt, t)
        t += dt
        n += 1
    started = time.perf_counter()
    renderer.draw(sim, ui, t, time.time())
    renderer.emit()
    cost = (time.perf_counter() - started) * 1000
    print(renderer.plain(colour))
    print(f"{len(sim.nodes)} organisms · frame {cost:.1f} ms")
