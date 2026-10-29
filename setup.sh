#!/bin/bash
# Run once in Terminal:  bash ~/Desktop/bdsa-watch/setup.sh
set -e
cd "$(dirname "$0")"
TOPIC=$(cat .ntfy_topic)

command -v gh >/dev/null || { command -v brew >/dev/null && brew install gh || { echo "Install GitHub CLI from https://cli.github.com then rerun."; exit 1; }; }
gh auth status >/dev/null 2>&1 || gh auth login --web --git-protocol https

echo; echo "ntfy topic: $TOPIC"
echo "On your phone: install ntfy, tap +, subscribe to the topic above (server ntfy.sh)."
read -rp "Press Enter once subscribed... "

echo; echo "== Local check against the live page"
python3 check.py --dry-run

[ -d .git ] || git init -b main -q
git add -A
git -c user.name="$(gh api user -q .login)" -c user.email="$(gh api user -q .id)+$(gh api user -q .login)@users.noreply.github.com" commit -qm "BDSA ticket watcher" || true
if gh repo view bdsa-watch >/dev/null 2>&1; then
  git remote get-url origin >/dev/null 2>&1 || git remote add origin "https://github.com/$(gh api user -q .login)/bdsa-watch.git"
  git push -u origin main
else
  gh repo create bdsa-watch --private --source=. --push
fi
printf '%s' "$TOPIC" | gh secret set NTFY_TOPIC

echo; echo "== Running the workflow once"
for i in 1 2 3 4 5 6; do gh workflow run "BDSA ticket watch" 2>/dev/null && break; sleep 5; done
sleep 8
RUN=$(gh run list --workflow "BDSA ticket watch" --limit 1 --json databaseId -q '.[0].databaseId')
gh run watch "$RUN" --exit-status
gh run view "$RUN" --log | grep -E "previous:|error|ALERT" || true

echo; echo "== Test push to your phone"
NTFY_TOPIC="$TOPIC" python3 check.py --test-alert
echo; echo "Done. Check your phone for 'BDSA watcher test', then tap it: it should open the ticket page."
