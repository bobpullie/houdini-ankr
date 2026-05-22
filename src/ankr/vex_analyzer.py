"""VEX code regex analysis — attribute / group / random seed extraction.

Not a perfect parser; macros, conditional attribute access, and user-defined
functions can produce false negatives. Scope of coverage: typical wrangle VEX
attribute reads/writes, group function calls, random number functions.

Pure-Python — no Houdini runtime dependency. Used by `hou_runtime` during
node enrichment and by the deadflow detection pipeline.
"""
from __future__ import annotations
import re

# Typed attribute prefix: f@, i@, v@, p@, 2@, 3@, 4@, 9@, s@, u@, d@ — or bare @
_TYPE_PREFIX = r"(?:[fiv2349spud]@|@)"
_ATTRIB_NAME = r"([A-Za-z_]\w*)"

# write pattern: type@name = ... (LHS context: start-of-line, `;`, `{`, `}` precedes)
_WRITE_RE = re.compile(
    rf"(?:^|;|\{{|\}})\s*{_TYPE_PREFIX}{_ATTRIB_NAME}\s*(?:\[\d+\])?\s*(?:[+\-*/]?=)(?!=)",
    re.MULTILINE,
)
# read pattern: any `type@name` occurrence (positional-agnostic; LHS writes are filtered separately)
_READ_RE = re.compile(rf"{_TYPE_PREFIX}{_ATTRIB_NAME}")

# point() / prim() / vertex() / detail() — first attrib argument is a read
_POINT_FN_RE = re.compile(
    r'(?:point|prim|vertex|detail|pointattrib|primattrib|vertexattrib|detailattrib)'
    r'\s*\(\s*[^,]+,\s*"([^"]+)"',
)

# group functions
_GROUP_READ_RE = re.compile(
    r'(?:inpointgroup|inprimgroup|invertexgroup|inedgegroup)'
    r'\s*\(\s*[^,]+,\s*"([^"]+)"',
)
_GROUP_WRITE_RE = re.compile(
    r'(?:setpointgroup|setprimgroup|setvertexgroup|setedgegroup)'
    r'\s*\(\s*[^,]+,\s*"([^"]+)"',
)

# random / rand / nrandom — extract first arg as seed (nrandom: second arg)
_RANDOM_RE = re.compile(r'\brandom\s*\(\s*([^)]+)\)')
_RAND_RE = re.compile(r'\brand\s*\(\s*([^)]+)\)')
_NRANDOM_RE = re.compile(r'\bnrandom\s*\(\s*"[^"]*"\s*,\s*([^)]+)\)')


def analyze_vex(code: str) -> dict:
    """VEX code → {reads, writes, groups_read, groups_write, random_seeds}.

    Each list is sorted and deduplicated.
    """
    writes_set = set()
    reads_set = set()

    # 1. writes (LHS: type@name = ...)
    for m in _WRITE_RE.finditer(code):
        writes_set.add(m.group(1))

    # 2. reads (every type@name occurrence — minus the LHS writes)
    for m in _READ_RE.finditer(code):
        name = m.group(1)
        if name not in writes_set:
            reads_set.add(name)

    # 3. point()/prim()/etc. attribute argument is also a read
    for m in _POINT_FN_RE.finditer(code):
        reads_set.add(m.group(1))

    groups_read_set = set(_GROUP_READ_RE.findall(code))
    groups_write_set = set(_GROUP_WRITE_RE.findall(code))

    random_seeds = []
    for m in _RANDOM_RE.finditer(code):
        random_seeds.append(("random", m.group(1).strip()))
    for m in _RAND_RE.finditer(code):
        random_seeds.append(("rand", m.group(1).strip()))
    for m in _NRANDOM_RE.finditer(code):
        random_seeds.append(("nrandom", m.group(1).strip()))

    return {
        "reads": sorted(reads_set),
        "writes": sorted(writes_set),
        "groups_read": sorted(groups_read_set),
        "groups_write": sorted(groups_write_set),
        "random_seeds": random_seeds,
    }


def count_vex_lines(code: str) -> int:
    """Count non-empty, non-comment lines in VEX code."""
    if not code:
        return 0
    count = 0
    for line in code.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("//"):
            count += 1
    return count
