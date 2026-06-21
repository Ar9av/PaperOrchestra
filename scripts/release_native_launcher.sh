#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Build, sign, optionally notarize, and optionally install the PaperOrchestra app.

Required environment:
  PAPER_ORCHESTRA_SIGN_IDENTITY      Developer ID Application identity name

Optional environment:
  PAPER_ORCHESTRA_NOTARY_PROFILE     notarytool keychain profile name

Usage:
  scripts/release_native_launcher.sh [--debug] [--install] [--skip-notarize] [--output-dir DIR]

Options:
  --debug            Build Debug instead of Release.
  --install          Copy the signed app to /Applications after verification.
  --skip-notarize    Sign only; do not submit to notarytool.
  --output-dir DIR   Output directory. Default: ./dist/release
  --help             Show this help text.
EOF
}

MODE="release"
INSTALL_AFTER="0"
SKIP_NOTARIZE="0"
OUTPUT_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --debug)
      MODE="debug"
      shift
      ;;
    --install)
      INSTALL_AFTER="1"
      shift
      ;;
    --skip-notarize)
      SKIP_NOTARIZE="1"
      shift
      ;;
    --output-dir)
      OUTPUT_DIR="${2:-}"
      shift 2
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
APP_NAME="PaperOrchestra"
SIGN_IDENTITY="${PAPER_ORCHESTRA_SIGN_IDENTITY:-}"
NOTARY_PROFILE="${PAPER_ORCHESTRA_NOTARY_PROFILE:-}"
DIST_DIR="${OUTPUT_DIR:-$ROOT_DIR/dist/release}"
SIGNED_APP="$DIST_DIR/$APP_NAME.app"
ZIP_PATH="$DIST_DIR/$APP_NAME.zip"

if [[ -z "$SIGN_IDENTITY" ]]; then
  echo "Missing PAPER_ORCHESTRA_SIGN_IDENTITY. Example:" >&2
  echo "  export PAPER_ORCHESTRA_SIGN_IDENTITY='Developer ID Application: Your Name (TEAMID)'" >&2
  exit 1
fi

if [[ "$SKIP_NOTARIZE" != "1" && -z "$NOTARY_PROFILE" ]]; then
  echo "Missing PAPER_ORCHESTRA_NOTARY_PROFILE for notarization." >&2
  echo "Set --skip-notarize to sign without notarization." >&2
  exit 1
fi

mkdir -p "$DIST_DIR"
if [[ "$MODE" == "debug" ]]; then
  /bin/bash "$ROOT_DIR/scripts/build_native_launcher.sh" --debug --output-dir "$DIST_DIR"
else
  /bin/bash "$ROOT_DIR/scripts/build_native_launcher.sh" --output-dir "$DIST_DIR"
fi

if [[ ! -d "$SIGNED_APP" ]]; then
  echo "Built app bundle not found at $SIGNED_APP" >&2
  exit 1
fi

xattr -cr "$SIGNED_APP"
codesign --force --deep --options runtime --timestamp --sign "$SIGN_IDENTITY" "$SIGNED_APP"
codesign --verify --deep --strict --verbose=2 "$SIGNED_APP"

if [[ "$SKIP_NOTARIZE" != "1" ]]; then
  rm -f "$ZIP_PATH"
  ditto -c -k --sequesterRsrc --keepParent "$SIGNED_APP" "$ZIP_PATH"
  xcrun notarytool submit "$ZIP_PATH" --keychain-profile "$NOTARY_PROFILE" --wait
  xcrun stapler staple "$SIGNED_APP"
fi

spctl -a -vv "$SIGNED_APP"

if [[ "$INSTALL_AFTER" == "1" ]]; then
  rm -rf "/Applications/$APP_NAME.app"
  cp -R "$SIGNED_APP" "/Applications/$APP_NAME.app"
  xattr -cr "/Applications/$APP_NAME.app"
  echo "Installed /Applications/$APP_NAME.app"
fi

echo "Release-ready app: $SIGNED_APP"
if [[ -f "$ZIP_PATH" ]]; then
  echo "Notarized archive: $ZIP_PATH"
fi
