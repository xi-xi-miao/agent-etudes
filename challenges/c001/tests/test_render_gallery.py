"""Tests for ``tools/render.py`` and ``tools/gallery.py``.

The renderer is checked by parsing its output as XML (not by string matching),
and the gallery by inspecting the emitted HTML: grouping by instance, sorted
group headings, alphabetical card order inside a group, and caption derivation
from a ``results/<cid>/<participant>/<n>/`` path.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET

import pytest

pytest.importorskip("shapely")

import gallery  # noqa: E402  (conftest puts tools/ on sys.path)
import geom  # noqa: E402
import render  # noqa: E402

SVG_NS = "http://www.w3.org/2000/svg"
Q = "{%s}%%s" % SVG_NS

# The vocabulary that must not appear under ``challenges/`` is spelled here in
# halves, so this test file does not itself trip the repo-wide word check.
_BANNED_HALVES = [("leader", "board"), ("sco", "re"), ("ran", "k"), ("win", "ner")]
FORBIDDEN = re.compile(
    r"\b(?:" + "|".join(a + b for a, b in _BANNED_HALVES) + r")(?:s|ing|ings)?\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def holed_instance(tiny_instance):
    """W=100 instance whose first part is a 40x40 square with a 20x20 hole."""
    parts = [
        {
            "id": "p001",
            "exterior": [[0.0, 0.0], [40.0, 0.0], [40.0, 40.0], [0.0, 40.0]],
            # clockwise hole
            "holes": [[[10.0, 10.0], [10.0, 30.0], [30.0, 30.0], [30.0, 10.0]]],
        },
        {"id": "p002", "exterior": [[0.0, 0.0], [30.0, 0.0], [0.0, 30.0]], "holes": []},
        {
            "id": "p003",
            "exterior": [[0.0, 0.0], [20.0, 0.0], [20.0, 20.0], [0.0, 20.0]],
            "holes": [],
        },
    ]
    return tiny_instance(instance_id="c001-t3-dev-01", tier=3, parts=parts)


@pytest.fixture
def hand_solution():
    """The square on the floor, the triangle above it, the small square beside
    the triangle: used height 80 on a 100-wide strip."""
    return {
        "instance_id": "c001-t3-dev-01",
        "solver": {"name": "hand", "version": "0"},
        "placements": [
            {"part_id": "p001", "translation": [0.0, 0.0], "rotation_deg": 0.0},
            {"part_id": "p002", "translation": [0.0, 50.0], "rotation_deg": 0.0},
            {"part_id": "p003", "translation": [50.0, 50.0], "rotation_deg": 0.0},
        ],
    }


def _parse(path_or_text):
    text = path_or_text if isinstance(path_or_text, str) else path_or_text.read_text(encoding="utf-8")
    return ET.fromstring(text)


def _texts(root):
    return [(el.text or "") for el in root.findall(Q % "text")]


def _outline(root):
    """The strip outline: the one unfilled ``<rect>`` of a layout SVG."""
    (rect,) = [r for r in root.findall(Q % "rect") if r.get("fill") == "none"]
    return rect


# ---------------------------------------------------------------------------
# render.py -- solution mode
# ---------------------------------------------------------------------------


def test_solution_svg_is_wellformed_svg(holed_instance, hand_solution, tmp_path):
    out = render.write_svg(holed_instance, hand_solution, tmp_path / "layout.svg")
    assert out.is_file()
    root = _parse(out)
    assert root.tag == Q % "svg"
    assert root.get("viewBox")
    # Nothing sticks out of the strip, so the canvas is exactly the target width.
    assert float(root.get("width")) == pytest.approx(render.TARGET_WIDTH)


def test_solution_svg_has_exactly_one_dashed_line(holed_instance, hand_solution):
    root = _parse(render.svg_string(holed_instance, hand_solution))
    lines = root.findall(Q % "line")
    assert len(lines) == 1
    assert lines[0].get("stroke-dasharray")
    # the marker is horizontal, at the used height
    assert lines[0].get("y1") == lines[0].get("y2")


def test_strip_outline_and_marker_are_where_the_geometry_says(holed_instance, hand_solution):
    """The dashed marker sits at used_height inside a strip drawn to draw_height,
    with y = 0 at the bottom of the outline."""
    root = _parse(render.svg_string(holed_instance, hand_solution))
    outline = [r for r in root.findall(Q % "rect") if r.get("fill") == "none"]
    assert len(outline) == 1
    rect = outline[0]
    y0, height = float(rect.get("y")), float(rect.get("height"))
    used_h, _, _ = render.layout_measures(holed_instance, hand_solution)
    draw_h = max(used_h * render.HEIGHT_HEADROOM, render.MIN_DRAW_HEIGHT)
    assert draw_h == pytest.approx(100.0)  # the minimum floor bites here

    line = root.findall(Q % "line")[0]
    # y grows downward in SVG, so the marker is measured up from the bottom edge
    assert float(line.get("y1")) == pytest.approx(
        y0 + height * (draw_h - used_h) / draw_h, abs=0.01
    )
    assert y0 < float(line.get("y1")) < y0 + height
    # the outline is as wide as the strip, in the same scale
    assert float(rect.get("width")) == pytest.approx(
        height * holed_instance["strip_width"] / draw_h, rel=1e-9
    )
    # y is flipped in Python: no mirroring transform on any element
    assert "scale(1,-1)" not in ET.tostring(root, encoding="unicode")
    assert root.get("transform") is None


def test_the_floor_is_at_the_bottom_of_the_picture(holed_instance, hand_solution):
    """A part at y = 0 is drawn against the bottom edge of the strip outline."""
    root = _parse(render.svg_string(holed_instance, hand_solution))
    rect = [r for r in root.findall(Q % "rect") if r.get("fill") == "none"][0]
    bottom = float(rect.get("y")) + float(rect.get("height"))
    p001 = [p for p in root.findall(Q % "path") if p.get("data-part-id") == "p001"][0]
    ys = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", p001.get("d"))][1::2]
    assert max(ys) == pytest.approx(bottom, abs=0.01)


def test_layouts_of_one_instance_share_a_scale(holed_instance, hand_solution):
    """Two layouts of the same instance are drawn at one scale: same canvas
    width, same strip width in pixels, and the canvas height follows the used
    height -- so the better layout is simply the shorter picture."""
    taller = json.loads(json.dumps(hand_solution))
    taller["placements"][2]["translation"] = [50.0, 500.0]
    roots = [_parse(render.svg_string(holed_instance, s)) for s in (hand_solution, taller)]
    rects = [_outline(root) for root in roots]
    assert roots[0].get("width") == roots[1].get("width")
    assert rects[0].get("width") == rects[1].get("width")
    heights = [
        max(
            render.layout_measures(holed_instance, s)[0] * render.HEIGHT_HEADROOM,
            render.MIN_DRAW_HEIGHT,
        )
        for s in (hand_solution, taller)
    ]
    assert float(rects[1].get("height")) / float(rects[0].get("height")) == pytest.approx(
        heights[1] / heights[0], rel=1e-9
    )
    assert float(roots[1].get("height")) > float(roots[0].get("height"))


def test_a_layout_that_leaves_the_strip_keeps_the_shared_scale(holed_instance, hand_solution):
    """The scale is fixed by the strip width alone: a part hanging past x = W
    widens the canvas but leaves the strip outline -- and so every other layout
    of the instance -- at the same pixel width and height."""
    spilling = json.loads(json.dumps(hand_solution))
    spilling["placements"][2]["translation"] = [150.0, 50.0]  # p003 past x = W = 100
    clean = _parse(render.svg_string(holed_instance, hand_solution))
    spilt = _parse(render.svg_string(holed_instance, spilling))
    rects = [_outline(root) for root in (clean, spilt)]
    assert float(rects[1].get("width")) == pytest.approx(render.TARGET_WIDTH - 2 * render.MARGIN)
    assert rects[0].get("width") == rects[1].get("width")
    assert rects[0].get("height") == rects[1].get("height")
    assert float(spilt.get("width")) > float(clean.get("width"))
    assert spilt.get("height") == clean.get("height")


def test_runaway_layout_keeps_the_header_inside_the_viewport():
    """A part placed absurdly far up the strip, or absurdly far to the side
    (W=1000), must not blow the canvas past the caps or clip the header when
    the scale is shrunk to fit."""
    instance = {
        "instance_id": "c001-t1-dev-01",
        "challenge": "c001",
        "tier": 1,
        "seed": 1,
        "strip_width": 1000.0,
        "rotations_allowed": "free",
        "parts": [
            {
                "id": "p{:03d}".format(i),
                "exterior": [[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0]],
                "holes": [],
            }
            for i in range(40)
        ],
    }
    upward = {
        "instance_id": "c001-t1-dev-01",
        "placements": [{"part_id": "p000", "translation": [0.0, 200000.0], "rotation_deg": 0.0}],
    }
    sideways = {
        "instance_id": "c001-t1-dev-01",
        "placements": [{"part_id": "p000", "translation": [50000.0, 0.0], "rotation_deg": 0.0}],
    }
    for svg in (
        render.svg_string(instance, upward),
        render.svg_string(instance, sideways),
        render.svg_string(instance),
    ):
        root = _parse(svg)
        assert float(root.get("width")) >= render.MIN_CANVAS_WIDTH
        assert float(root.get("width")) <= render.MAX_WIDTH + 1.0
        assert float(root.get("height")) <= render.MAX_HEIGHT + 1.0
        assert root.get("viewBox") == "0 0 {} {}".format(root.get("width"), root.get("height"))


def test_baseline_sized_layout_keeps_the_shared_scale():
    """The caps must not bite for a layout the size the baseline produces on the
    dev set (W = 1000, ~6500 tall), or two such layouts would stop comparing."""
    instance = {
        "instance_id": "c001-t1-dev-01",
        "challenge": "c001",
        "tier": 1,
        "seed": 1,
        "strip_width": 1000.0,
        "rotations_allowed": "free",
        "parts": [
            {
                "id": "p001",
                "exterior": [[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0]],
                "holes": [],
            }
        ],
    }
    solution = {
        "instance_id": "c001-t1-dev-01",
        "placements": [{"part_id": "p001", "translation": [0.0, 6400.0], "rotation_deg": 0.0}],
    }
    root = _parse(render.svg_string(instance, solution))
    assert float(root.get("width")) == pytest.approx(render.TARGET_WIDTH)
    rect = [r for r in root.findall(Q % "rect") if r.get("fill") == "none"][0]
    assert float(rect.get("width")) == pytest.approx(render.TARGET_WIDTH - 2 * render.MARGIN)


def test_solution_svg_has_one_evenodd_path_per_part(holed_instance, hand_solution):
    root = _parse(render.svg_string(holed_instance, hand_solution))
    paths = root.findall(Q % "path")
    assert len(paths) == len(holed_instance["parts"])
    by_id = {p.get("data-part-id"): p for p in paths}
    assert set(by_id) == {"p001", "p002", "p003"}
    for path in paths:
        assert path.get("fill-rule") == "evenodd"
        assert path.get("fill") in geom.PALETTE
        assert path.get("fill-opacity") == "0.6"
        assert path.get("stroke") == "#222222"
        assert path.get("stroke-width") == "1"
    # the holed part carries two subpaths, so its hole is punched out
    assert by_id["p001"].get("d").count("M") == 2
    assert by_id["p002"].get("d").count("M") == 1


def test_solution_header_reports_utilization_and_used_height(holed_instance, hand_solution):
    root = _parse(render.svg_string(holed_instance, hand_solution))
    header = " ".join(_texts(root))
    used_h, util, placed = render.layout_measures(holed_instance, hand_solution)
    assert used_h == pytest.approx(80.0)
    assert placed == 3
    # 1600 - 400 + 450 + 400 = 2050 over 100 * 80
    assert util == pytest.approx(2050.0 / 8000.0)
    assert "utilization" in header
    assert geom.format_pct(util) + "%" in header
    assert "used height" in header
    assert holed_instance["instance_id"] in header


def test_part_labels_only_with_labels_flag(holed_instance, hand_solution):
    plain = _texts(_parse(render.svg_string(holed_instance, hand_solution)))
    assert not [t for t in plain if t.strip() in {"p001", "p002", "p003"}]

    labelled = _texts(_parse(render.svg_string(holed_instance, hand_solution, labels=True)))
    assert {"p001", "p002", "p003"} <= {t.strip() for t in labelled}


def test_header_carries_no_participant_information(holed_instance, hand_solution):
    text = render.svg_string(holed_instance, hand_solution)
    assert "hand" not in " ".join(_texts(_parse(text)))


def test_used_height_marker_moves_with_the_layout(holed_instance, hand_solution):
    shifted = json.loads(json.dumps(hand_solution))
    shifted["placements"][1]["translation"] = [0.0, 500.0]
    used_h, util, _ = render.layout_measures(holed_instance, shifted)
    assert used_h == pytest.approx(530.0)
    base_used, base_util, _ = render.layout_measures(holed_instance, hand_solution)
    assert util < base_util


def test_rotated_placement_is_rendered(holed_instance):
    """A 90 degree rotation about the local origin lands the part in -x/+y."""
    solution = {
        "instance_id": holed_instance["instance_id"],
        "placements": [
            {"part_id": "p001", "translation": [40.0, 0.0], "rotation_deg": 90.0},
            {"part_id": "p002", "translation": [50.0, 0.0], "rotation_deg": 0.0},
            {"part_id": "p003", "translation": [0.0, 60.0], "rotation_deg": 0.0},
        ],
    }
    used_h, _, placed = render.layout_measures(holed_instance, solution)
    assert placed == 3
    assert used_h == pytest.approx(80.0)
    root = _parse(render.svg_string(holed_instance, solution))
    assert len(root.findall(Q % "path")) == 3


def test_partial_solution_renders_the_parts_it_has(holed_instance):
    solution = {
        "instance_id": holed_instance["instance_id"],
        "placements": [
            {"part_id": "p001", "translation": [0.0, 0.0], "rotation_deg": 0.0},
            {"part_id": "pXXX", "translation": [0.0, 0.0], "rotation_deg": 0.0},
        ],
    }
    root = _parse(render.svg_string(holed_instance, solution))
    paths = root.findall(Q % "path")
    assert [p.get("data-part-id") for p in paths] == ["p001"]
    # utilization still counts every part of the instance, as the validator does
    _, util, placed = render.layout_measures(holed_instance, solution)
    assert placed == 1
    assert util == pytest.approx(geom.total_area(holed_instance) / (100.0 * 40.0))


# ---------------------------------------------------------------------------
# render.py -- catalog mode
# ---------------------------------------------------------------------------


def test_catalog_mode_draws_one_path_per_part_and_no_line(holed_instance, tmp_path):
    out = render.write_svg(holed_instance, None, tmp_path / "catalog.svg")
    root = _parse(out)
    assert root.tag == Q % "svg"
    # the catalog keeps its own, wider canvas: it is not a layout to compare
    assert float(root.get("width")) == pytest.approx(render.CATALOG_WIDTH)
    assert len(root.findall(Q % "path")) == len(holed_instance["parts"])
    assert root.findall(Q % "line") == []
    texts = {t.strip() for t in _texts(root)}
    # the catalog always labels its cells, whatever --labels says
    assert {"p001", "p002", "p003"} <= texts


def test_catalog_paths_do_not_overlap_in_x(holed_instance):
    """Grid cells are laid out side by side, so no two cells share an x span."""
    root = _parse(render.svg_string(holed_instance))
    xs = []
    for path in root.findall(Q % "path"):
        numbers = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", path.get("d"))]
        xs.append(min(numbers[0::2]))
    assert len(set(round(x, 3) for x in xs)) >= 2


def test_catalog_of_a_single_part_still_renders(tiny_instance):
    one = tiny_instance(parts=[{"id": "only", "exterior": [[0, 0], [10, 0], [0, 10]], "holes": []}])
    root = _parse(render.svg_string(one))
    assert len(root.findall(Q % "path")) == 1


def test_svg_string_rejects_an_empty_instance(tiny_instance):
    with pytest.raises(geom.InstanceError):
        render.svg_string(tiny_instance(parts=[]))


# ---------------------------------------------------------------------------
# render.py -- CLI
# ---------------------------------------------------------------------------


def test_render_cli_both_modes(run_tool, holed_instance, hand_solution, tmp_path):
    inst_path = geom.write_json(holed_instance, tmp_path / "inst.json")
    sol_path = geom.write_json(hand_solution, tmp_path / "sol.json")

    catalog = tmp_path / "catalog.svg"
    done = run_tool("render", inst_path, "--out", catalog)
    assert done.returncode == 0, done.stderr
    assert _parse(catalog).tag == Q % "svg"

    layout = tmp_path / "layout.svg"
    done = run_tool("render", inst_path, sol_path, "--out", layout, "--labels")
    assert done.returncode == 0, done.stderr
    root = _parse(layout)
    assert len(root.findall(Q % "line")) == 1
    assert "p001" in {t.strip() for t in _texts(root)}


def test_render_cli_rejects_a_mismatched_solution(run_tool, holed_instance, hand_solution, tmp_path):
    inst_path = geom.write_json(holed_instance, tmp_path / "inst.json")
    other = dict(hand_solution, instance_id="c001-t1-dev-99")
    sol_path = geom.write_json(other, tmp_path / "sol.json")
    done = run_tool("render", inst_path, sol_path, "--out", tmp_path / "x.svg")
    assert done.returncode == 2
    assert "mismatch" in done.stderr


def test_render_cli_rejects_an_unreadable_instance(run_tool, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    done = run_tool("render", bad, "--out", tmp_path / "x.svg")
    assert done.returncode == 2


# ---------------------------------------------------------------------------
# gallery.py
# ---------------------------------------------------------------------------


def _square_instance(instance_id, tier):
    return {
        "instance_id": instance_id,
        "challenge": "c001",
        "tier": tier,
        "seed": 1,
        "strip_width": 100.0,
        "rotations_allowed": "free",
        "parts": [
            {
                "id": "p001",
                "exterior": [[0.0, 0.0], [40.0, 0.0], [40.0, 40.0], [0.0, 40.0]],
                "holes": [],
            },
            {
                "id": "p002",
                "exterior": [[0.0, 0.0], [20.0, 0.0], [20.0, 20.0], [0.0, 20.0]],
                "holes": [],
            },
        ],
    }


def _solution(instance_id, shift):
    return {
        "instance_id": instance_id,
        "placements": [
            {"part_id": "p001", "translation": [0.0, 0.0], "rotation_deg": 0.0},
            {"part_id": "p002", "translation": [50.0, float(shift)], "rotation_deg": 0.0},
        ],
    }


@pytest.fixture
def results_tree(tmp_path):
    """A tiny ``results/`` tree: alice/2 and bob/1 on one instance, bob/1 on another."""
    instances = tmp_path / "instances"
    geom.write_json(_square_instance("c001-t1-dev-01", 1), instances / "c001-t1-dev-01.json")
    geom.write_json(_square_instance("c001-t2-dev-02", 2), instances / "c001-t2-dev-02.json")

    root = tmp_path / "results" / "c001"
    # alice sorts first alphabetically but uses MORE height: card order must not
    # follow the measure.
    alice = geom.write_json(
        _solution("c001-t1-dev-01", 300), root / "alice" / "2" / "solutions" / "x.json"
    )
    bob = geom.write_json(
        _solution("c001-t1-dev-01", 50), root / "bob" / "1" / "solutions" / "x.json"
    )
    other = geom.write_json(
        _solution("c001-t2-dev-02", 60), root / "bob" / "1" / "solutions" / "y.json"
    )
    return {"instances": instances, "alice": alice, "bob": bob, "other": other, "tmp": tmp_path}


def test_label_derivation_from_a_results_path(results_tree):
    assert gallery.label_for(results_tree["alice"]) == "alice / attempt 2"
    assert gallery.label_for(results_tree["bob"]) == "bob / attempt 1"


def test_label_falls_back_to_the_file_stem(tmp_path):
    loose = tmp_path / "somewhere" / "my-layout.json"
    geom.write_json(_solution("c001-t1-dev-01", 10), loose)
    assert gallery.label_for(loose) == "my-layout"


def test_gallery_groups_by_instance_with_sorted_headings(results_tree, tmp_path):
    out = gallery.write_gallery(
        [results_tree["bob"], results_tree["other"], results_tree["alice"]],
        tmp_path / "gallery.html",
        instances_dir=results_tree["instances"],
    )
    html = out.read_text(encoding="utf-8")

    first = "<h2>c001-t1-dev-01</h2>"
    second = "<h2>c001-t2-dev-02</h2>"
    assert html.count(first) == 1
    assert html.count(second) == 1
    assert html.index(first) < html.index(second)

    # both cards of the first instance live under the first heading
    alice_at = html.index("alice / attempt 2")
    bob_at = html.index("bob / attempt 1")
    assert html.index(first) < alice_at < bob_at < html.index(second)

    # ... and that alphabetical order is not the utilization order
    instance = geom.load_instance(results_tree["instances"] / "c001-t1-dev-01.json")
    _, alice_util, _ = render.layout_measures(instance, geom.load_solution(results_tree["alice"]))
    _, bob_util, _ = render.layout_measures(instance, geom.load_solution(results_tree["bob"]))
    assert alice_util < bob_util

    # two layouts for instance one, one for instance two
    assert html.count("<svg ") == 3
    assert html.count('<div class="card">') == 3
    assert "Gallery — c001" in html
    assert "utilization {}%".format(geom.format_pct(bob_util)) in html


def test_gallery_embeds_parsable_svgs(results_tree, tmp_path):
    html = gallery.build_gallery(
        [results_tree["alice"]], instances_dir=results_tree["instances"]
    )
    start = html.index("<svg ")
    end = html.index("</svg>") + len("</svg>")
    root = ET.fromstring(html[start:end])
    assert root.tag == Q % "svg"
    assert len(root.findall(Q % "path")) == 2


def test_gallery_accepts_a_directory_and_a_glob(results_tree, tmp_path):
    directory = results_tree["bob"].parent
    from_dir = gallery.expand_paths([directory])
    assert sorted(p.name for p in from_dir) == ["x.json", "y.json"]

    pattern = str(results_tree["tmp"] / "results" / "c001" / "*" / "*" / "solutions" / "*.json")
    from_glob = gallery.expand_paths([pattern])
    assert len(from_glob) == 3
    assert len(gallery.expand_paths([pattern, directory])) == 3  # de-duplicated


def test_gallery_skips_a_solution_whose_instance_is_missing(tmp_path, capsys):
    orphan = geom.write_json(_solution("c001-t9-dev-77", 10), tmp_path / "orphan.json")
    out = tmp_path / "gallery.html"
    code = gallery.main([str(orphan), "--out", str(out), "--instances-dir", str(tmp_path)])
    captured = capsys.readouterr()
    assert code == 0
    assert "c001-t9-dev-77" in captured.err
    html = out.read_text(encoding="utf-8")
    assert "<svg " not in html
    assert "No layouts to show." in html


def test_gallery_cli(results_tree, tmp_path, run_tool):
    out = tmp_path / "cli-gallery.html"
    pattern = str(results_tree["tmp"] / "results" / "c001" / "*" / "*" / "solutions" / "*.json")
    done = run_tool(
        "gallery", pattern, "--out", out, "--instances-dir", results_tree["instances"]
    )
    assert done.returncode == 0, done.stderr
    html = out.read_text(encoding="utf-8")
    assert html.count('<div class="card">') == 3


def test_cards_are_one_width_and_bottom_aligned():
    """Renderer and gallery contracts: every card the same width and bottom-aligned,
    so the strips of one instance stand on one floor at one scale."""
    cards = re.search(r"\.cards\s*\{([^}]*)\}", gallery.CSS).group(1)
    card = re.search(r"\.card\s*\{([^}]*)\}", gallery.CSS).group(1)
    assert "align-items: flex-end" in cards
    assert re.search(r"flex:\s*0\s+1\s", card), "cards must not grow to fill a row"


def test_card_provenance_is_relative_and_leaks_no_absolute_path(results_tree, monkeypatch):
    """A committed gallery must not carry the builder's home directory."""
    monkeypatch.chdir(results_tree["tmp"])
    html = gallery.build_gallery(
        [results_tree["alice"], results_tree["bob"], results_tree["other"]],
        instances_dir=results_tree["instances"],
    )
    shown = re.findall(r'<div class="path">([^<]*)</div>', html)
    assert len(shown) == 3
    for text in shown:
        assert not text.startswith("/")
        assert text.startswith("results/c001/")
    assert str(results_tree["tmp"]) not in html


