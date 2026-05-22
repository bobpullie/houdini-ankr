"""Tests for VEX code analysis."""
from ankr.vex_analyzer import analyze_vex, count_vex_lines


def test_simple_attrib_write():
    code = "@density = 1.0;"
    r = analyze_vex(code)
    assert "density" in r["writes"]


def test_typed_attrib_read():
    code = "float d = f@density;"
    r = analyze_vex(code)
    assert "density" in r["reads"]


def test_typed_attrib_write():
    code = "i@cluster_id = 5;"
    r = analyze_vex(code)
    assert "cluster_id" in r["writes"]


def test_attrib_read_and_write():
    code = """
    float d = f@density;
    @house_idx = i@cluster_id;
    """
    r = analyze_vex(code)
    assert "density" in r["reads"]
    assert "cluster_id" in r["reads"]
    assert "house_idx" in r["writes"]


def test_point_function_read():
    code = 'float v = point(0, "P", @ptnum).x;'
    r = analyze_vex(code)
    assert "P" in r["reads"]


def test_pointgroup_read():
    code = 'if (inpointgroup(0, "house_seed", @ptnum)) { @selected = 1; }'
    r = analyze_vex(code)
    assert "house_seed" in r["groups_read"]
    assert "selected" in r["writes"]


def test_setpointgroup_write():
    code = 'setpointgroup(0, "candidates", @ptnum, 1);'
    r = analyze_vex(code)
    assert "candidates" in r["groups_write"]


def test_random_with_int_seed():
    code = "@val = random(1337);"
    r = analyze_vex(code)
    assert any("1337" in str(s) for s in r["random_seeds"])


def test_random_with_expression_seed():
    code = "@val = random(@ptnum + 42);"
    r = analyze_vex(code)
    seeds = [str(s) for s in r["random_seeds"]]
    assert any("@ptnum + 42" in s or "@ptnum+42" in s.replace(" ", "") for s in seeds)


def test_nrandom_seed():
    code = '@val = nrandom("twister", 7);'
    r = analyze_vex(code)
    assert any("7" in str(s) for s in r["random_seeds"])


def test_no_random():
    code = "@density = 1.0;"
    r = analyze_vex(code)
    assert r["random_seeds"] == []


def test_skip_local_var():
    code = "float local = 1.0;"
    r = analyze_vex(code)
    assert "local" not in r["reads"]
    assert "local" not in r["writes"]


def test_count_vex_lines_simple():
    code = "i@foo = 1;\nf@bar = 2.0;\n"
    assert count_vex_lines(code) == 2


def test_count_vex_lines_with_blanks_and_comments():
    code = "// header\n\ni@foo = 1;\n\n// comment\nf@bar = 2.0;\n"
    assert count_vex_lines(code) == 2


def test_count_vex_lines_empty():
    assert count_vex_lines("") == 0
    assert count_vex_lines("   \n\n  ") == 0


def test_count_vex_lines_multiline():
    code = """// VEX wrangle
int n = npoints(0);
for (int i = 0; i < n; i++) {
    vector pos = point(0, "P", i);
    float dist = length(pos);
    if (dist > 1.0) {
        removepoint(0, i);
    }
}
"""
    assert count_vex_lines(code) == 8
