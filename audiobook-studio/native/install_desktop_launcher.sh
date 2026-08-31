#!/bin/zsh
set -euo pipefail

script_dir="${0:A:h}"
workspace_root="${AUDIOBOOK_STUDIO_HOME:-$HOME/Documents/New project/Audiobook-Studio}"
real_app="${1:-$workspace_root/builds/native-staging/Audiobook Studio.app}"
desktop_app="$HOME/Desktop/Audiobook Studio.app"
launcher_tmp="$(mktemp -d /tmp/audiobook-studio-launcher.XXXXXX)"
launcher_app="$launcher_tmp/Audiobook Studio.app"
contents="$launcher_app/Contents"
real_exec="$real_app/Contents/MacOS/Audiobook Studio"
archive_root="$HOME/Library/Application Support/Audiobook Studio/Archives"
timestamp="$(date +%Y%m%d-%H%M%S)"
sdk_path="${SDKROOT:-$(xcrun --sdk macosx --show-sdk-path)}"
deployment_target="${AUDIOBOOK_STUDIO_MACOS_DEPLOYMENT_TARGET:-14.0}"
target_arch="${AUDIOBOOK_STUDIO_ARCH:-$(uname -m)}"
module_cache="${AUDIOBOOK_STUDIO_LAUNCHER_MODULE_CACHE:-/tmp/audiobook-studio-launcher-module-cache}"
launcher_bundle_id="ru.elena.audiobookstudio.launcher"

cleanup() { rm -rf "$launcher_tmp"; }
trap cleanup EXIT

[[ -d "$real_app" ]] || { print -u2 -- "Missing real app: $real_app"; exit 2; }
[[ -x "$real_exec" ]] || { print -u2 -- "Missing real executable: $real_exec"; exit 2; }
codesign --verify --deep --strict "$real_app"

real_bundle_id="$(plutil -extract CFBundleIdentifier raw -o - "$real_app/Contents/Info.plist")"
[[ "$real_bundle_id" == "ru.elena.audiobookstudio" ]] || {
  print -u2 -- "Unexpected real app bundle id: $real_bundle_id"
  exit 2
}

mkdir -p "$contents/MacOS" "$HOME/Desktop" "$module_cache/clang" "$module_cache/swift"
cat > "$contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleDevelopmentRegion</key><string>ru</string>
<key>CFBundleDisplayName</key><string>Audiobook Studio</string>
<key>CFBundleExecutable</key><string>Audiobook Studio Launcher</string>
<key>CFBundleIdentifier</key><string>ru.elena.audiobookstudio.launcher</string>
<key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
<key>CFBundleName</key><string>Audiobook Studio</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>1.1</string>
<key>CFBundleVersion</key><string>2</string>
<key>LSMinimumSystemVersion</key><string>14.0</string>
<key>LSUIElement</key><true/>
<key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST

CLANG_MODULE_CACHE_PATH="$module_cache/clang" \
SWIFT_MODULECACHE_PATH="$module_cache/swift" \
xcrun swiftc \
  "$script_dir/DesktopLauncher.swift" \
  -parse-as-library \
  -target "$target_arch-apple-macosx$deployment_target" \
  -sdk "$sdk_path" \
  -module-cache-path "$module_cache/swift" \
  -o "$contents/MacOS/Audiobook Studio Launcher" \
  -framework AppKit

plutil -lint "$contents/Info.plist"
xattr -cr "$launcher_app"
codesign --force --sign - --timestamp=none "$launcher_app"
codesign --verify --deep --strict "$launcher_app"

if [[ -e "$desktop_app" || -L "$desktop_app" ]]; then
  existing_id=""
  if [[ ! -L "$desktop_app" && -f "$desktop_app/Contents/Info.plist" ]]; then
    existing_id="$(plutil -extract CFBundleIdentifier raw -o - "$desktop_app/Contents/Info.plist" 2>/dev/null || true)"
  fi
  if [[ "$existing_id" == "$launcher_bundle_id" ]]; then
    rm -rf "$desktop_app"
  else
    mkdir -p "$archive_root/desktop/$timestamp"
    mv "$desktop_app" "$archive_root/desktop/$timestamp/Audiobook Studio.app"
  fi
fi

if ! ditto --norsrc --noextattr "$launcher_app" "$desktop_app"; then
  rm -rf "$desktop_app"
  exit 1
fi
xattr -cr "$desktop_app"
codesign --verify --deep --strict "$desktop_app"
installed_id="$(plutil -extract CFBundleIdentifier raw -o - "$desktop_app/Contents/Info.plist")"
[[ "$installed_id" == "$launcher_bundle_id" ]] || {
  print -u2 -- "Unexpected installed launcher bundle id: $installed_id"
  exit 1
}
file "$desktop_app/Contents/MacOS/Audiobook Studio Launcher" | grep -q 'Mach-O' || {
  print -u2 -- "Desktop launcher executable is not native Mach-O"
  exit 1
}
print -- "$desktop_app"