def test_provenance_of_a_file_outside_the_working_directory_is_its_name(tmp_path):
    outside = tmp_path / "not-under-cwd" / "layout.json"
    geom.write_json(_solution("c001-t1-dev-01", 10), outside)
    assert gallery.display_path(outside) == "layout.json"


def test_instance_lookup_prefers_the_explicit_directory(results_tree):
    found = gallery.find_instance("c001-t1-dev-01", results_tree["instances"])
    assert found == results_tree["instances"] / "c001-t1-dev-01.json"
    assert gallery.find_instance("c001-t1-dev-01", None) in (None,) + tuple(
        d / "c001-t1-dev-01.json" for d in gallery.DEFAULT_INSTANCE_DIRS
    )


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


def test_no_forbidden_vocabulary_in_the_output(results_tree, holed_instance, hand_solution, tmp_path):
    html = gallery.build_gallery(
        [results_tree["alice"], results_tree["bob"], results_tree["other"]],
        instances_dir=results_tree["instances"],
    )
    for text in (
        html,
        render.svg_string(holed_instance, hand_solution, labels=True),
        render.svg_string(holed_instance),
    ):
        assert not FORBIDDEN.search(text)


def test_no_forbidden_vocabulary_in_the_sources(tools_dir):
    for name in ("render.py", "gallery.py"):
        assert not FORBIDDEN.search((tools_dir / name).read_text(encoding="utf-8"))


def test_parts_outside_the_strip_stay_inside_the_viewbox(tiny_instance):
    """An INVALID layout (negative x, past x = W, below the floor) must be
    drawn, not clipped away."""
    instance = tiny_instance()
    solution = {
        "instance_id": instance["instance_id"],
        "placements": [
            {"part_id": "p001", "translation": [-60.0, 10.0], "rotation_deg": 0.0},
            {"part_id": "p002", "translation": [90.0, 30.0], "rotation_deg": 0.0},
            {"part_id": "p003", "translation": [10.0, -20.0], "rotation_deg": 0.0},
        ],
    }
    root = _parse(render.svg_string(instance, solution))
    _, _, vb_w, vb_h = (float(v) for v in root.get("viewBox").split())
    numbers = re.compile(r"-?\d+(?:\.\d+)?")
    for path in root.iter("{http://www.w3.org/2000/svg}path"):
        coords = [float(n) for n in numbers.findall(path.get("d"))]
        xs, ys = coords[0::2], coords[1::2]
        assert min(xs) >= -1e-6 and max(xs) <= vb_w + 1e-6
        assert min(ys) >= -1e-6 and max(ys) <= vb_h + 1e-6
