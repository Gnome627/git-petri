"""One polling thread per account."""

import threading
import time

from .model import Snapshot


class Syncer(threading.Thread):
    def __init__(self, name, provider, queue, interval):
        super().__init__(daemon=True, name=f"sync-{name}")
        self.account = name
        self.provider = provider
        self.queue = queue
        self.interval = interval
        self.state = "syncing"  # syncing | ok | error
        self.error = ""
        self.last = 0.0
        self.kick = threading.Event()

    def run(self):
        wait = self.interval
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
                self.state, self.error, wait = "ok", "", self.interval
            self.kick.wait(wait)
            self.kick.clear()
