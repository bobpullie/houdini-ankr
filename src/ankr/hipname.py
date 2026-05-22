"""hip filename → folder name conversion. Strips version indices.

Used by the hip-workflow subcommands (`ankr track`, `ankr sync`) to map a
versioned `.hip` filename (`KJI_Kr_House_v023.hip`) to a stable directory
name under the KB (`KJI_Kr_House/`). Pure-Python, no Houdini deps.
"""

from __future__ import annotations

import os
import re

# Matched in order of priority:
# 1. _v\d+       → _v023
# 2. _\d{3,}     → _001  (3+ digits to avoid stripping meaningful short suffixes)
_VERSION_PATTERNS = [
    re.compile(r"_v\d+$"),
    re.compile(r"_\d{3,}$"),
]

_HIP_EXTENSIONS = (".hip", ".hipnc", ".hiplc")


def hip_to_folder(hipfile: str) -> str:
    """hip filename/path → stable folder name (strips trailing version index)."""
    name = os.path.basename(hipfile)
    for ext in _HIP_EXTENSIONS:
        if name.endswith(ext):
            name = name[: -len(ext)]
            break
    for pat in _VERSION_PATTERNS:
        m = pat.search(name)
        if m:
            return name[: m.start()]
    return name
