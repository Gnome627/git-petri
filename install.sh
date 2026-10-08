#!/bin/sh
# Install git-petri for the current user. No root, no dependencies beyond Python 3.10+.
#
#   ./install.sh              install into ~/.local (or $PREFIX)
#   ./install.sh --uninstall  remove it again; accounts in ~/.config/git-petri are kept
set -eu

PREFIX="${PREFIX:-$HOME/.local}"
SHARE="$PREFIX/share/git-petri"
BIN="$PREFIX/bin"
SRC="$(cd "$(dirname "$0")" && pwd)"
# On Omarchy the installer also adds a row to the system menu.
MENU="${OMARCHY_MENU:-${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/extensions/omarchy-menu.jsonc}"
MARK_OPEN="// >>> git-petri >>>"
MARK_CLOSE="// <<< git-petri <<<"

menu_remove() {
    [ -f "$MENU" ] && grep -qF "$MARK_OPEN" "$MENU" || return 0
    sed "\\|$MARK_OPEN|,\\|$MARK_CLOSE|d" "$MENU" > "$MENU.tmp" && mv "$MENU.tmp" "$MENU"
}

menu_add() {
    command -v omarchy-launch-or-focus-tui >/dev/null 2>&1 || return 0
    [ -f "$MENU" ] || { mkdir -p "$(dirname "$MENU")" && printf '{\n}\n' > "$MENU"; }
    if ! grep -q '^[[:space:]]*{[[:space:]]*$' "$MENU"; then
        echo "note: could not find where to add a row in $MENU — left untouched"
        return 0
    fi
    row="  \"git-petri\": {\"icon\": \"󰊢\", \"label\": \"Git Petri\", \"aliases\": [\"petri\", \"git\"], \"description\": \"git-petri — репозитории и CI в чашке Петри\", \"action\": \"omarchy-launch-or-focus-tui $BIN/git-petri\"},"
    if grep -qF "$MARK_OPEN" "$MENU"; then
        # Already there: refresh the row where it stands, so a reinstall keeps your ordering.
        awk -v head="$MARK_OPEN" -v row="$row" -v tail="$MARK_CLOSE" '
            index($0, head) { print; print row; skip = 1; next }
            index($0, tail) { skip = 0 }
            !skip { print }
        ' "$MENU" > "$MENU.tmp"
    else
        cp "$MENU" "$MENU.bak.$(date +%s)"
        awk -v head="$MARK_OPEN" -v row="$row" -v tail="$MARK_CLOSE" '
            { print }
            !done && /^[[:space:]]*\{[[:space:]]*$/ { print head; print row; print tail; done = 1 }
        ' "$MENU" > "$MENU.tmp"
    fi
    if grep -qF "$MARK_CLOSE" "$MENU.tmp"; then
        mv "$MENU.tmp" "$MENU"
        echo "added to the Omarchy menu: Git Petri"
    else
        rm -f "$MENU.tmp"
        echo "note: could not update $MENU — left untouched"
    fi
}

if [ "${1:-}" = "--uninstall" ]; then
    rm -rf "$SHARE"
    rm -f "$BIN/git-petri"
    menu_remove
    echo "git-petri removed (accounts kept in ${XDG_CONFIG_HOME:-$HOME/.config}/git-petri)"
    exit 0
fi

hint() {
    if command -v pacman >/dev/null 2>&1; then echo "sudo pacman -S $1"
    elif command -v apt-get >/dev/null 2>&1; then echo "sudo apt install $2"
    elif command -v dnf >/dev/null 2>&1; then echo "sudo dnf install $2"
    else echo "install $2 with your package manager"
    fi
}

if ! command -v python3 >/dev/null 2>&1; then
    echo "git-petri needs Python 3.10 or newer: $(hint python python3)" >&2
    exit 1
fi
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
    echo "git-petri needs Python 3.10 or newer, found $(python3 -V 2>&1)" >&2
    exit 1
fi
# Debian and Ubuntu split parts of the standard library into separate packages.
if ! python3 -c 'import ssl, termios, json, urllib.request' 2>/dev/null; then
    echo "this Python lacks ssl or termios: $(hint python python3-minimal\ libpython3-stdlib)" >&2
    exit 1
fi

mkdir -p "$SHARE" "$BIN"
rm -rf "$SHARE/gitpetri"
cp -R "$SRC/gitpetri" "$SHARE/gitpetri"
find "$SHARE/gitpetri" -name __pycache__ -type d -prune -exec rm -rf {} +
cp "$SRC/git-petri" "$SHARE/git-petri"
chmod 755 "$SHARE/git-petri"
ln -sf "$SHARE/git-petri" "$BIN/git-petri"

echo "git-petri installed: $BIN/git-petri"
menu_add
command -v xdg-open >/dev/null 2>&1 ||
    echo "note: xdg-open is missing, so opening links will not work: $(hint xdg-utils xdg-utils)"
case ":$PATH:" in
    *":$BIN:"*) echo "run: git-petri   (or: git petri, git-petri --demo)" ;;
    *) echo "note: $BIN is not in PATH — add it:  export PATH=\"$BIN:\$PATH\"" ;;
esac
