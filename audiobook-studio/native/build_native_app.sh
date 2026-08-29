#!/bin/zsh
set -euo pipefail

script_dir="${0:A:h}"
workspace_root="${AUDIOBOOK_STUDIO_HOME:-$HOME/Documents/New project/Audiobook-Studio}"
output_app="${1:-$workspace_root/builds/native-staging/Audiobook Studio.app}"
temporary_root="$(mktemp -d /tmp/audiobook-studio-native-build.XXXXXX)"
staged_app="$temporary_root/Audiobook Studio.app"
contents="$staged_app/Contents"
sdk_path="${SDKROOT:-$(xcrun --sdk macosx --show-sdk-path)}"
sdk_version="$(plutil -extract Version raw -o - "$sdk_path/SDKSettings.plist")"
swift_build="$(xcrun swiftc --version 2>/dev/null | sed -n 's/.*swiftlang-\([^ ]*\).*/\1/p')"
deployment_target="${AUDIOBOOK_STUDIO_MACOS_DEPLOYMENT_TARGET:-14.0}"
target_arch="${AUDIOBOOK_STUDIO_ARCH:-$(uname -m)}"
cache_key="${swift_build:-unknown}-macosx${sdk_version}"
module_cache="${AUDIOBOOK_STUDIO_SWIFT_MODULE_CACHE:-/tmp/audiobook-studio-swift-module-cache/$cache_key}"

cleanup() {
  rm -rf "$temporary_root"
}
trap cleanup EXIT

mkdir -p "$contents/MacOS" "$contents/Resources" "$module_cache/clang" "$module_cache/swift"
cp "$script_dir/Info.plist" "$contents/Info.plist"
print -u2 -- "Swift compiler: $(xcrun --find swiftc)"
print -u2 -- "macOS SDK: $sdk_path ($sdk_version)"
print -u2 -- "Module cache: $module_cache"
CLANG_MODULE_CACHE_PATH="$module_cache/clang" \
SWIFT_MODULECACHE_PATH="$module_cache/swift" \
xcrun swiftc \
  "$script_dir/StudioContracts.swift" \
  "$script_dir/AudioQAContracts.swift" \
  "$script_dir/EmbeddedAudioPlayer.swift" \
  "$script_dir/AudiobookStudioApp.swift" \
  -parse-as-library \
  -target "$target_arch-apple-macosx$deployment_target" \
  -sdk "$sdk_path" \
  -module-cache-path "$module_cache/swift" \
  -o "$contents/MacOS/Audiobook Studio" \
  -framework SwiftUI \
  -framework AppKit \
  -framework AVFoundation
plutil -lint "$contents/Info.plist"
xattr -cr "$staged_app"
codesign --force --sign - --timestamp=none "$staged_app"
codesign --verify --deep --strict --verbose=2 "$staged_app"

# File Provider may attach FinderInfo while an .app is assembled directly in
# the workspace. Sign in /tmp, then install without resource forks/xattrs.
mkdir -p "${output_app:h}"
if [[ -e "$output_app" ]]; then
  mv "$output_app" "$temporary_root/previous.app"
fi
if ! ditto --norsrc --noextattr "$staged_app" "$output_app"; then
  rm -rf "$output_app"
  if [[ -e "$temporary_root/previous.app" ]]; then
    mv "$temporary_root/previous.app" "$output_app"
  fi
  exit 1
fi
# Finder/File Provider may attach FinderInfo immediately after the directory
# appears at its final path. Clear only generated-bundle metadata before the
# final strict verification; signed code/resources are not modified.
xattr -cr "$output_app"
if ! codesign --verify --deep --strict --verbose=2 "$output_app"; then
  rm -rf "$output_app"
  if [[ -e "$temporary_root/previous.app" ]]; then
    mv "$temporary_root/previous.app" "$output_app"
  fi
  exit 1
fi
echo "$output_app"
