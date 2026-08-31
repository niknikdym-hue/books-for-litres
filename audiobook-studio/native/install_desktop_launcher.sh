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

cleanup() { rm -rf "$launcher_tmp"; }
trap cleanup EXIT

[[ -d "$real_app" ]] || { print -u2 -- "Missing real app: $real_app"; exit 2; }
[[ -x "$real_exec" ]] || { print -u2 -- "Missing real executable: $real_exec"; exit 2; }
codesign --verify --deep --strict "$real_app"

mkdir -p "$contents/MacOS" "$HOME/Desktop"
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
<key>CFBundleShortVersionString</key><string>1.0</string>
<key>CFBundleVersion</key><string>1</string>
<key>LSMinimumSystemVersion</key><string>14.0</string>
<key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST

cat > "$contents/MacOS/Audiobook Studio Launcher" <<EOF
#!/bin/zsh
set -euo pipefail
real_app=${(q)real_app}
real_exec=${(q)real_exec}
workspace_root=${(q)workspace_root}

# Terminate only Audiobook Studio binaries launched from this workspace or Desktop.
for pid in \$(/usr/bin/pgrep -x 'Audiobook Studio' 2>/dev/null || true); do
  [[ "\$pid" == "\$\$" ]] && continue
  txt="\$(/usr/sbin/lsof -a -p "\$pid" -d txt -Fn 2>/dev/null | /usr/bin/sed -n 's/^n//p' | /usr/bin/head -1)"
  case "\$txt" in
    "\$workspace_root"/builds/*/Audiobook\\ Studio.app/Contents/MacOS/Audiobook\\ Studio|"\$HOME"/Desktop/Audiobook\\ Studio.app/Contents/MacOS/Audiobook\\ Studio)
      /bin/kill -TERM "\$pid" 2>/dev/null || true
      ;;
  esac
done

for _ in {1..40}; do
  alive=0
  for pid in \$(/usr/bin/pgrep -x 'Audiobook Studio' 2>/dev/null || true); do
    txt="\$(/usr/sbin/lsof -a -p "\$pid" -d txt -Fn 2>/dev/null | /usr/bin/sed -n 's/^n//p' | /usr/bin/head -1)"
    [[ "\$txt" == "\$real_exec" ]] && alive=1
  done
  [[ "\$alive" -eq 0 ]] && break
  /bin/sleep 0.1
done

/usr/bin/open -na "\$real_app"
EOF
chmod 755 "$contents/MacOS/Audiobook Studio Launcher"
plutil -lint "$contents/Info.plist"
xattr -cr "$launcher_app"
codesign --force --sign - --timestamp=none "$launcher_app"
codesign --verify --deep --strict "$launcher_app"

if [[ -e "$desktop_app" || -L "$desktop_app" ]]; then
  mkdir -p "$archive_root/desktop/$timestamp"
  mv "$desktop_app" "$archive_root/desktop/$timestamp/Audiobook Studio.app"
fi

ditto --norsrc --noextattr "$launcher_app" "$desktop_app"
xattr -cr "$desktop_app"
codesign --verify --deep --strict "$desktop_app"
print -- "$desktop_app"
