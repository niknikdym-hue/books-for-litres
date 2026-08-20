#!/bin/zsh
set -euo pipefail

script_dir="${0:A:h}"
workspace_root="${AUDIOBOOK_STUDIO_HOME:-$HOME/Documents/New project/Audiobook-Studio}"
output_app="${1:-$workspace_root/builds/native-staging/Audiobook Studio.app}"
contents="$output_app/Contents"

mkdir -p "$contents/MacOS" "$contents/Resources"
cp "$script_dir/Info.plist" "$contents/Info.plist"
xcrun swiftc "$script_dir/AudiobookStudioApp.swift" \
  -parse-as-library \
  -o "$contents/MacOS/Audiobook Studio" \
  -framework SwiftUI \
  -framework AppKit
plutil -lint "$contents/Info.plist"
echo "$output_app"
