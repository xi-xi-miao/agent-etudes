#!/usr/bin/env python3
"""Assemble the retro package for one étude: ``retros/<cid>/``.

A retro is the stored verdict of a round. This script does the mechanical
part of it so the maintainer only has to write the prose:

1. ``collect_results.py`` copies the attempt branches into ``results/``
   (skip it with ``--skip-collect`` when the tree is already up to date),
2. ``stats.py`` writes the full distributions to ``retros/<cid>/stats.txt``,
3. the challenge's own ``tools/gallery.py`` -- when it has one -- renders
   ``retros/<cid>/gallery.html``,
4. ``retros/<cid>/retro.md`` is created from ``templates/retro.md`` with the
   machine-derived sections filled in, and the reel is printed to stdout so it
   can be pasted straight into the round's discussion thread.

The machine-derived sections live between ``<!-- generated:start <id> -->``
and ``<!-- generated:end <id> -->`` markers. Re-running the script refreshes
only what is between those markers: everything a human wrote in ``retro.md``
survives, which is the whole point of running it more than once.

Judgment call: the reel and the wildcard table are computed from the same
``results/`` tree that ``stats.py`` reads, rather than parsed back out of
``stats.py``'s stdout. ``retro.md`` therefore never depends on another
script's presentation details, and ``stats.txt`` stays the human-readable
companion file it is advertised as.

Dependencies: Python 3.11 standard library + PyYAML (via ``etudes_lib``).
"""

from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import etudes_lib as lib  # noqa: E402  (needs the sys.path line above)

#: Shell template used when the challenge ships a ``tools/gallery.py`` and the
#: caller did not pass ``--gallery-cmd``. ``{python}`` is the interpreter that
#: is running this script; ``{results_glob}`` and ``{out}`` are absolute paths.
DEFAULT_GALLERY_CMD = "{python} tools/gallery.py {results_glob} --out {out}"

#: Fallback skeleton, used only when ``templates/retro.md`` is missing.
FALLBACK_TEMPLATE = """# Retro — étude no. N (`<cid>`)

This document holds no grades and makes no per-person comparison. It records
what the round taught us and what changes because of it.

## 1. Attempts index

## 2. Steal list

## 3. Recurring traps

## 4. Wildcard review

## 5. Taxonomy proposals

## 6. Open questions

## 7. Decisions for next round
"""

TODO_MARKER = "TODO: fill this in during the retro."

_BLOCK_RE = re.compile(
    r"<!--\s*generated:start(?:[ \t]+(?P<id>[a-z0-9-]+))?\s*-->"
    r".*?"
    r"<!--\s*generated:end(?:[ \t]+[a-z0-9-]+)?\s*-->",
    re.DOTALL,
)

_HEADING_RE = re.compile(r"^##[ \t]+(?P<text>.*)$")

UNKNOWN = "(unknown)"


class RetroError(lib.EtudesError):
    """A problem the person running the script has to fix."""


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def _cell(value: object) -> str:
    """Render one markdown table cell: no pipes, no newlines, never empty."""
    text = " ".join(str(value).split()) if value is not None else ""
    text = text.replace("|", r"\|")
    return text or UNKNOWN


