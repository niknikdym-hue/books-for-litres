#!/bin/zsh
set -euo pipefail

script_dir="${0:A:h}"
workspace_root="${AUDIOBOOK_STUDIO_HOME:-$HOME/Documents/New project/Audiobook-Studio}"
output_app="${1:-$workspace_root/builds/native-staging/Audiobook Studio.app}"
contents="$output_app/Contents"
sdk_path="${SDKROOT:-$(xcrun --sdk macosx --show-sdk-path)}"
sdk_version="$(plutil -extract Version raw -o - "$sdk_path/SDKSettings.plist")"
swift_build="$(xcrun swiftc --version 2>/dev/null | sed -n 's/.*swiftlang-\([^ ]*\).*/\1/p')"
deployment_target="${AUDIOBOOK_STUDIO_MACOS_DEPLOYMENT_TARGET:-14.0}"
target_arch="${AUDIOBOOK_STUDIO_ARCH:-$(uname -m)}"
cache_key="${swift_build:-unknown}-macosx${sdk_version}"
module_cache="${AUDIOBOOK_STUDIO_SWIFT_MODULE_CACHE:-/tmp/audiobook-studio-swift-module-cache/$cache_key}"

mkdir -p "$contents/MacOS" "$contents/Resources" "$module_cache/clang" "$module_cache/swift"
cp "$script_dir/Info.plist" "$contents/Info.plist"
print -u2 -- "Swift compiler: $(xcrun --find swiftc)"
print -u2 -- "macOS SDK: $sdk_path ($sdk_version)"
print -u2 -- "Module cache: $module_cache"
CLANG_MODULE_CACHE_PATH="$module_cache/clang" \
SWIFT_MODULECACHE_PATH="$module_cache/swift" \
xcrun swiftc "$script_dir/StudioContracts.swift" "$script_dir/AudiobookStudioApp.swift" \
  -parse-as-library \
  -target "$target_arch-apple-macosx$deployment_target" \
  -sdk "$sdk_path" \
  -module-cache-path "$module_cache/swift" \
  -o "$contents/MacOS/Audiobook Studio" \
  -framework SwiftUI \
  -framework AppKit
plutil -lint "$contents/Info.plist"
xattr -cr "$output_app"
codesign --force --sign - --timestamp=none "$output_app"
codesign --verify --deep --strict --verbose=2 "$output_app"
echo "$output_app"
