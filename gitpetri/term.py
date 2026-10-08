"""Raw terminal: alternate screen, key and mouse decoding."""

import os
import re
import select
import signal
import sys
import termios
import tty

_SEQ = re.compile(r"\x1b\[<(\d+);(\d+);(\d+)([Mm])|\x1b\[([ABCDZ])|\x1bO([ABCD])|\x1b\[[\d;?]*[ -/]*[@-~]|.",
                  re.S)
_ARROWS = {"A": "up", "B": "down", "C": "right", "D": "left", "Z": "back"}
_PLAIN = {"\t": "next", "\r": "enter", "\n": "enter", "\x1b": "esc", "\x03": "q", " ": "space"}
# The same physical keys on a Russian layout.
_LAYOUT = str.maketrans("йкщдтзвЙКЩДТЗВ", "qroltpdqroltpd")


class Terminal:
    def __enter__(self):
        self.fd = sys.stdin.fileno()
        self.saved = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        self.resized = True
        # Anything that should end an idle wait writes to this pipe: pollers through
        # wake(), and signals (a resize) through the interpreter's wakeup fd.
        self.pipe_r, self.pipe_w = os.pipe()
        os.set_blocking(self.pipe_r, False)
        os.set_blocking(self.pipe_w, False)
        signal.set_wakeup_fd(self.pipe_w, warn_on_full_buffer=False)
        signal.signal(signal.SIGWINCH, self._winch)
        signal.signal(signal.SIGUSR1, lambda *_: None)  # only there to end the idle wait
        signal.signal(signal.SIGTERM, self._term)
        self.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h\x1b[2J")
        return self

    def __exit__(self, *exc):
        self.write("\x1b[?1006l\x1b[?1000l\x1b[?2026l\x1b[0m\x1b[?25h\x1b[?1049l")
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)
        signal.set_wakeup_fd(-1)

    def wake(self):
        try:
            os.write(self.pipe_w, b"\0")
        except OSError:
            pass  # pipe full: a wake-up is already pending

    def _winch(self, *_):
        self.resized = True

    def _term(self, *_):
        raise SystemExit(0)

    def size(self):
        s = os.get_terminal_size(sys.stdout.fileno())
        return s.columns, s.lines

    def write(self, s):
        sys.stdout.write(s)
        sys.stdout.flush()

    def keys(self, timeout):
        """Wait up to `timeout` seconds (None: until woken); return decoded input events."""
        if timeout is not None:
            timeout = max(0.0, timeout)
        ready, _, _ = select.select([self.fd, self.pipe_r], [], [], timeout)
        if self.pipe_r in ready:
            try:
                os.read(self.pipe_r, 4096)
            except OSError:
                pass
        if self.fd not in ready:
            return []
        data = os.read(self.fd, 4096).decode("utf-8", "ignore")
        out = []
        for m in _SEQ.finditer(data):
            if m.group(1):
                if m.group(4) == "M" and int(m.group(1)) & 0x43 == 0:  # left button down
                    out.append(("click", int(m.group(2)) - 1, int(m.group(3)) - 1))
            elif m.group(5) or m.group(6):
                out.append(_ARROWS[m.group(5) or m.group(6)])
            elif len(m.group(0)) == 1:
                ch = m.group(0)
                out.append(_PLAIN.get(ch) or ch.translate(_LAYOUT).lower())
        return out
