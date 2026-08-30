#!/usr/bin/env python3
"""Build a self-contained HTML gallery of c001 solution layouts.

Usage::

    gallery.py <paths...> --out gallery.html [--instances-dir DIR]

Each positional path is a solution JSON file, a directory (every ``*.json``
directly inside it, non-recursive), or a glob such as
``"results/c001/*/*/solutions/*.json"``.  Quote the glob so the shell hands it
over untouched; already-expanded shell globs work too.

The instance behind each solution is located by its ``instance_id``: first under
``--instances-dir`` when given, then ``instances/dev``, then
``instances/hidden`` next to this script.  A solution whose instance cannot be
found is skipped with a warning on stderr.

Layout of the page: one section per instance id (sections in sorted id order),
and inside a section one card per solution.  Cards are ordered alphabetically by
their label -- participant/attempt when the path looks like
``.../results/<cid>/<participant>/<n>/...``, otherwise the file stem.  The label
is the sort key on its own, so card order never depends on utilization.  Every
utilization shown is recomputed here with :mod:`geom` from the instance and the
solution; none is read out of a file.  The page has no aggregate table and no
medals: it exists so two attempts at the same instance sit side by side.
Every card has the same width and ``render.py`` draws every layout of one
instance at the same scale, so side by side the pictures compare by height
alone; the cards are bottom-aligned so the strips stand on one common floor.

The provenance line under a card is written relative to the working directory
(see :func:`display_path`).  A gallery gets committed under ``retros/<cid>/``,
so an absolute path would bake one machine's home directory into a shared file
and make the same tree produce a different page on every laptop.
"""

from __future__ import annotations

import argparse
import glob as globmod
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parent))

import geom  # noqa: E402  (path shim above must run first)
import render  # noqa: E402

__all__ = [
    "expand_paths",
    "find_instance",
    "label_for",
    "display_path",
    "build_gallery",
    "write_gallery",
    "main",
]

TOOLS_DIR = Path(__file__).resolve().parent
C001_DIR = TOOLS_DIR.parent
DEFAULT_INSTANCE_DIRS = [C001_DIR / "instances" / "dev", C001_DIR / "instances" / "hidden"]

_RESULTS_RE = re.compile(r"^c[0-9]{3}$")

CSS = """
:root { color-scheme: light; }
body { margin: 0; padding: 24px; background: #f6f6f4; color: #1a1a1a;
       font-family: ui-sans-serif, -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; }
h1 { font-size: 20px; margin: 0 0 4px; }
p.sub { margin: 0 0 24px; color: #666; font-size: 13px; }
h2 { font-size: 15px; margin: 28px 0 10px; padding-bottom: 6px;
     border-bottom: 1px solid #ddd; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.cards { display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-end; }
.card { background: #fff; border: 1px solid #e2e2de; border-radius: 6px; padding: 10px;
        flex: 0 1 460px; max-width: 100%; box-sizing: border-box; }
.card .caption { font-size: 13px; margin-bottom: 8px; }
.card .caption .who { font-weight: 600; }
.card .caption .measure { color: #555; }
.card .path { font-size: 11px; color: #999; margin-top: 6px; word-break: break-all;
              font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.card svg { width: 100%; height: auto; display: block; }
""".strip()


# ---------------------------------------------------------------------------
# Input expansion and instance lookup
# ---------------------------------------------------------------------------


def expand_paths(paths):
    """Expand files, directories and globs into a de-duplicated list of files."""
    out = []
    seen = set()

    def add(path):
        resolved = Path(path).resolve()
        if resolved not in seen and resolved.is_file():
            seen.add(resolved)
            out.append(resolved)

    for raw in paths:
        candidate = Path(raw)
        if candidate.is_dir():
            for found in sorted(candidate.glob("*.json")):
                add(found)
        elif candidate.is_file():
            add(candidate)
        else:
            matches = sorted(globmod.glob(str(raw), recursive=True))
            if not matches:
                print("warning: no match for {}".format(raw), file=sys.stderr)
            for match in matches:
                found = Path(match)
                if found.is_dir():
                    for inner in sorted(found.glob("*.json")):
                        add(inner)
                else:
                    add(found)
    return out


def find_instance(instance_id, instances_dir=None):
    """Locate the instance file for ``instance_id``, or return ``None``."""
    candidates = []
    if instances_dir is not None:
        candidates.append(Path(instances_dir))
    candidates.extend(DEFAULT_INSTANCE_DIRS)
    for directory in candidates:
        if not directory.is_dir():
            continue
        direct = directory / "{}.json".format(instance_id)
        if direct.is_file():
            return direct
        nested = sorted(directory.rglob("{}.json".format(instance_id)))
        if nested:
            return nested[0]
    return None


