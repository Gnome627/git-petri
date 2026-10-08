"""Main loop: poll, simulate, draw."""

import queue
import subprocess
import time

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


def start(providers, interval):
    q = queue.Queue()
    syncers = [Syncer(name, p, q, interval) for name, p in providers]
    for s in syncers:
        s.start()
    return q, syncers


def cycle(sim, ui, step):
    order = sim.ordered()
    if not order:
        return
    ids = [n.id for n in order]
    i = ids.index(ui.selected) + step if ui.selected in ids else (0 if step > 0 else -1)
    ui.selected = ids[i % len(ids)]


def run(providers, settings):
    theme, sim, ui = Theme(), Sim(), Ui()
    renderer = Renderer(theme)
    q, syncers = start(providers, settings["interval"])
    frame = 1.0 / max(1, min(60, settings["fps"]))
    with Terminal() as term:
        last = time.monotonic()
        theme_check = last
        dirty, beat = True, -1
        while True:
            t = time.monotonic()
            dt, last = min(0.1, t - last), t
            if term.resized:
                term.resized = False
                renderer.resize(*term.size())
                sim.resize(renderer.A, renderer.B, t, time.time())
                dirty = True
            if t - theme_check > 2:
                theme_check = t
                if theme.changed():
                    renderer.retheme()
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

            # At rest nothing is simulated or drawn. A running pipeline's spinner advances
            # on a half-second beat; only a rearranging dish is drawn at the full rate.
            flowing = sim.tick(dt, t) or sim.animating(t)
            spinning = not sim.nodes or sim.counts()["running"]
            if spinning and int(t * 2) != beat:
                beat, dirty = int(t * 2), True
            if dirty or flowing:
                renderer.draw(sim, ui, t, time.time())
                term.write(renderer.emit())
                dirty = False

            wait = frame - (time.monotonic() - t) if flowing else 0.5 - t * 2 % 1 / 2
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
                elif key == "l":
                    renderer.labels = not renderer.labels
                elif key in ("o", "enter"):
                    node = sim.nodes.get(ui.selected)
                    if node and node.url.startswith(("http://", "https://")):
                        subprocess.Popen(["xdg-open", node.url], stdin=subprocess.DEVNULL,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                         start_new_session=True)
                elif isinstance(key, tuple):
                    _, col, row = key
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
