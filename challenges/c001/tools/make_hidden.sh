#!/usr/bin/env bash
#
# make_hidden.sh -- build the hidden instance set for etude no. 1 (c001).
#
# The hidden seeds are secret until the round closes, so this script refuses to
# read a seeds file that git can see: the file must be untracked, unstaged and
# matched by .gitignore.  Everything else it does is a thin loop around
# tools/generate.py, so any participant can reproduce the exact same instances
# from the published seeds after the round.
#
# Written for bash 3.2 (the /bin/bash that ships with macOS): no associative
# arrays, no mapfile, no ${var^^}.
#
set -euo pipefail

CHALLENGE_ID="c001"
SCRIPT_NAME="$(basename "$0")"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CHALLENGE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DEFAULT_SEEDS_FILE="$CHALLENGE_DIR/hidden-seeds.txt"
DEFAULT_OUT_DIR="$CHALLENGE_DIR/instances/hidden"

# Exit codes: 0 ok | 1 generator failed | 2 usage or malformed seeds | 3 the
# seeds file is not safe (tracked, staged, or not ignored).
EX_GENERATOR=1
EX_USAGE=2
EX_UNSAFE=3

usage() {
    cat <<USAGE
Usage: ${SCRIPT_NAME} [--seeds-file FILE] [--out DIR]
       ${SCRIPT_NAME} --help

Generate the hidden instances of challenge ${CHALLENGE_ID} from secret seeds.

Options:
  --seeds-file FILE  read seeds from FILE
                     (default: ${DEFAULT_SEEDS_FILE})
  --out DIR          write the instances into DIR
                     (default: ${DEFAULT_OUT_DIR})
  -h, --help         print this text and exit

Seed sources (first one that applies wins):
  1. --seeds-file FILE
  2. \$HIDDEN_SEEDS, formatted "tier:seed,tier:seed,..."
     e.g. HIDDEN_SEEDS="1:1731,1:9042,2:5510,3:8123"
  3. the default seeds file, if it exists

Seeds file format: one "tier seed" per line (a colon works too), blank lines
and lines starting with # ignored.  Example:

    # etude no. 1, hidden set
    1 1731
    2 5510
    3 8123

Instances are named ${CHALLENGE_ID}-t<TIER>-hidden-<NN>.json, with NN counting
from 01 within each tier, in the order the seeds are listed.

Safety rules (why this script may refuse with exit ${EX_UNSAFE}):
  * the seeds file must NOT be tracked by git,
  * it must NOT be staged in the index,
  * it MUST be matched by .gitignore (the repo ignores *hidden-seeds*).
A seed that leaks before the round closes hands out the hidden instances early,
which is exactly what the dev/hidden split exists to prevent.

Environment:
  HIDDEN_SEEDS   inline seeds, see above
  PYTHON         python command used to run the generator (default: python;
                 inside this repo use PYTHON="uv run python")
  GENERATE_CMD   full generator command, overriding "\$PYTHON tools/generate.py"
                 (used by the tests; the words are split on whitespace)

Post-round protocol
-------------------
1. ORGANIZER, before the round: pick the seeds, keep them in an ignored
   hidden-seeds.txt, and tell nobody.  Do not run this script into a tracked
   directory yet.
2. PARTICIPANTS, during the round: work on dev instances only.  There is
   nothing to solve in instances/hidden/ yet -- it is empty on purpose.
3. ORGANIZER, when the round closes: open one PR that (a) commits the seed list
   as challenges/${CHALLENGE_ID}/published-seeds.txt -- a fresh name on purpose,
   .gitignore matches *hidden-seeds*, so hidden-seeds.txt itself stays untracked
   and 'git add' would silently skip it, (b) commits the generated instances
   under
   challenges/${CHALLENGE_ID}/instances/hidden/, and (c) flips
   challenges/${CHALLENGE_ID}/challenge.yaml to status: closed.  CI needs the
   committed instances to validate anybody's hidden solutions.
4. EVERY PARTICIPANT, after that PR lands: reproduce the instances locally with
   this script (or with tools/generate.py directly) and check that the files
   are byte-identical to the committed ones -- the generator is deterministic,
   so they will be.  Then run your own solver, unchanged, on each hidden
   instance, honoring the 60 s budget.
5. EVERY PARTICIPANT: commit the results as solutions/hidden/<instance_id>.json
   on your attempt branch and push.  The retro reads those files.

The hidden set is about contamination control, not about comparing people:
tiers are personal rungs and the gallery groups layouts by instance.
USAGE
}

