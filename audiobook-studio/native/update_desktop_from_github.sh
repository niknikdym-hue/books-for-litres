#!/bin/zsh
set -euo pipefail

# Owner-visible Audiobook Studio update path for the canonical Mac.
#
# Why this exists:
# - downloaded ad-hoc-signed .app archives are quarantined by Gatekeeper;
# - this updater downloads SOURCE only, builds the app locally on the owner's Mac,
#   then installs the locally-built bundle on Desktop;
# - no TTS/provider/model/paid request is executed here;
# - production books/renders/cache/QA/billing state are never copied from GitHub
#   and are never deleted by this updater.

readonly repository_url="https://github.com/niknikdym-hue/books-for-litres.git"
readonly source_sha="109ade8174b491002269d7a1b3fad3c5a041f772"
readonly workspace_root="${AUDIOBOOK_STUDIO_HOME:-$HOME/Documents/New project/Audiobook-Studio}"
readonly runtime_root="$workspace_root/runtime/studio-workspace"
readonly python_executable="${AUDIOBOOK_STUDIO_PYTHON:-$workspace_root/engines/qwen-mlx/.venv/bin/python}"
readonly desktop_app="$HOME/Desktop/Audiobook Studio.app"
readonly archive_root="$HOME/Library/Application Support/Audiobook Studio/Archives"
readonly timestamp="$(date +%Y%m%d-%H%M%S)"
readonly temporary_root="$(mktemp -d /tmp/audiobook-studio-owner-update.XXXXXX)"
readonly checkout_root="$temporary_root/repository"
readonly source_root="$checkout_root/audiobook-studio"
readonly candidate_app="$temporary_root/Audiobook Studio.app"
readonly runtime_backup="$archive_root/runtime-code/$timestamp"
readonly new_files_manifest="$runtime_backup/new-top-level-files.txt"

runtime_changed=0

cleanup() {
  rm -rf "$temporary_root"
}
trap cleanup EXIT

fail() {
  print -u2 -- "Audiobook Studio update blocked: $1"
  exit 2
}

for command_path in /usr/bin/git /usr/bin/xcrun /usr/bin/codesign /usr/bin/ditto /usr/bin/open; do
  [[ -x "$command_path" ]] || fail "missing required macOS tool: $command_path"
done

[[ -d "$workspace_root" ]] || fail "workspace not found: $workspace_root"
[[ -d "$runtime_root" ]] || fail "runtime not found: $runtime_root"
[[ ! -L "$runtime_root" ]] || fail "runtime must not be a symlink"
[[ -x "$python_executable" ]] || fail "Studio Python not found: $python_executable"

mkdir -p "$checkout_root"
/usr/bin/git -C "$checkout_root" init -q
/usr/bin/git -C "$checkout_root" remote add origin "$repository_url"
/usr/bin/git -C "$checkout_root" fetch -q --depth 1 origin "$source_sha"
/usr/bin/git -C "$checkout_root" checkout -q --detach FETCH_HEAD
actual_sha="$(/usr/bin/git -C "$checkout_root" rev-parse HEAD)"
[[ "$actual_sha" == "$source_sha" ]] || fail "source identity mismatch"

# Build first, before changing any local runtime code. The output lives in /tmp,
# so build_native_app.sh cannot silently replace the Desktop application here.
AUDIOBOOK_STUDIO_HOME="$workspace_root" \
  /bin/zsh "$source_root/native/build_native_app.sh" "$candidate_app" >/dev/null
[[ -d "$candidate_app" ]] || fail "local native build did not produce an app"
/usr/bin/codesign --verify --deep --strict "$candidate_app" || fail "local native signature verification failed"
bundle_id="$(/usr/bin/plutil -extract CFBundleIdentifier raw -o - "$candidate_app/Contents/Info.plist")"
[[ "$bundle_id" == "ru.elena.audiobookstudio" ]] || fail "unexpected bundle id: $bundle_id"

mkdir -p "$runtime_backup"
: > "$new_files_manifest"

