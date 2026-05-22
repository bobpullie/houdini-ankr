"""Tests for markdown generation."""
from ankr.markdown_gen import render_segment_md, render_skeleton_md


def _sample_segment():
    return {
        "segment_id": "seg_05_house_scatter",
        "endnode": "/obj/KJI_Kr_House/OUT_houses",
        "upstream_landmark": "seg_04 (density_field)",
        "downstream_landmark": "seg_06 (concave_filter)",
        "node_count": 2,
        "data": {
            "input_attribs": ["P", "N", "density"],
            "output_attribs": ["P", "N", "density", "cluster_id"],
            "input_groups": ["terrain"],
            "output_groups": ["terrain", "house_candidates"],
            "geometry": "12000pts → 8500pts (-3500)",
        },
        "random_seeds": [
            {"node": "scatter_houses", "source": "param: seed", "value": 42},
        ],
        "narrative": "density 기반 voronoi로 가옥 부지 추출.",
        "issues": [],
        "nodes": [
            {
                "name": "scatter_houses",
                "type": "scatter",
                "kind": "data_transform",
                "reads": ["P", "density"],
                "writes": ["P", "cluster_id"],
                "params_non_default": {
                    "density attribute": "density",
                    "force total count": 4500,
                    "seed": 42,
                },
                "flags": {},
                "seed_note": "⚠️ random seed",
            },
            {
                "name": "attrib_house_idx",
                "type": "attribwrangle",
                "kind": "wrangle",
                "runover": "Points",
                "reads": ["cluster_id"],
                "writes": ["house_idx"],
                "params_non_default": {},
                "flags": {},
                "vex_code": "i@house_idx = i@cluster_id;",
            },
        ],
    }


def test_segment_has_yaml_frontmatter():
    md = render_segment_md(_sample_segment())
    assert md.startswith("---\n")


def test_segment_includes_id_and_endnode():
    md = render_segment_md(_sample_segment())
    assert "seg_05_house_scatter" in md
    assert "/obj/KJI_Kr_House/OUT_houses" in md


def test_segment_includes_data_meta():
    md = render_segment_md(_sample_segment())
    assert "input_attribs" in md
    assert "cluster_id" in md
    assert "house_candidates" in md
    assert "12000pts" in md


def test_segment_includes_narrative():
    md = render_segment_md(_sample_segment())
    assert "density 기반 voronoi" in md


def test_wrangle_node_includes_vex_code():
    md = render_segment_md(_sample_segment())
    assert "i@house_idx = i@cluster_id;" in md
    assert "vex" in md


def test_data_transform_node_includes_reads_writes():
    md = render_segment_md(_sample_segment())
    assert "reads" in md
    assert "writes" in md


def test_random_seed_warning_present():
    md = render_segment_md(_sample_segment())
    assert "⚠️" in md or "random seed" in md.lower()


def test_seed_42_in_output():
    md = render_segment_md(_sample_segment())
    assert "42" in md


def _sample_skeleton():
    return {
        "endnode": "/obj/KJI_Kr_House/OUT_houses",
        "hipfile_current": "KJI_Kr_House_v023.hip",
        "last_sync": "2026-04-08T14:23",
        "node_count_total": 487,
        "landmark_count": 4,
        "segment_count": 5,
        "random_seeds_in_use": [
            {"segment": "seg_04", "node": "set_density", "source": "vex", "value": "1337 (hardcoded)"},
            {"segment": "seg_05", "node": "scatter_houses", "source": "param: seed", "value": 42},
        ],
        "flag_anomalies": [
            {"segment": "seg_05", "node": "Bevel2", "flag": "bypass=ON", "note": "이유 미기록"},
        ],
        "unresolved_issues": [
            {"id": "H-7", "segment": "seg_05", "summary": "bypass 정리 여부"},
        ],
        "hda_dependencies": ["kji::village_split::1.0"],
        "landmarks": [
            {"id": "M1", "path": ".../trim_combine", "type": "merge", "kind": "branch", "inputs": 2, "between": "seg_01,seg_02 → seg_03"},
            {"id": "H1", "path": ".../villageSplit_1", "type": "kji::village_split::1.0", "kind": "hda", "between": "seg_03 → seg_04"},
        ],
        "segments_index": [
            {"id": "seg_01_terrain_load", "narrative": "terrain bgeo 로드", "warnings": []},
            {"id": "seg_03_house_voronoi", "narrative": "voronoi 분할", "warnings": ["random seed"]},
        ],
        "graph_edges": [
            {"from": "src_terrain", "to": "seg_01"},
            {"from": "seg_01", "to": "M1"},
            {"from": "seg_02", "to": "M1"},
            {"from": "M1", "to": "seg_03"},
            {"from": "seg_03", "to": "H1"},
            {"from": "H1", "to": "seg_04"},
            {"from": "seg_04", "to": "OUT"},
        ],
        "graph_nodes": {
            "src_terrain": {"label": "file: terrain.bgeo", "shape": "rect"},
            "seg_01": {"label": "seg_01", "shape": "rect"},
            "seg_02": {"label": "seg_02", "shape": "rect"},
            "seg_03": {"label": "seg_03", "shape": "rect"},
            "seg_04": {"label": "seg_04", "shape": "rect"},
            "M1": {"label": "merge: trim_combine", "shape": "diamond"},
            "H1": {"label": "HDA village_split::1.0", "shape": "subroutine"},
            "OUT": {"label": "OUT_houses", "shape": "rect"},
        },
    }


