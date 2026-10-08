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
_LAYOUT = str.maketrans("йкщдтзЙКЩДТЗ", "qroltpqroltp")


class Terminal:
    def __enter__(self):
        self.fd = sys.stdin.fileno()
        self.saved = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        self.resized = True
        signal.signal(signal.SIGWINCH, self._winch)
        signal.signal(signal.SIGTERM, self._term)
        self.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h\x1b[2J")
        return self

    def __exit__(self, *exc):
        self.write("\x1b[?1006l\x1b[?1000l\x1b[?2026l\x1b[0m\x1b[?25h\x1b[?1049l")
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)

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
        """Wait up to `timeout` seconds; return decoded input events."""
        try:
            ready, _, _ = select.select([self.fd], [], [], max(0.0, timeout))
        except InterruptedError:
            return []
        if not ready:
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
