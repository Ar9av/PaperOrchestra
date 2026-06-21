#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Build the native PaperOrchestra macOS launcher app bundle.

Usage:
  scripts/build_native_launcher.sh [--debug] [--output-dir DIR] [--open]

Options:
  --debug            Build the Xcode app in debug mode.
  --output-dir DIR   Write the staged .app bundle to DIR. Default: ./dist
  --open             Open the staged app after building.
  --help             Show this help text.
EOF
}

MODE="release"
OUTPUT_DIR=""
OPEN_AFTER_BUILD="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --debug)
      MODE="debug"
      shift
      ;;
    --output-dir)
      OUTPUT_DIR="${2:-}"
      shift 2
      ;;
    --open)
      OPEN_AFTER_BUILD="1"
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

APP_NAME="PaperOrchestra"
DIST_DIR="${OUTPUT_DIR:-$ROOT_DIR/dist}"
APP_BUNDLE="$DIST_DIR/$APP_NAME.app"
CONFIGURATION="Release"
if [[ "$MODE" == "debug" ]]; then
  CONFIGURATION="Debug"
fi
DERIVED_DATA_PATH="$ROOT_DIR/.build/xcode/DerivedData"
BUILT_APP_BUNDLE="$DERIVED_DATA_PATH/Build/Products/$CONFIGURATION/$APP_NAME.app"

mkdir -p "$DIST_DIR"

CONFIGURATION="$CONFIGURATION" "$ROOT_DIR/scripts/build.sh"

if [[ ! -d "$BUILT_APP_BUNDLE" ]]; then
  echo "Built app bundle not found at $BUILT_APP_BUNDLE" >&2
  exit 1
fi

rm -rf "$APP_BUNDLE"
cp -R "$BUILT_APP_BUNDLE" "$APP_BUNDLE"
codesign --force --deep --sign - "$APP_BUNDLE" >/dev/null

echo "Built $APP_BUNDLE"

if [[ "$OPEN_AFTER_BUILD" == "1" ]]; then
  /usr/bin/open -n "$APP_BUNDLE"
fi