def test_skeleton_starts_with_frontmatter():
    md = render_skeleton_md(_sample_skeleton())
    assert md.startswith("---\n")


def test_skeleton_yaml_includes_random_seeds():
    md = render_skeleton_md(_sample_skeleton())
    assert "random_seeds_in_use" in md
    assert "scatter_houses" in md


def test_skeleton_yaml_includes_anomalies():
    md = render_skeleton_md(_sample_skeleton())
    assert "flag_anomalies" in md
    assert "bypass=ON" in md


def test_skeleton_yaml_includes_unresolved_issues():
    md = render_skeleton_md(_sample_skeleton())
    assert "H-7" in md


def test_skeleton_has_mermaid_tb_graph():
    md = render_skeleton_md(_sample_skeleton())
    assert "```mermaid" in md
    assert "graph TB" in md
    assert "seg_01 --> M1" in md
    assert "M1 --> seg_03" in md


def test_skeleton_has_landmark_table():
    md = render_skeleton_md(_sample_skeleton())
    assert "| ID" in md or "| ID  |" in md
    assert "M1" in md
    assert "H1" in md


def test_skeleton_has_segment_index():
    md = render_skeleton_md(_sample_skeleton())
    assert "## 세그먼트 인덱스" in md
    assert "seg_01_terrain_load" in md
    assert "seg_03_house_voronoi" in md
    assert "⚠️" in md or "warning" in md.lower() or "random seed" in md


def test_skeleton_links_to_segment_files():
    md = render_skeleton_md(_sample_skeleton())
    assert "(segments/seg_01_terrain_load.md)" in md


def test_skeleton_no_histogram_in_frontmatter():
    """After L0/L1 migration, histogram lives in map.yaml — skeleton frontmatter
    should not include node_type_histogram."""
    sk = {
        "endnode": "/obj/Test/OUT",
        "hipfile_current": "test.hip",
        "last_sync": "2026-04-09T14:00",
        "node_count_total": 5,
        "landmark_count": 0,
        "segment_count": 1,
        "random_seeds_in_use": [],
        "flag_anomalies": [],
        "unresolved_issues": [],
        "hda_dependencies": [],
        "node_type_histogram": {"null": 2, "attribwrangle": 3},
        "landmarks": [],
        "segments_index": [{"id": "seg_01", "narrative": "test", "warnings": []}],
        "graph_edges": [],
        "graph_nodes": {},
    }
    md = render_skeleton_md(sk)
    import yaml
    fm_text = md.split("---")[1]
    fm = yaml.safe_load(fm_text)
    assert "node_type_histogram" not in fm


def _skeleton_with_cross_refs():
    sk = _sample_skeleton()
    sk["cross_segment_refs"] = [
        {
            "from_segment": "seg_01_terrain",
            "to_segment": "seg_03_house_voronoi",
            "data_hint": ["P", "N"],
        },
    ]
    return sk


def test_skeleton_cross_refs_in_frontmatter():
    """cross_segment_refs appears in YAML frontmatter when non-empty."""
    import yaml
    md = render_skeleton_md(_skeleton_with_cross_refs())
    fm_text = md.split("---")[1]
    fm = yaml.safe_load(fm_text)
    assert "cross_segment_refs" in fm
    assert len(fm["cross_segment_refs"]) == 1
    assert fm["cross_segment_refs"][0]["from_segment"] == "seg_01_terrain"


def test_skeleton_cross_refs_mermaid_dotted():
    """Mermaid block contains dotted arrows for cross-segment refs."""
    md = render_skeleton_md(_skeleton_with_cross_refs())
    assert '-.->|"P, N"|' in md
    assert "seg_01 -.->|" in md
    assert "seg_03" in md


def test_skeleton_no_cross_refs():
    """Empty cross_segment_refs: no dotted arrows, no frontmatter field."""
    import yaml
    sk = _sample_skeleton()
    sk["cross_segment_refs"] = []
    md = render_skeleton_md(sk)
    fm_text = md.split("---")[1]
    fm = yaml.safe_load(fm_text)
    assert "cross_segment_refs" not in fm
    assert ".->" not in md


def test_skeleton_segment_summary_table():
    sk = _sample_skeleton()
    sk["segment_summary"] = [
        {"seg_id": "seg_01_test", "nodes": 8, "wrangles": 1, "vex_lines": 32, "file_kb": 3.2, "split": 0},
        {"seg_id": "seg_05_heavy", "nodes": 23, "wrangles": 8, "vex_lines": 450, "file_kb": 25.1, "split": 3},
    ]
    md = render_skeleton_md(sk)
    assert "## 세그먼트 메타" in md
    assert "| seg_id" in md
    assert "seg_01_test" in md
    assert "450" in md
    assert "3" in md


def test_skeleton_without_segment_summary():
    """segment_summary가 없으면 세그먼트 메타 테이블은 출력되지 않는다."""
    sk = _sample_skeleton()
    md = render_skeleton_md(sk)
    assert "## 세그먼트 메타" not in md
