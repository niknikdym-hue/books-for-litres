#!/bin/zsh
set -euo pipefail

# Historical filename kept only to avoid breaking callers.
# This script no longer installs a launcher. It installs the real, signed
# Audiobook Studio bundle directly on Desktop.
workspace_root="${AUDIOBOOK_STUDIO_HOME:-$HOME/Documents/New project/Audiobook-Studio}"
real_app="${1:-$workspace_root/builds/native-staging/Audiobook Studio.app}"
desktop_app="$HOME/Desktop/Audiobook Studio.app"
real_exec="$real_app/Contents/MacOS/Audiobook Studio"
archive_root="$HOME/Library/Application Support/Audiobook Studio/Archives"
timestamp="$(date +%Y%m%d-%H%M%S)"
staging_name=".Audiobook Studio.installing.$$.app"
desktop_staging="$HOME/Desktop/$staging_name"
archive_dir="$archive_root/desktop/$timestamp"
archive_previous="$archive_dir/Audiobook Studio.app"

cleanup() {
  if [[ -e "$desktop_staging" || -L "$desktop_staging" ]]; then
    rm -rf "$desktop_staging"
  fi
}
trap cleanup EXIT

[[ -d "$real_app" ]] || { print -u2 -- "Missing real app: $real_app"; exit 2; }
[[ -x "$real_exec" ]] || { print -u2 -- "Missing real executable: $real_exec"; exit 2; }
codesign --verify --deep --strict "$real_app"

real_bundle_id="$(plutil -extract CFBundleIdentifier raw -o - "$real_app/Contents/Info.plist")"
[[ "$real_bundle_id" == "ru.elena.audiobookstudio" ]] || {
  print -u2 -- "Unexpected real app bundle id: $real_bundle_id"
  exit 2
}

mkdir -p "$HOME/Desktop"
rm -rf "$desktop_staging"

# Stage the real bundle on the Desktop filesystem first so the final rename is
# local and the owner never launches a partially copied app.
ditto --norsrc --noextattr "$real_app" "$desktop_staging"
xattr -cr "$desktop_staging"
codesign --verify --deep --strict "$desktop_staging"

staged_id="$(plutil -extract CFBundleIdentifier raw -o - "$desktop_staging/Contents/Info.plist")"
[[ "$staged_id" == "ru.elena.audiobookstudio" ]] || {
  print -u2 -- "Unexpected staged Desktop app bundle id: $staged_id"
  exit 1
}

previous_archived=0
if [[ -e "$desktop_app" || -L "$desktop_app" ]]; then
  mkdir -p "$archive_dir"
  mv "$desktop_app" "$archive_previous"
  previous_archived=1
fi

if ! mv "$desktop_staging" "$desktop_app"; then
  if [[ "$previous_archived" -eq 1 && -e "$archive_previous" ]]; then
    mv "$archive_previous" "$desktop_app" || true
  fi
  exit 1
fi

# Finder/File Provider may attach metadata immediately at the final path.
xattr -cr "$desktop_app"
if ! codesign --verify --deep --strict "$desktop_app"; then
  rm -rf "$desktop_app"
  if [[ "$previous_archived" -eq 1 && -e "$archive_previous" ]]; then
    mv "$archive_previous" "$desktop_app" || true
  fi
  exit 1
fi

installed_id="$(plutil -extract CFBundleIdentifier raw -o - "$desktop_app/Contents/Info.plist")"
[[ "$installed_id" == "ru.elena.audiobookstudio" ]] || {
  print -u2 -- "Unexpected installed Desktop app bundle id: $installed_id"
  exit 1
}

installed_exec="$desktop_app/Contents/MacOS/Audiobook Studio"
[[ -x "$installed_exec" ]] || {
  print -u2 -- "Installed Desktop executable missing: $installed_exec"
  exit 1
}
file "$installed_exec" | grep -q 'Mach-O' || {
  print -u2 -- "Installed Desktop executable is not native Mach-O"
  exit 1
}

print -- "$desktop_app"
