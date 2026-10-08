"""One polling thread per account."""

import threading
import time

from .model import RUNNING, Snapshot


class Syncer(threading.Thread):
    def __init__(self, name, provider, queue, interval, max_interval=300, notify=None):
        super().__init__(daemon=True, name=f"sync-{name}")
        self.account = name
        self.provider = provider
        self.queue = queue
        self.interval = interval
        self.max_interval = max(interval, max_interval)
        self.notify = notify or (lambda: None)
        self.state = "syncing"  # syncing | ok | error
        self.error = ""
        self.last = 0.0
        self.kick = threading.Event()

    def run(self):
        wait, seen = self.interval, None
        while True:
            self.state = "syncing"
            try:
                repos = self.provider.fetch()
            except Exception as e:  # a poller must outlive any provider failure
                self.state, self.error = "error", str(e)[:80] or type(e).__name__
                wait = min(600, wait * 2)
            else:
                self.last = time.time()
                self.queue.put(Snapshot(self.account, repos, self.last))
                self.state, self.error = "ok", ""
                # Poll briskly while things move or a pipeline is in flight; when polls
                # keep returning the same picture, back off so a quiet forge costs little.
                digest = hash(repr(repos))
                busy = any(r.status == RUNNING for repo in repos for r in repo.runs)
                if busy or digest != seen:
                    wait = self.interval
                else:
                    wait = min(self.max_interval, wait * 1.5)
                seen = digest
            self.notify()
            if self.kick.wait(wait):
                wait = self.interval  # a manual refresh also restores the brisk pace
            self.kick.clear()
