#!/usr/bin/env bash
set -euo pipefail
checkpoint="$RUNNER_TEMP/growth-checkpoint"
test -s "$checkpoint/state.sqlite3"
destination="$RUNNER_TEMP/growth-data"
result=0
git ls-remote --exit-code --heads origin growth-data > "$RUNNER_TEMP/growth-remote" || result=$?
if [ "$result" -eq 0 ]; then
  git fetch --depth=1 origin refs/heads/growth-data
  git worktree add --detach "$destination" FETCH_HEAD
elif [ "$result" -eq 2 ]; then
  git worktree add --detach "$destination" HEAD
  git -C "$destination" checkout --orphan growth-data
  git -C "$destination" rm -rf --ignore-unmatch .
else
  exit "$result"
fi
mkdir -p "$destination/reports"
cp "$checkpoint/state.sqlite3" "$destination/state.sqlite3"
if [ -f "$checkpoint/reports/report.json" ]; then
  cp "$checkpoint/reports/report.json" "$destination/reports/"
fi
if [ -f "$checkpoint/reports/brief.md" ]; then
  cp "$checkpoint/reports/brief.md" "$destination/reports/"
fi
git -C "$destination" config user.name 'github-actions[bot]'
git -C "$destination" config user.email '41898282+github-actions[bot]@users.noreply.github.com'
git -C "$destination" add state.sqlite3 reports
if git -C "$destination" diff --cached --quiet; then
  echo 'No checkpoint changes.'
  exit 0
fi
git -C "$destination" commit -m 'chore(growth): preserve observed metrics and execution checkpoint'
# Fast-forward only. Conflicts fail, retain the run artifact and never overwrite state.
git -C "$destination" push origin HEAD:refs/heads/growth-data
