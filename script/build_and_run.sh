#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Build, test, install, or run the native PaperOrchestra macOS app.

Usage:
  script/build_and_run.sh [run|--debug|--logs|--telemetry|--verify|--test]
                          [--release|--debug-build] [--install] [--no-open]

Examples:
  script/build_and_run.sh
  script/build_and_run.sh --release --install --no-open
  script/build_and_run.sh --test --no-open

Options:
  --release       Build the Release configuration. Default.
  --debug-build   Build the Debug configuration.
  --install       Copy the built app to /Applications/PaperOrchestra.app.
  --no-open       Build or install without launching the app.
  --test          Build the native Xcode app and run Swift package tests.
  --debug         Launch the staged app under lldb after building.
  --logs          Launch and stream process logs.
  --telemetry     Launch and stream subsystem logs.
  --verify        Launch and verify the process exists.
EOF
}

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="PaperOrchestra"
BUNDLE_ID="com.paperorchestra.launcher"
DIST_DIR="$ROOT_DIR/dist"
APP_BUNDLE="$DIST_DIR/$APP_NAME.app"
INSTALL_BUNDLE="/Applications/$APP_NAME.app"

CONFIGURATION="Release"
ACTION="run"
INSTALL_AFTER_BUILD="0"
OPEN_AFTER_BUILD="1"

while [[ $# -gt 0 ]]; do
  case "$1" in
    run)
      ACTION="run"
      shift
      ;;
    --release|release)
      CONFIGURATION="Release"
      shift
      ;;
    --debug-build)
      CONFIGURATION="Debug"
      shift
      ;;
    --debug|debug)
      ACTION="debug"
      CONFIGURATION="Debug"
      shift
      ;;
    --logs|logs)
      ACTION="logs"
      shift
      ;;
    --telemetry|telemetry)
      ACTION="telemetry"
      shift
      ;;
    --verify|verify)
      ACTION="verify"
      shift
      ;;
    --test|test)
      ACTION="test"
      OPEN_AFTER_BUILD="0"
      shift
      ;;
    --install|install)
      INSTALL_AFTER_BUILD="1"
      shift
      ;;
    --no-open|build|--build-only)
      OPEN_AFTER_BUILD="0"
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

export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode-beta.app/Contents/Developer}"
export CONFIGURATION

pkill -x "$APP_NAME" >/dev/null 2>&1 || true

build_app() {
  local build_args=()
  if [[ "$CONFIGURATION" == "Debug" ]]; then
    build_args+=(--debug)
  fi
  build_args+=(--output-dir "$DIST_DIR")
  "$ROOT_DIR/scripts/build_native_launcher.sh" "${build_args[@]}"
}

install_app() {
  if [[ ! -d "$APP_BUNDLE" ]]; then
    echo "Built app bundle not found at $APP_BUNDLE" >&2
    exit 1
  fi
  rm -rf "$INSTALL_BUNDLE"
  cp -R "$APP_BUNDLE" "$INSTALL_BUNDLE"
  codesign --force --deep --sign - "$INSTALL_BUNDLE" >/dev/null
  echo "Installed $INSTALL_BUNDLE"
}

open_target_app() {
  local target="$APP_BUNDLE"
  if [[ "$INSTALL_AFTER_BUILD" == "1" ]]; then
    target="$INSTALL_BUNDLE"
  fi
  /usr/bin/open -n "$target"
}

run_tests() {
  build_app
  env DEVELOPER_DIR="$DEVELOPER_DIR" xcrun swift test
}

if [[ "$ACTION" == "test" ]]; then
  run_tests
  if [[ "$INSTALL_AFTER_BUILD" == "1" ]]; then
    install_app
  fi
  exit 0
fi

build_app

if [[ "$INSTALL_AFTER_BUILD" == "1" ]]; then
  install_app
fi

if [[ "$OPEN_AFTER_BUILD" == "0" ]]; then
  exit 0
fi

case "$ACTION" in
  run)
    open_target_app
    ;;
  debug)
    target="$APP_BUNDLE"
    if [[ "$INSTALL_AFTER_BUILD" == "1" ]]; then
      target="$INSTALL_BUNDLE"
    fi
    lldb -- "$target/Contents/MacOS/$APP_NAME"
    ;;
  logs)
    open_target_app
    /usr/bin/log stream --info --style compact --predicate "process == \"$APP_NAME\""
    ;;
  telemetry)
    open_target_app
    /usr/bin/log stream --info --style compact --predicate "subsystem == \"$BUNDLE_ID\""
    ;;
  verify)
    open_target_app
    sleep 1
    pgrep -x "$APP_NAME" >/dev/null
    ;;
  *)
    echo "Unknown action: $ACTION" >&2
    exit 2
    ;;
esac
