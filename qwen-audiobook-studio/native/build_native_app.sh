#!/bin/zsh
set -euo pipefail

script_dir="${0:A:h}"
output_app="${1:-$script_dir/build/Audiobook Studio.app}"
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
