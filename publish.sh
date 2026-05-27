#!/bin/bash
# BigCat Learning Hub — shared publish script for all routine repos.
# Auto-derives N, commit message, and URL from filesystem state.
# Usage: ./publish.sh   (no args)
#
# Handles two file-layout modes:
#   - LEGACY embedded: single  *-{day,week,book,issue}{N}.html  per topic
#   - SPLIT bilingual: pair    *-{day,week,...}{N}.html  +  *-{...}{N}.en.html
#
# Guards (filesystem is source of truth, not TOPICS.md):
#   - new content file exists matching the pattern above
#   - each new file is not a tiny error stub (>2KB)
#   - index.html references the new Chinese file (index.en.html refs the .en one if present)
#   - no DUPLICATE N (treats day1 / day01 / day9 / day09 as same N=9)
#   - no hardcoded shared scripts (comments/search/index-button/i18n-tts)
#   - <div> balance + data-zh/data-en attribute integrity
#   - pushes to main via HEAD:main (bypasses claude/* harness branches)
#   - also pushes current branch to origin (keeps claude/* harness branches in sync with stop-hook)
#   - retries push up to 3 times on transient failures

set -e

# Collect all new (untracked + modified) HTML files matching the topic pattern.
# Excludes index.html — that's expected to be modified, not "the new content".
NEW_FILES=$(git status --porcelain | grep -oE '\S+-(day|week|book|issue)[0-9]+(\.en)?\.html$' | sort -u)
[ -z "$NEW_FILES" ] && { echo "ERROR: no new *-{day,week,book,issue}{N}[.en].html in working tree"; exit 1; }

# Primary (Chinese) file = the non-.en one if any, else the .en one
PRIMARY=$(echo "$NEW_FILES" | grep -v '\.en\.html$' | head -1)
[ -z "$PRIMARY" ] && PRIMARY=$(echo "$NEW_FILES" | head -1)

PADDED_N=$(echo "$PRIMARY" | grep -oE '[0-9]+' | tail -1)
N=$((10#$PADDED_N))
KIND=$(echo "$PRIMARY" | grep -oE '(day|week|book|issue)')

TITLE=$(grep -oE '<title>[^<]+' "$PRIMARY" | head -1 | sed 's|<title>||')
[ -z "$TITLE" ] && TITLE="$PRIMARY"
MSG="${MSG:-Add #$N: $TITLE}"

# ---------- Per-file validations ----------
for F in $NEW_FILES; do
  [ ! -f "$F" ] && continue

  # Size guard
  [ $(wc -c < "$F") -lt 2000 ] && { echo "ERROR: $F only $(wc -c < $F) bytes, likely incomplete"; exit 1; }

  # Reference check: Chinese file must be in index.html, .en file in index.en.html (if exists)
  if echo "$F" | grep -q '\.en\.html$'; then
    if [ -f index.en.html ]; then
      grep -q "$F" index.en.html || { echo "ERROR: index.en.html does not reference $F"; exit 1; }
    fi
  else
    grep -q "$F" index.html || { echo "ERROR: index.html does not reference $F"; exit 1; }
  fi

  # Forbidden hardcoded scripts (auto-injected by GitHub Action)
  for s in comments.js search.js index-button.js i18n-tts.js; do
    grep -q "$s" "$F" && { echo "ERROR: $F hardcodes $s (auto-injected, will duplicate)"; exit 1; }
  done
  grep -q "← Hub" "$F" && echo "WARN: $F hardcodes ← Hub button (will be deduped, consider removing)"

  # <div> balance
  OPENS=$(grep -oE '<div[ >]' "$F" | wc -l | tr -d ' ')
  CLOSES=$(grep -oE '</div>' "$F" | wc -l | tr -d ' ')
  if [ "$OPENS" != "$CLOSES" ]; then
    echo "ERROR: $F has unbalanced <div>: $OPENS opens vs $CLOSES closes (diff $((OPENS-CLOSES)))"
    exit 1
  fi

  # data-zh/data-en attribute integrity (catch ASCII " inside attribute value)
  BAD_ATTR=$(grep -cE 'data-(zh|en)="[^"]*"[^ />]' "$F" || true)
  if [ "$BAD_ATTR" -gt 0 ]; then
    echo "ERROR: $F has $BAD_ATTR data-zh/data-en attribute(s) with unescaped ASCII \" inside value."
    echo "       Use 「」 / 『』 or HTML entity &quot;"
    exit 1
  fi
done

# ---------- Duplicate N check (across same KIND, both lang variants) ----------
DUP=""
for existing in *-${KIND}*.html; do
  [ ! -f "$existing" ] && continue
  # Skip if this file is itself one of the new files
  echo "$NEW_FILES" | grep -q "^${existing}$" && continue
  EXISTING_PADDED=$(echo "$existing" | grep -oE '[0-9]+' | tail -1)
  EXISTING_N=$((10#$EXISTING_PADDED))
  # Only compare same lang variant: split-mode produces both x.html and x.en.html
  IS_EN_EXISTING=$(echo "$existing" | grep -c '\.en\.html$' || true)
  IS_EN_PRIMARY=$(echo "$PRIMARY" | grep -c '\.en\.html$' || true)
  if [ "$EXISTING_N" = "$N" ] && [ "$IS_EN_EXISTING" = "$IS_EN_PRIMARY" ]; then
    DUP="$DUP $existing"
  fi
done
if [ -n "$DUP" ]; then
  echo "ERROR: ${KIND} #$N already exists:$DUP"
  echo "       Check filesystem before regenerating."
  exit 1
fi

# ---------- Commit + push ----------
git config user.email "chengchen0802@gmail.com"
git config user.name "BigCat"
git add -A
git diff --cached --quiet && { echo "Nothing to commit."; exit 0; }
git commit -m "$MSG"

for i in 1 2 3; do
  if git push origin HEAD:main 2>/dev/null; then
    echo "✓ Pushed: $MSG"
    REPO=$(basename "$(pwd)")
    echo "→ https://cissy0802.github.io/$REPO/$PRIMARY"
    EN_FILE=$(echo "$NEW_FILES" | grep '\.en\.html$' | head -1)
    [ -n "$EN_FILE" ] && echo "→ https://cissy0802.github.io/$REPO/$EN_FILE"
    # Also push current branch (keeps claude/* harness branches in sync with stop-hook).
    CURBRANCH=$(git rev-parse --abbrev-ref HEAD)
    if [ "$CURBRANCH" != "main" ] && [ "$CURBRANCH" != "HEAD" ]; then
      git push -u origin HEAD >/dev/null 2>&1 && echo "✓ Also synced branch: $CURBRANCH"
    fi
    exit 0
  fi
  echo "Push attempt $i failed, fetching and rebasing..."
  git fetch origin main
  git rebase origin/main || { git rebase --abort; echo "Rebase failed"; }
  [ $i -lt 3 ] && sleep 2
done
echo "ERROR: push failed after 3 attempts"
exit 1
