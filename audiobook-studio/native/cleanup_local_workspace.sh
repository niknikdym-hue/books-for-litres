#!/bin/zsh
set -euo pipefail

workspace_root="${AUDIOBOOK_STUDIO_HOME:-$HOME/Documents/New project/Audiobook-Studio}"
builds_root="$workspace_root/builds"
staging_root="$builds_root/native-staging"
canonical_app="$staging_root/Audiobook Studio.app"
archive_root="$HOME/Library/Application Support/Audiobook Studio/Archives"
timestamp="$(date +%Y%m%d-%H%M%S)"
archive_dir="$archive_root/workspace-cleanup/$timestamp"

[[ -d "$workspace_root" ]] || { print -u2 -- "Missing workspace: $workspace_root"; exit 2; }
mkdir -p "$archive_dir"

move_to_archive() {
  local item="$1"
  [[ -e "$item" || -L "$item" ]] || return 0
  local rel="${item#$workspace_root/}"
  local destination="$archive_dir/$rel"
  mkdir -p "${destination:h}"
  mv "$item" "$destination"
}

# 1. The active staging folder is single-artifact. Preserve only the canonical app.
if [[ -d "$staging_root" ]]; then
  local_item=""
  for local_item in "$staging_root"/*(DN); do
    [[ "$local_item" == "$canonical_app" ]] && continue
    move_to_archive "$local_item"
  done
fi

# 2. `builds/` is generated state. Preserve only the active native-staging folder;
# move historical build folders/files out of the user workspace.
if [[ -d "$builds_root" ]]; then
  local_item=""
  for local_item in "$builds_root"/*(DN); do
    [[ "$local_item" == "$staging_root" ]] && continue
    move_to_archive "$local_item"
  done
fi

# 3. Move only known obsolete top-level app/launcher copies. Never touch canonical
# user/data roots such as books, runtime, cache, renders, jobs, chapters, masters,
# exports, casting, settings or engines.
for local_item in \
  "$workspace_root"/Audiobook\ Studio*.app(N) \
  "$workspace_root"/Audiobook\ Studio*STAGING*(N) \
  "$workspace_root"/Audiobook\ Studio*OLD*(N) \
  "$workspace_root"/Audiobook\ Studio*old*(N); do
  move_to_archive "$local_item"
done

# 4. Finder metadata is disposable and should not clutter the workspace.
/usr/bin/find "$workspace_root" -name '.DS_Store' -type f -delete 2>/dev/null || true
/usr/bin/find "$workspace_root" -name '._*' -type f -delete 2>/dev/null || true

# Remove an empty archive directory if nothing actually needed archiving.
if [[ -d "$archive_dir" && -z "$(/bin/ls -A "$archive_dir" 2>/dev/null)" ]]; then
  rmdir "$archive_dir"
fi

print -- "WORKSPACE=$workspace_root"
print -- "CANONICAL_STAGING_APP=$canonical_app"
print -- "ARCHIVE=${archive_dir}"
print -- "PRESERVED_DATA_ROOTS=books,runtime,cache,renders,jobs,chapters,masters,exports,casting,settings,engines"