def label_for(path):
    """Card label: ``<participant> / attempt <n>`` under results/, else the file stem."""
    parts = list(Path(path).resolve().parts)
    for i in range(len(parts) - 4, -1, -1):
        if parts[i] != "results":
            continue
        cid, participant, attempt = parts[i + 1], parts[i + 2], parts[i + 3]
        if _RESULTS_RE.match(cid) and attempt.isdigit():
            return "{} / attempt {}".format(participant, attempt)
    return Path(path).stem


def display_path(path):
    """The provenance string shown under a card.

    Relative to the working directory when the file lives under it, otherwise
    just the file name.  Never an absolute path: the gallery is a committed
    artefact (``retros/<cid>/gallery.html``), and an absolute path would put the
    builder's home directory into it and make the page differ from machine to
    machine for one and the same tree.
    """
    try:
        return str(Path(path).resolve().relative_to(Path.cwd()))
    except (ValueError, OSError):
        return Path(path).name


# ---------------------------------------------------------------------------
# Page building
# ---------------------------------------------------------------------------


def _collect(solution_paths, instances_dir=None):
    """Read every solution, pairing it with its instance.  Returns cards + the cid."""
    instances = {}
    cards = []
    challenge_id = None

    for path in solution_paths:
        try:
            solution = geom.load_solution(path)
        except geom.SolutionError as err:
            print("warning: skipping {}: {}".format(path, err), file=sys.stderr)
            continue
        instance_id = solution["instance_id"]
        if instance_id not in instances:
            located = find_instance(instance_id, instances_dir)
            if located is None:
                instances[instance_id] = None
            else:
                try:
                    instances[instance_id] = geom.load_instance(located)
                except geom.InstanceError as err:
                    print("warning: {}: {}".format(located, err), file=sys.stderr)
                    instances[instance_id] = None
        instance = instances[instance_id]
        if instance is None:
            print(
                "warning: skipping {}: no instance file for {!r}".format(path, instance_id),
                file=sys.stderr,
            )
            continue
        if challenge_id is None:
            challenge_id = instance.get("challenge") or geom.CHALLENGE_ID

        svg = render.svg_string(instance, solution)
        _, util, _ = render.layout_measures(instance, solution)
        cards.append(
            {
                "instance_id": instance_id,
                "label": label_for(path),
                "path": display_path(path),
                # Absolute, so that two cards with the same label and the same
                # displayed name still sort in a stable order within one run.
                "sort_path": str(path),
                "utilization": util,
                "svg": svg,
            }
        )

    return cards, (challenge_id or geom.CHALLENGE_ID)


def build_gallery(solution_paths, instances_dir=None):
    """Build the complete HTML document for the given solution files."""
    cards, challenge_id = _collect(list(solution_paths), instances_dir)

    groups = {}
    for card in cards:
        groups.setdefault(card["instance_id"], []).append(card)

    html = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8" />',
        '<meta name="viewport" content="width=device-width, initial-scale=1" />',
        "<title>Gallery — {}</title>".format(escape(challenge_id)),
        "<style>",
        CSS,
        "</style>",
        "</head>",
        "<body>",
        "<h1>Gallery — {}</h1>".format(escape(challenge_id)),
        '<p class="sub">Grouped by instance; within an instance, cards are alphabetical by label.</p>',
    ]

    if not groups:
        html.append('<p class="sub">No layouts to show.</p>')

    for instance_id in sorted(groups):
        html.append("<h2>{}</h2>".format(escape(instance_id)))
        html.append('<div class="cards">')
        for card in sorted(
            groups[instance_id], key=lambda c: (c["label"], c["path"], c["sort_path"])
        ):
            html.append('<div class="card">')
            html.append(
                '<div class="caption"><span class="who">{}</span>'
                ' <span class="measure">utilization {}%</span></div>'.format(
                    escape(card["label"]), escape(geom.format_pct(card["utilization"]))
                )
            )
            html.append(card["svg"].strip())
            html.append('<div class="path">{}</div>'.format(escape(card["path"])))
            html.append("</div>")
        html.append("</div>")

    html.extend(["</body>", "</html>", ""])
    return "\n".join(html)


def write_gallery(solution_paths, out_path, instances_dir=None):
    """Write the gallery HTML to ``out_path``.  Returns the path."""
    out_path = Path(out_path)
    if str(out_path.parent) not in ("", "."):
        out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(build_gallery(solution_paths, instances_dir), encoding="utf-8")
    return out_path


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="gallery.py",
        description="Build a self-contained HTML gallery of c001 solution layouts.",
    )
    parser.add_argument("paths", nargs="+", help="solution JSON files, directories, or globs")
    parser.add_argument("--out", required=True, help="output HTML file")
    parser.add_argument(
        "--instances-dir",
        default=None,
        help="extra directory searched first when locating instance files",
    )
    args = parser.parse_args(argv)

    solutions = expand_paths(args.paths)
    if not solutions:
        print("warning: no solution files found", file=sys.stderr)
    try:
        out = write_gallery(solutions, args.out, args.instances_dir)
    except OSError as err:
        print("ERROR cannot write {}: {}".format(args.out, err), file=sys.stderr)
        return 2
    print("wrote {}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
