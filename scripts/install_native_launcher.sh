#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Install PaperOrchestra.app into /Applications by default.

Usage:
  scripts/install_native_launcher.sh [--install-dir DIR] [--system] [--open]

Options:
  --install-dir DIR  Override the install directory.
  --system           Install to /Applications explicitly.
  --open             Open the installed app after copying.
  --help             Show this help text.
EOF
}

INSTALL_DIR=""
OPEN_AFTER_INSTALL="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-dir)
      INSTALL_DIR="${2:-}"
      shift 2
      ;;
    --system)
      INSTALL_DIR="/Applications"
      shift
      ;;
    --open)
      OPEN_AFTER_INSTALL="1"
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

TARGET_DIR="${INSTALL_DIR:-/Applications}"
APP_NAME="PaperOrchestra.app"
SOURCE_APP="$ROOT_DIR/dist/$APP_NAME"
TARGET_APP="$TARGET_DIR/$APP_NAME"

/bin/bash "$ROOT_DIR/scripts/build_native_launcher.sh"

mkdir -p "$TARGET_DIR"
rm -rf "$TARGET_APP"
cp -R "$SOURCE_APP" "$TARGET_APP"
codesign --force --deep --sign - "$TARGET_APP" >/dev/null

echo "Installed $TARGET_APP"

if [[ "$OPEN_AFTER_INSTALL" == "1" ]]; then
  /usr/bin/open -n "$TARGET_APP"
fi