die_usage() {
    printf '%s: %s\n\n' "$SCRIPT_NAME" "$1" >&2
    usage >&2
    exit "$EX_USAGE"
}

die() {
    printf '%s: %s\n' "$SCRIPT_NAME" "$2" >&2
    exit "$1"
}

# Absolute path of an existing file, without relying on realpath(1).
abspath_file() {
    local dir base
    dir="$(cd "$(dirname "$1")" && pwd)"
    base="$(basename "$1")"
    printf '%s/%s\n' "$dir" "$base"
}

# Refuse unless the seeds file is invisible to git: untracked, unstaged, and
# matched by an ignore rule.
assert_seeds_file_is_secret() {
    local file="$1"
    local dir root rel staged

    dir="$(dirname "$file")"
    if ! root="$(git -C "$dir" rev-parse --show-toplevel 2>/dev/null)"; then
        die "$EX_UNSAFE" "$file is not inside a git repository, so this script cannot check that it is untracked and ignored. Move the seeds file into the repository (where .gitignore covers *hidden-seeds*) and try again."
    fi

    rel="$file"
    case "$file" in
        "$root"/*) rel="${file#"$root"/}" ;;
    esac

    if git -C "$root" ls-files --error-unmatch -- "$rel" >/dev/null 2>&1; then
        die "$EX_UNSAFE" "refusing to use $rel: it is tracked by git. Hidden seeds must never be committed before the round closes. Run: git rm --cached -- '$rel' && echo '$rel' >> .gitignore"
    fi

    staged="$(git -C "$root" diff --cached --name-only 2>/dev/null || true)"
    if printf '%s\n' "$staged" | grep -Fxq -- "$rel"; then
        die "$EX_UNSAFE" "refusing to use $rel: it is staged in the git index and would become tracked at the next commit. Run: git restore --staged -- '$rel'"
    fi

    if ! git -C "$root" check-ignore -q -- "$rel"; then
        die "$EX_UNSAFE" "refusing to use $rel: no .gitignore rule matches it, so it is one 'git add .' away from being tracked. Add a rule (the repo ships '*hidden-seeds*') and try again."
    fi
}

seeds_file=""
out_dir=""

while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help)
            usage
            exit 0
            ;;
        --seeds-file)
            [ $# -ge 2 ] || die_usage "--seeds-file needs a FILE argument"
            seeds_file="$2"
            shift 2
            ;;
        --seeds-file=*)
            seeds_file="${1#*=}"
            shift
            ;;
        --out)
            [ $# -ge 2 ] || die_usage "--out needs a DIR argument"
            out_dir="$2"
            shift 2
            ;;
        --out=*)
            out_dir="${1#*=}"
            shift
            ;;
        --)
            shift
            break
            ;;
        -*)
            die_usage "unknown option: $1"
            ;;
        *)
            die_usage "unexpected argument: $1"
            ;;
    esac
done
[ $# -eq 0 ] || die_usage "unexpected argument: $1"

# ---------------------------------------------------------------------------
# Where do the seeds come from?
# ---------------------------------------------------------------------------
raw_seeds=""
source_label=""

if [ -n "$seeds_file" ]; then
    [ -f "$seeds_file" ] || die_usage "seeds file not found: $seeds_file"
    seeds_file="$(abspath_file "$seeds_file")"
    assert_seeds_file_is_secret "$seeds_file"
    raw_seeds="$(cat "$seeds_file")"
    source_label="$seeds_file"
elif [ -n "${HIDDEN_SEEDS:-}" ]; then
    raw_seeds="$HIDDEN_SEEDS"
    source_label="\$HIDDEN_SEEDS"
elif [ -f "$DEFAULT_SEEDS_FILE" ]; then
    seeds_file="$(abspath_file "$DEFAULT_SEEDS_FILE")"
    assert_seeds_file_is_secret "$seeds_file"
    raw_seeds="$(cat "$seeds_file")"
    source_label="$seeds_file"
else
    die_usage "no seeds given: set \$HIDDEN_SEEDS, pass --seeds-file FILE, or create $DEFAULT_SEEDS_FILE"
fi

# Strip comments first (a comma inside a comment must not become a separator),
# then treat "," as a line break and ":" as a field separator.
normalized="$(printf '%s\n' "$raw_seeds" | sed 's/#.*//' | tr ',:' '\n ')"

if [ -z "$out_dir" ]; then
    out_dir="$DEFAULT_OUT_DIR"
fi
mkdir -p "$out_dir"
out_dir="$(cd "$out_dir" && pwd)"

if [ -n "${GENERATE_CMD:-}" ]; then
    generator="$GENERATE_CMD"
else
    generator="${PYTHON:-python} tools/generate.py"
fi

cd "$CHALLENGE_DIR"

n1=0
n2=0
n3=0
made=0
seen=""

while read -r tier seed extra; do
    [ -n "${tier:-}" ] || continue
    if [ -n "${extra:-}" ]; then
        die "$EX_USAGE" "malformed seed entry in $source_label: expected \"tier seed\", got \"$tier ${seed:-} $extra\""
    fi
    if [ -z "${seed:-}" ]; then
        die "$EX_USAGE" "malformed seed entry in $source_label: \"$tier\" has no seed (expected \"tier seed\" or \"tier:seed\")"
    fi
    case "$tier" in
        1|2|3) ;;
        *) die "$EX_USAGE" "bad tier \"$tier\" in $source_label: tier must be 1, 2 or 3" ;;
    esac
    if ! [[ $seed =~ ^-?[0-9]+$ ]]; then
        die "$EX_USAGE" "bad seed \"$seed\" in $source_label: a seed must be a whole number"
    fi
    case " $seen " in
        *" $tier:$seed "*)
            die "$EX_USAGE" "duplicate seed $tier:$seed in $source_label: it would produce two identical hidden instances"
            ;;
    esac
    seen="$seen $tier:$seed"

    case "$tier" in
        1) n1=$((n1 + 1)); n=$n1 ;;
        2) n2=$((n2 + 1)); n=$n2 ;;
        3) n3=$((n3 + 1)); n=$n3 ;;
    esac

    instance_id="$(printf '%s-t%s-hidden-%02d' "$CHALLENGE_ID" "$tier" "$n")"
    out_file="$out_dir/$instance_id.json"

    # Deliberate word splitting: $generator carries a whole command line.
    # shellcheck disable=SC2086
    if ! $generator --tier "$tier" --seed "$seed" --id "$instance_id" --out "$out_file"; then
        die "$EX_GENERATOR" "generator failed for $instance_id (tier $tier, seed $seed)"
    fi
    printf '%s\n' "$out_file"
    made=$((made + 1))
done <<< "$normalized"

if [ "$made" -eq 0 ]; then
    die_usage "no seed entries found in $source_label"
fi

printf '%s: wrote %d hidden instance(s) into %s\n' "$SCRIPT_NAME" "$made" "$out_dir" >&2
printf '%s: keep these files (and the seeds) out of git until the round closes; see --help for the post-round protocol.\n' "$SCRIPT_NAME" >&2