def _short_sha(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return UNKNOWN
    sha = value.strip()
    return sha[:7] if re.fullmatch(r"[0-9a-fA-F]{7,40}", sha) else sha


def _read_manifest(session_dir: Path) -> dict:
    """``results/<cid>/<p>/<n>/manifest.yaml`` as a dict; ``{}`` when unusable.

    A missing or broken manifest must never stop a retro: the index row simply
    says ``(unknown)`` for the columns it cannot fill.
    """
    path = session_dir / "manifest.yaml"
    if not path.is_file():
        return {}
    try:
        return lib.load_yaml(path)
    except lib.EtudesError:
        return {}


def _tool_and_model(session: dict) -> str:
    tool = session.get("tool") if isinstance(session.get("tool"), dict) else {}
    model = session.get("model") if isinstance(session.get("model"), dict) else {}
    name = tool.get("name")
    version = tool.get("version")
    model_name = model.get("name")
    left = " ".join(str(p) for p in (name, version) if isinstance(p, str) and p.strip())
    right = model_name if isinstance(model_name, str) and model_name.strip() else ""
    parts = [p for p in (left, right) if p]
    return " / ".join(parts) if parts else UNKNOWN


def _wall_time(session: dict) -> str:
    value = session.get("duration_wall_minutes")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return UNKNOWN
    try:
        return lib.fmt_elapsed(int(round(value)))
    except ValueError:
        return UNKNOWN


# --------------------------------------------------------------------------
# The generated blocks
# --------------------------------------------------------------------------


def build_attempts_table(sessions: list) -> str:
    """Attempts index: one row per collected attempt, alphabetical.

    ``walk_results`` already sorts by ``(cid, participant, attempt)``, so the
    order here is alphabetical by participant and never derived from any
    measure.
    """
    header = (
        "| Participant | Attempt | Branch | Head | Tool / model | Wall time |\n"
        "|---|---|---|---|---|---|"
    )
    if not sessions:
        return header + "\n| _no attempts collected yet_ |  |  |  |  |  |"
    rows = []
    for s in sessions:
        manifest = _read_manifest(s.dir)
        branch = manifest.get("branch")
        if not isinstance(branch, str) or not branch.strip():
            branch = UNKNOWN
        else:
            branch = f"`{branch.strip()}`"
        head = _short_sha(manifest.get("head_sha"))
        if head != UNKNOWN:
            head = f"`{head}`"
        rows.append(
            "| {p} | {a} | {b} | {h} | {tm} | {w} |".format(
                p=_cell(s.participant),
                a=_cell(s.attempt),
                b=_cell(branch),
                h=_cell(head),
                tm=_cell(_tool_and_model(s.session)),
                w=_cell(_wall_time(s.session)),
            )
        )
    return header + "\n" + "\n".join(rows)


def build_reel(sessions: list) -> str:
    """The ``!!`` / ``??`` reel as plain text, ready to paste into a thread.

    Grouped by session in the order ``walk_results`` returns them
    (alphabetical by participant, not ordered by any measure) and by line
    within a session.
    """
    entries = []
    for s in sessions:
        for mv in s.moves:
            if mv.glyph in ("!!", "??"):
                phase = mv.phase + (mv.stance or "")
                entries.append(
                    (
                        s.label,
                        mv.timestamp,
                        phase,
                        mv.move,
                        mv.glyph,
                        mv.comment or "",
                        f"@{mv.anchor}" if mv.anchor else "",
                    )
                )
    if not entries:
        return "(no !! or ?? lines in the collected annotations)"

    widths = [max(len(row[i]) for row in entries) for i in range(5)]
    lines = []
    for label, ts, phase, move, glyph, comment, anchor in entries:
        parts = [
            label.ljust(widths[0]),
            ts.rjust(widths[1]),
            phase.ljust(widths[2]),
            move.ljust(widths[3]),
            glyph.ljust(widths[4]),
        ]
        line = "  ".join(parts)
        if comment:
            line += f'  "{comment}"'
        if anchor:
            line += f"  {anchor}"
        lines.append(line.rstrip())
    return "\n".join(lines)


def build_wildcard_table(sessions: list) -> str:
    """Every ``X-<name>`` seen, with the evidence a promotion decision needs.

    Threshold (TAXONOMY §3.4): used independently by >= 2 participants, or
    >= 3 times by one participant.
    """
    uses: dict[str, int] = {}
    people: dict[str, set] = {}
    per_person: dict[str, dict[str, int]] = {}
    for s in sessions:
        for mv in s.moves:
            if lib.move_family(mv.move) != "Wildcard":
                continue
            uses[mv.move] = uses.get(mv.move, 0) + 1
            people.setdefault(mv.move, set()).add(s.participant)
            counts = per_person.setdefault(mv.move, {})
            counts[s.participant] = counts.get(s.participant, 0) + 1

    header = (
        "| Wildcard | Uses | Distinct participants | Meets threshold |\n"
        "|---|---|---|---|"
    )
    if not uses:
        return header + "\n| _no wildcard moves in the collected annotations_ |  |  |  |"

    rows = []
    for name in sorted(uses):
        who = sorted(p for p in people[name] if p)
        meets = len(who) >= 2 or max(per_person[name].values()) >= 3
        rows.append(
            "| `{n}` | {u} | {d} | {m} |".format(
                n=name,
                u=uses[name],
                d=f"{len(who)} ({', '.join(who)})" if who else "0",
                m="yes" if meets else "no",
            )
        )
    return header + "\n" + "\n".join(rows)


# --------------------------------------------------------------------------
# Document assembly
# --------------------------------------------------------------------------


def render_block(block_id: str, content: str) -> str:
    return (
        f"<!-- generated:start {block_id} -->\n"
        f"{content.rstrip()}\n"
        f"<!-- generated:end {block_id} -->"
    )


def _split_sections(text: str) -> list[tuple[Optional[str], list[str]]]:
    """Split a markdown document into ``(heading_text, lines)`` chunks.

    The first chunk carries ``None`` as its heading: it is everything before
    the first ``##`` heading (title, preamble, metadata list).
    """
    sections: list[tuple[Optional[str], list[str]]] = [(None, [])]
    for line in text.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            sections.append((m.group("text").strip(), [line]))
        else:
            sections[-1][1].append(line)
    return sections


def _strip_table(lines: list[str]) -> list[str]:
    """Drop placeholder markdown table rows from a template section."""
    return [ln for ln in lines if not ln.lstrip().startswith("|")]


def build_document(
    template_text: str,
    blocks: dict[str, str],
    cid: str,
    number: Optional[int] = None,
) -> str:
    """Create a fresh ``retro.md`` from the template plus the generated blocks.

    Sections are matched by heading text so the template can be re-worded or
    re-numbered without breaking this script. Narrative sections keep their
    template content and gain a TODO marker.
    """
    sections = _split_sections(template_text)
    out: list[str] = []
    used: set[str] = set()

    for heading, lines in sections:
        if heading is None:
            head = "\n".join(lines)
            head = head.replace("<cid>", cid)
            if number is not None:
                head = re.sub(r"(étude no\.)\s*N\b", rf"\1 {number}", head)
            out.append(head)
            continue

        lower = heading.lower()
        body = list(lines)
        if "attempts index" in lower and "attempts" in blocks:
            body = _strip_table(body) + ["", render_block("attempts", blocks["attempts"])]
            used.add("attempts")
        elif "wildcard" in lower and "wildcards" in blocks:
            body = _strip_table(body) + [
                "",
                render_block("wildcards", blocks["wildcards"]),
                "",
                TODO_MARKER,
            ]
            used.add("wildcards")
        elif "steal" in lower and "reel" in blocks:
            body = body + ["", render_block("reel", blocks["reel"]), "", TODO_MARKER]
            used.add("reel")
        else:
            body = body + ["", TODO_MARKER]
        out.append("\n".join(body))

    leftovers = [bid for bid in blocks if bid not in used]
    if leftovers:
        titles = {
            "attempts": "Attempts index",
            "reel": "Brilliancies and blunders reel",
            "wildcards": "Wildcard review",
        }
        for bid in leftovers:
            out.append(
                "## "
                + titles.get(bid, bid)
                + "\n\n"
                + render_block(bid, blocks[bid])
            )

    text = "\n\n".join(part.strip("\n") for part in out if part.strip())
    return re.sub(r"\n{3,}", "\n\n", text).rstrip() + "\n"


def refresh_document(existing: str, blocks: dict[str, str]) -> tuple[str, list[str]]:
    """Replace the content of every generated block, leave the rest alone.

    Returns the new text and the ids of blocks that were appended because the
    existing document did not contain them.
    """
    seen: set[str] = set()

    def replace(match: re.Match) -> str:
        block_id = match.group("id") or "attempts"
        if block_id in blocks:
            seen.add(block_id)
            return render_block(block_id, blocks[block_id])
        return match.group(0)

    text = _BLOCK_RE.sub(replace, existing)
    missing = [bid for bid in blocks if bid not in seen]
    if missing:
        titles = {
            "attempts": "Attempts index",
            "reel": "Brilliancies and blunders reel",
            "wildcards": "Wildcard review",
        }
        extra = "\n\n".join(
            "## " + titles.get(bid, bid) + "\n\n" + render_block(bid, blocks[bid])
            for bid in missing
        )
        text = text.rstrip() + "\n\n" + extra + "\n"
    return text.rstrip() + "\n", missing


# --------------------------------------------------------------------------
# Sub-processes
# --------------------------------------------------------------------------


def _describe(cmd: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in cmd)


def run_collect(scripts_dir: Path, repo: Path, results: Path) -> None:
    """Run ``collect_results.py`` over every attempt branch of the repository."""
    script = scripts_dir / "collect_results.py"
    if not script.is_file():
        raise RetroError(
            f"{script}: not found, so attempt branches cannot be collected. "
            "Re-run with --skip-collect if results/ is already up to date."
        )
    cmd = [
        sys.executable,
        str(script),
        "--repo",
        str(repo),
        "--results",
        str(results),
    ]
    print(f"[retro] collecting attempt branches: {_describe(cmd)}")
    proc = subprocess.run(cmd, cwd=str(repo), text=True)
    if proc.returncode != 0:
        raise RetroError(
            f"collect_results.py exited with code {proc.returncode}.\n"
            f"  command: {_describe(cmd)}\n"
            f"  run from: {repo}\n"
            "Fix the problem it reported, or re-run this script with "
            "--skip-collect to use the results/ tree as it stands."
        )


def run_stats(scripts_dir: Path, repo: Path, results: Path, cid: str, out_file: Path) -> bool:
    """Capture ``stats.py`` stdout into ``stats.txt``. Warnings, never fatal."""
    script = scripts_dir / "stats.py"
    if not script.is_file():
        print(
            f"[retro] notice: {script} does not exist yet; no stats.txt written.",
            file=sys.stderr,
        )
        return False
    cmd = [sys.executable, str(script), str(results), "--challenge", cid]
    print(f"[retro] measuring: {_describe(cmd)}")
    proc = subprocess.run(cmd, cwd=str(repo), text=True, stdout=subprocess.PIPE)
    if proc.returncode != 0:
        print(
            f"[retro] warning: stats.py exited with code {proc.returncode}; "
            f"{out_file.name} was not written.\n"
            f"  command: {_describe(cmd)}",
            file=sys.stderr,
        )
        return False
    out_file.write_text(proc.stdout, encoding="utf-8")
    return True


def run_gallery(
    repo: Path, results: Path, cid: str, out_file: Path, template: Optional[str]
) -> bool:
    """Render the gallery with the challenge's own tool, when there is one."""
    challenge_dir = repo / "challenges" / cid
    if template is None:
        if not (challenge_dir / "tools" / "gallery.py").is_file():
            print(
                f"[retro] notice: challenges/{cid}/tools/gallery.py does not "
                "exist, so no gallery was rendered. Pass --gallery-cmd "
                "'<shell template>' to build one with a different tool.",
                file=sys.stderr,
            )
            return False
        template = DEFAULT_GALLERY_CMD

    results_glob = str(results / cid / "*" / "*" / "solutions" / "*.json")
    cwd = challenge_dir if challenge_dir.is_dir() else repo
    try:
        command = template.format(
            python=shlex.quote(sys.executable),
            results_glob=shlex.quote(results_glob),
            out=shlex.quote(str(out_file)),
        )
    except (KeyError, IndexError, ValueError) as exc:
        raise RetroError(
            f"--gallery-cmd could not be filled in ({exc}); the available "
            "placeholders are {python}, {results_glob} and {out}, and a "
            "literal brace must be written as {{ or }}."
        ) from None

    print(f"[retro] rendering the gallery: {command}")
    proc = subprocess.run(command, cwd=str(cwd), shell=True, text=True)
    if proc.returncode != 0:
        print(
            f"[retro] warning: the gallery command exited with code "
            f"{proc.returncode}; {out_file.name} may be missing or stale.\n"
            f"  command: {command}\n"
            f"  run from: {cwd}",
            file=sys.stderr,
        )
        return False
    return True


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="retro.py",
        description=(
            "Assemble retros/<cid>/ for one étude: collect the attempt "
            "branches, write stats.txt, render gallery.html when the "
            "challenge has a gallery tool, and pre-fill retro.md."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Re-running is safe: only the <!-- generated:start ... --> blocks "
            "in retro.md are refreshed, everything you wrote around them is "
            "kept."
        ),
    )
    parser.add_argument(
        "--challenge",
        required=True,
        metavar="cXXX",
        help="challenge id, e.g. c001 (required)",
    )
    parser.add_argument(
        "--repo",
        metavar="DIR",
        help="repository root (default: the repository this script lives in)",
    )
    parser.add_argument(
        "--results",
        metavar="DIR",
        help="results tree to read (default: <repo>/results)",
    )
    parser.add_argument(
        "--out",
        metavar="DIR",
        help="output directory (default: <repo>/retros/<cid>)",
    )
    parser.add_argument(
        "--skip-collect",
        action="store_true",
        help="do not run collect_results.py; use results/ as it stands",
    )
    parser.add_argument(
        "--gallery-cmd",
        metavar="TEMPLATE",
        help=(
            "shell command template for the gallery, run from the challenge "
            "directory. Placeholders: {python} (this interpreter), "
            "{results_glob}, {out}. Default when the challenge has "
            "tools/gallery.py: " + DEFAULT_GALLERY_CMD
        ),
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    cid = args.challenge
    if not lib.CHALLENGE_ID_RE.fullmatch(cid):
        raise RetroError(
            f"--challenge must be a challenge id such as c001 (pattern "
            f"^c[0-9]{{3}}$), found {cid!r}"
        )

    if args.repo:
        repo = Path(args.repo).expanduser().resolve()
        if not repo.is_dir():
            raise RetroError(f"--repo {args.repo}: no such directory")
    else:
        repo = lib.repo_root_from(Path(__file__).resolve())

    if not (repo / "challenges" / cid / "challenge.yaml").is_file():
        raise RetroError(
            f"no such challenge: {repo / 'challenges' / cid} has no challenge.yaml"
        )

    scripts_dir = Path(__file__).resolve().parent
    results = Path(args.results).expanduser().resolve() if args.results else repo / "results"
    out_dir = Path(args.out).expanduser().resolve() if args.out else repo / "retros" / cid

    if not args.skip_collect:
        run_collect(scripts_dir, repo, results)

    if not results.is_dir():
        print(
            f"[retro] notice: {results} does not exist, so there is nothing "
            "collected to read. Run collect_results.py (or drop "
            "--skip-collect) and try again; retro.md is written with empty "
            "tables in the meantime.",
            file=sys.stderr,
        )

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RetroError(f"{out_dir}: could not create the output directory ({exc})")

    run_stats(scripts_dir, repo, results, cid, out_dir / "stats.txt")
    run_gallery(repo, results, cid, out_dir / "gallery.html", args.gallery_cmd)

    sessions = [s for s in lib.walk_results(results) if s.cid == cid]
    if not sessions:
        print(
            f"[retro] notice: no collected attempts for {cid} under {results}; "
            "retro.md is written with empty tables.",
            file=sys.stderr,
        )

    blocks = {
        "attempts": build_attempts_table(sessions),
        "reel": "```\n" + build_reel(sessions) + "\n```",
        "wildcards": build_wildcard_table(sessions),
    }

    retro_path = out_dir / "retro.md"
    if retro_path.is_file():
        existing = retro_path.read_text(encoding="utf-8")
        text, appended = refresh_document(existing, blocks)
        for bid in appended:
            print(
                f"[retro] notice: {retro_path.name} had no '{bid}' block, so a "
                "fresh one was appended at the end.",
                file=sys.stderr,
            )
        action = "refreshed"
    else:
        template_path = repo / "templates" / "retro.md"
        if template_path.is_file():
            template_text = template_path.read_text(encoding="utf-8")
        else:
            print(
                f"[retro] notice: {template_path} not found; using the built-in "
                "skeleton.",
                file=sys.stderr,
            )
            template_text = FALLBACK_TEMPLATE
        number = None
        try:
            number = lib.load_manifest(repo / "challenges" / cid).get("number")
        except lib.EtudesError:
            number = None
        text = build_document(template_text, blocks, cid, number)
        action = "written"
    retro_path.write_text(text, encoding="utf-8")

    print()
    print(f"# {cid} — brilliancies and blunders reel")
    print(build_reel(sessions))
    print()
    print(f"[retro] {action}: {retro_path}")
    for name in ("stats.txt", "gallery.html"):
        if (out_dir / name).is_file():
            print(f"[retro] wrote:     {out_dir / name}")
    print(
        f"[retro] {len(sessions)} attempt(s) for {cid}. Fill in the TODO "
        "sections of retro.md, then open the retro PR."
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except lib.EtudesError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:  # pragma: no cover
        sys.exit(130)