managed_top_level=()
for source_file in "$source_root"/*.py "$source_root"/*.json; do
  [[ -f "$source_file" ]] || continue
  managed_top_level+=("${source_file:t}")
done

rollback_runtime() {
  (( runtime_changed == 1 )) || return 0
  for name in "${managed_top_level[@]}"; do
    if [[ -f "$runtime_backup/top-level/$name" ]]; then
      /usr/bin/ditto --norsrc --noextattr "$runtime_backup/top-level/$name" "$runtime_root/$name"
    else
      rm -f "$runtime_root/$name"
    fi
  done
  for directory in backends contracts; do
    rm -rf "$runtime_root/$directory"
    if [[ -d "$runtime_backup/$directory" ]]; then
      /usr/bin/ditto --norsrc --noextattr "$runtime_backup/$directory" "$runtime_root/$directory"
    fi
  done
}

mkdir -p "$runtime_backup/top-level"
for name in "${managed_top_level[@]}"; do
  target="$runtime_root/$name"
  if [[ -L "$target" ]]; then
    fail "refuse to replace symlinked runtime file: $target"
  fi
  if [[ -f "$target" ]]; then
    /usr/bin/ditto --norsrc --noextattr "$target" "$runtime_backup/top-level/$name"
  else
    print -- "$name" >> "$new_files_manifest"
  fi
done

for directory in backends contracts; do
  target="$runtime_root/$directory"
  [[ ! -L "$target" ]] || fail "refuse to replace symlinked runtime directory: $target"
  if [[ -d "$target" ]]; then
    /usr/bin/ditto --norsrc --noextattr "$target" "$runtime_backup/$directory"
  fi
done

runtime_changed=1
trap 'rollback_runtime; cleanup' EXIT

# Synchronize code/config only. Local production data directories are deliberately
# outside this managed set and therefore remain untouched.
for name in "${managed_top_level[@]}"; do
  source_file="$source_root/$name"
  temporary_target="$runtime_root/.$name.update.$$"
  rm -f "$temporary_target"
  /usr/bin/ditto --norsrc --noextattr "$source_file" "$temporary_target"
  mv -f "$temporary_target" "$runtime_root/$name"
done

for directory in backends contracts; do
  staged="$runtime_root/.$directory.update.$$"
  rm -rf "$staged"
  /usr/bin/ditto --norsrc --noextattr "$source_root/$directory" "$staged"
  rm -rf "$runtime_root/$directory"
  mv "$staged" "$runtime_root/$directory"
done

# Offline-only local smoke: syntax/import surface plus the Content Quality status.
(
  cd "$runtime_root"
  "$python_executable" -m py_compile \
    content_quality_runner.py \
    tts_text_review_runner.py \
    tts_text_review.py \
    tts_pronunciation_apply.py \
    book_text_preparation.py \
    book_sound_design.py \
    book_sound_runner.py
  status_json="$(OPENAI_API_KEY='' YANDEX_API_KEY='' YANDEX_CLOUD_API_KEY='' \
    "$python_executable" content_quality_runner.py --status)"
  STATUS_JSON="$status_json" "$python_executable" - <<'PY'
import json
import os

value = json.loads(os.environ["STATUS_JSON"])
assert value.get("provider_requests") == 0
assert value.get("remote_request_sent") is False
assert value.get("model_calls") == 0
assert value.get("paid_execution") is False
assert value.get("billing_changed") is False
PY
) || fail "offline runtime smoke failed; previous runtime code will be restored"

# Install the locally built app, archiving the previous Desktop bundle through
# the accepted fail-safe installer. Because the bundle was built on this Mac,
# this path does not depend on downloading/unpacking a quarantined .app archive.
AUDIOBOOK_STUDIO_HOME="$workspace_root" \
  /bin/zsh "$source_root/native/install_desktop_launcher.sh" "$candidate_app" >/dev/null \
  || fail "Desktop install failed; previous runtime code will be restored"

[[ -d "$desktop_app" ]] || fail "Desktop app missing after install"
/usr/bin/codesign --verify --deep --strict "$desktop_app" \
  || fail "Desktop app signature verification failed"
installed_bundle_id="$(/usr/bin/plutil -extract CFBundleIdentifier raw -o - "$desktop_app/Contents/Info.plist")"
[[ "$installed_bundle_id" == "ru.elena.audiobookstudio" ]] || fail "installed bundle id mismatch"

# Installation succeeded; keep the runtime backup for rollback history but do not
# roll back on normal exit.
runtime_changed=0
trap cleanup EXIT

/usr/bin/open "$desktop_app"
print -- "Audiobook Studio updated and opened: $desktop_app"
print -- "Source: $source_sha"
