# retros/

The stored record of each closed round, one directory per étude:

```
retros/<cid>/
├── retro.md          # the round's write-up: attempts index, steal list, recurring traps,
│                     # wildcard review, taxonomy proposals, open questions, decisions
├── stats.txt         # the move, glyph and motif distributions and the phase timelines
└── gallery.html      # the collected layouts, one section per instance, cards side by side
```

`retros/c001/` is the retro of étude no. 1. No round has closed yet, so there is nothing here
besides this file and `.gitkeep`; nothing is written here while a round is open.

## How it gets here

A maintainer closes a round on a `retro/<cid>` branch off `main` and runs
`make retro CHALLENGE=<cid>` (`scripts/retro.py`). That one command collects the attempt branches
into `results/` (`scripts/collect_results.py`; `--skip-collect` reuses the tree as it stands),
captures `scripts/stats.py`'s output as `stats.txt`, renders `gallery.html` with the challenge's own
`tools/gallery.py` when it has one, and writes `retro.md` from
[templates/retro.md](../templates/retro.md) with the machine-derived parts filled in: the round
facts, the attempts index, the brilliancies-and-blunders reel and the wildcard table. Each of those
sits between `<!-- generated:start <id> -->` and `<!-- generated:end <id> -->` markers, and
re-running the script refreshes only what is between them — everything a human wrote survives,
including the date the round closed. The reel also goes to stdout, ready to paste into the round's
discussion thread. A missing piece is a notice on stderr, not a failure: without collected attempts
`retro.md` is still written, with empty tables.

The maintainer then writes the prose sections and opens a pull request from `retro/<cid>` to `main`.
**That is the one pull request of a round that gets merged** — attempt pull requests never are —
and it carries the new `results/<cid>/…` directories with it, so it is also the last review of
everything collected. The step by step is scenario C in [CONTRIBUTING.md](../CONTRIBUTING.md); the
checklist is in [.github/PULL_REQUEST_TEMPLATE.md](../.github/PULL_REQUEST_TEMPLATE.md).

## What this directory is for

A retro records what the round taught and what changes because of it. The attempts index is
alphabetical by participant and descriptive; the reel and the wildcard table are quotes and counts,
never an ordering by quality. Taxonomy changes a retro argues for are not made here: each becomes
its own pull request labelled `taxonomy-change` ([TAXONOMY.md](../TAXONOMY.md) section 7). The
conversation about the round lives in a GitHub Discussion, opened by hand.
