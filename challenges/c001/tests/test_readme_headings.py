"""The challenge README is the citation key, so the cited headings are pinned.

Code comments and test docstrings cite this README by heading text -- there are
no section numbers to cite any more.  A heading that gets renamed or dropped
would leave those citations pointing at nothing, silently; these tests turn that
into a failure.  Nothing here reads the prose under a heading: this is a
liveness check on the anchors, not a check on what they say.
"""

from __future__ import annotations

import re
from pathlib import Path

C001_DIR = Path(__file__).resolve().parent.parent
README = C001_DIR / "README.md"

#: Every heading cited from code, a test docstring, another document or an
#: in-file link.  See challenges/c001/tools/generate.py, tests/test_generate.py,
#: tests/test_baseline.py, tests/test_roundtrip.py and demo.sh.
CITED_HEADINGS = (
    "Start here",
    "Running the tools",
    "File formats",
    "Instance",
    "Size mix and totals",
    "Dev set and hidden set",
    "Checks, in order",
    "Tolerance",
    "Output",
    "What good looks like",
    "The reference floor",
    "Geometry conventions",
)


def _headings():
    """The text of every ATX heading line in the README, in file order."""
    text = README.read_text(encoding="utf-8")
    return [
        match.group(1).strip()
        for match in re.finditer(r"^#{1,6}[ \t]+(.+?)[ \t]*$", text, re.MULTILINE)
    ]


def test_every_cited_heading_exists():
    """Each cited heading is a heading line, not just a phrase in the prose."""
    headings = _headings()
    missing = [heading for heading in CITED_HEADINGS if heading not in headings]
    assert not missing, "README.md no longer has the cited heading(s): {}".format(
        ", ".join(missing)
    )


def test_the_spec_is_merged_into_the_readme():
    """One document per étude: SPEC.md was folded into README.md and removed."""
    assert not (C001_DIR / "SPEC.md").exists(), (
        "challenges/c001/SPEC.md is back; the étude has one document, README.md"
    )


def test_the_readme_cites_headings_and_never_section_numbers():
    """Headings are the citation key, so numbered cross-references are stale."""
    text = README.read_text(encoding="utf-8")
    assert "§" not in text, "README.md cites a section sign; cite the heading text"
    numbered = re.findall(r"section [0-9]", text, re.IGNORECASE)
    assert not numbered, "README.md cites {}; cite the heading text".format(numbered)
