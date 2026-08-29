# results/

Collected session artifacts, one directory per attempt:

```
results/<cid>/<participant>/<n>/
├── manifest.yaml        # branch, head_sha, base_sha, start_tag, cid, participant,
│                        # attempt, collected_at, taxonomy_version, copied_paths
├── git-timeline.txt     # every commit of the attempt, elapsed time from the first one
├── session.yaml         # copied from session/ on the attempt branch
├── annotations.md
├── postmortem.md
├── decisions/           # dr-001.md, …
├── harness/             # if the participant committed one
├── transcript/          # if the transcript lives in the repository
├── solutions/           # the solution data (JSON) and rendered SVGs — never solver code
└── reviews/             # optional cross-annotations: <reviewer>.annotations.md
```

`results/c001/alice/2/` is alice's second attempt at étude no. 1. The participant, challenge and
attempt in the path always agree with the fields inside `session.yaml` and `annotations.md` — the
tooling reads the files, not the path.

## How it gets here

A maintainer runs `make collect` (`scripts/collect_results.py`) on a branch off `main`. It walks the
`attempt/<cid>/<participant>/<n>` branches, extracts `session/` and `solutions/` from each ref
without checking it out, writes the manifest and the timeline, and leaves the result in the working
tree. The change lands on `main` through a normal pull request, so every addition to this directory
is reviewable — including one last look for secrets. Re-running the collector rebuilds an attempt
directory from the branch, so it is safe to run again after somebody pushes a fix; the one thing it
carries over is `reviews/`, because cross-annotations are committed here by their reviewer rather
than pushed to somebody else's attempt branch.

Solver code is deliberately **not** copied. It stays on the attempt branch, where it can be read in
its own history; what belongs here is the record of the process plus the data needed to render the
retro gallery.

## What this directory is for

It is a record kept for comparing *process* — how people worked, where they intervened, what they
would do differently — and never standings: nothing here is ordered by quality, and the tooling
groups by challenge, then instance, then participant alphabetically.
