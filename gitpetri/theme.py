"""Palette from the active omarchy theme, reloaded when the theme changes."""

import os
import tomllib

PATHS = (
    "~/.local/state/omarchy/current/theme/colors.toml",
    "~/.config/omarchy/current/theme/colors.toml",
)
FALLBACK = {
    "background": "#1a1b26", "foreground": "#c0caf5", "bright_foreground": "#e6e9f5",
    "muted": "#565f89", "accent": "#7aa2f7", "red": "#f7768e", "bright_red": "#ff9aa8",
    "green": "#9ece6a", "bright_green": "#b9f27c", "yellow": "#e0af68",
    "cyan": "#7dcfff", "magenta": "#bb9af7", "orange": "#ff9e64",
}


def rgb(s):
    s = s.lstrip("#")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def mix(a, b, f):
    return (int(a[0] + (b[0] - a[0]) * f), int(a[1] + (b[1] - a[1]) * f),
            int(a[2] + (b[2] - a[2]) * f))


def pack(c):
    return (c[0] << 16) | (c[1] << 8) | c[2]


class Theme:
    def __init__(self):
        self.path = next((p for p in map(os.path.expanduser, PATHS) if os.path.exists(p)), None)
        self.mtime = None
        self.load()

    def load(self):
        raw = dict(FALLBACK)
        if self.path:
            try:
                self.mtime = os.stat(self.path).st_mtime
                with open(self.path, "rb") as f:
                    raw.update({k: v for k, v in tomllib.load(f).items()
                                if isinstance(v, str) and v.startswith("#")})
            except (OSError, ValueError):
                pass
        c = {k: rgb(v) for k, v in raw.items()}
        self.bg, self.fg = c["background"], c["foreground"]
        self.bright = c["bright_foreground"]
        self.muted, self.accent = c["muted"], c["accent"]
        self.red, self.bright_red = c["red"], c["bright_red"]
        self.green, self.bright_green = c["green"], c["bright_green"]
        self.yellow = c["yellow"]
        # One hue per kind of organism; red / green / yellow are reserved for CI.
        self.kind = {
            "org": self.accent,
            "repo": mix(c["orange"], self.fg, 0.45),
            "branch": c["cyan"],
            "pr": c["magenta"],
        }
        self.rim = mix(self.bg, self.muted, 0.75)
        self.speck = mix(self.bg, self.muted, 0.35)
        self.dim = mix(self.bg, self.fg, 0.5)

    def changed(self):
        if not self.path:
            return False
        try:
            if os.stat(self.path).st_mtime == self.mtime:
                return False
        except OSError:
            return False
        self.load()
        return True
