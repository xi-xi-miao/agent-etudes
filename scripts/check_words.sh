#!/usr/bin/env bash
#
# check_words.sh -- this repository reports utilizations, distributions and
# timelines; it never reports standings. This check greps the whole tree for
# the competitive vocabulary we have agreed not to use.
#
# Usage:  bash scripts/check_words.sh [ROOT]
#         (ROOT defaults to the repository the script lives in)
#
# Allowed: the "what this is not" sentence in the top-level README.md. Every
# other hit fails the check.
#
# Excluded from the search: .git/, .venv/, __pycache__/, .pytest_cache/,
# node_modules/, .claude/ (agent scratch: local settings and worktrees) and
# uv.lock. Binary files are skipped with grep -I. Nothing under docs/ is
# exempt: every document in the tree is held to the vocabulary rule.
#
# Also excluded: anything under a nested checkout -- a second clone or a git
# worktree living inside ROOT, recognised by its own .git entry (a directory
# for a clone, a file for a worktree). Those files belong to another checkout,
# and without this a copy of the allowed README.md sentence would be reported
# as a violation of the very rule that allows it.
#
# Portability: POSIX-ish shell, works with macOS bash 3.2 + BSD grep as well as
# bash 5 + GNU grep.
#
# The search words are assembled from fragments below so that this script does
# not match itself.

set -u

case "${1:-}" in
  -h|--help)
    echo "usage: bash scripts/check_words.sh [ROOT]"
    exit 0
    ;;
esac

if [ "$#" -ge 1 ] && [ -n "$1" ]; then
  root="$1"
else
  script_dir="$(cd "$(dirname "$0")" && pwd)"
  root="$(cd "$script_dir/.." && pwd)"
fi

if [ ! -d "$root" ]; then
  echo "check_words.sh: no such directory: $root" >&2
  exit 2
fi

w1='leader''board'
w2='sco''re'
w3='ra''nk'
w4='win''ner'
pattern="${w1}|${w2}|${w2}s|${w3}|${w3}s|${w3}ing|${w3}ings|${w4}"

cd "$root" || exit 2

hits="$(grep -rniwE "$pattern" . -I \
  --exclude-dir=.git \
  --exclude-dir=.venv \
  --exclude-dir=venv \
  --exclude-dir=__pycache__ \
  --exclude-dir=.pytest_cache \
  --exclude-dir=node_modules \
  --exclude-dir=.claude \
  --exclude=uv.lock 2>/dev/null || true)"

# Drop the empty line that quoting an empty result would otherwise produce
# (printf '%s\n' "" emits one), so a clean tree stays detectably clean.
hits="$(printf '%s\n' "$hits" | grep -v '^[[:space:]]*$' || true)"

# Nested checkouts: every directory below ROOT that carries its own .git entry.
# ROOT's own .git is at depth 1 and is left alone. The prune list is applied to
# the hits (grep -r has no path-aware exclusion that both GNU and BSD grep
# accept) BEFORE the README.md allowlist is worked out, so a nested copy of the
# allowed sentence is neither an extra allowed hit nor an offending one.
nested="$(find . -mindepth 2 \
  \( -path './.git/*' -o -name .venv -o -name node_modules -o -name .claude \) \
  -prune -o -name .git -print -prune 2>/dev/null \
  | sed -e 's|/\.git$||' -e 's|^\./||' | sort)"

if [ -n "$nested" ] && [ -n "$hits" ]; then
  hits="$(printf '%s\n' "$hits" | awk -v dirs="$nested" '
    BEGIN { n = split(dirs, prefix, "\n") }
    {
      for (i = 1; i <= n; i++)
        if (prefix[i] != "" && index($0, "./" prefix[i] "/") == 1) next
      print
    }')"
fi

if [ -z "$hits" ]; then
  echo "check-words: clean (no hits at all)"
  exit 0
fi

allowed="$(printf '%s\n' "$hits" | grep '^\./README\.md:' || true)"
offending="$(printf '%s\n' "$hits" | grep -v '^\./README\.md:' | grep -v '^[[:space:]]*$' || true)"

if [ -n "$allowed" ]; then
  echo "check-words: allowed hits in the top-level README.md:"
  printf '%s\n' "$allowed" | sed 's/^/    /'
fi

allowed_count="$(printf '%s\n' "$allowed" | grep -c . || true)"
if [ "$allowed_count" -gt 1 ]; then
  echo "check-words: README.md may carry the vocabulary in exactly ONE sentence (the 'what this is not' line); found $allowed_count lines" >&2
  exit 1
fi

if [ -z "$offending" ]; then
  echo "check-words: clean (only the README.md sentence)"
  exit 0
fi

echo "check-words: forbidden vocabulary outside README.md:" >&2
printf '%s\n' "$offending" | sed 's/^/    /' >&2
echo "" >&2
echo "Use utilization / measure / distribution / count instead." >&2
exit 1
