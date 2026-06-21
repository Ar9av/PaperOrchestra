#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_PATH="$ROOT_DIR/PaperOrchestra.xcodeproj"
SCHEME="PaperOrchestra"
DESTINATION="${DESTINATION:-platform=macOS,arch=arm64}"
DERIVED_DATA_PATH="$ROOT_DIR/.build/xcode/DerivedData"
CONFIGURATION="${CONFIGURATION:-Release}"

if [[ ! -d "$PROJECT_PATH" ]]; then
  echo "Missing Xcode project at $PROJECT_PATH" >&2
  exit 1
fi

cd "$ROOT_DIR"

xcodebuild \
  -list \
  -project "$PROJECT_PATH"

xcodebuild \
  -project "$PROJECT_PATH" \
  -scheme "$SCHEME" \
  -configuration "$CONFIGURATION" \
  -destination "$DESTINATION" \
  -derivedDataPath "$DERIVED_DATA_PATH" \
  build \
  ARCHS=arm64 \
  ONLY_ACTIVE_ARCH=YES \
  CODE_SIGNING_ALLOWED=NO
