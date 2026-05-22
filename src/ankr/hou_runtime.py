"""Houdini in-process runtime — chain walk, hashing, HDA walker, BFS, baseline.

Every function here calls `hou` and must execute inside a Houdini session
(typically dispatched by `ankr track` / `ankr sync` via fxhoudinimcp.execute_python).
`hou` is imported lazily inside each function body, so this module is import-safe
from a normal interpreter even though its functions cannot run there.

Provides the Houdini-side primitives that the `ankr track`, `ankr sync`, and
HDA-walker subcommands rely on: subtree/chain-scoped hash computation,
flag introspection, segment enrichment, vendor-HDA black-box gating, the
temp-instance HDA walker, forward BFS for downstream-usage scans, the
single-call `extract_and_dump` aggregator, the `DefaultHouOps` agent-clone
backend, and the cook-level geometry baseline snapshot used by regression
verification. Pure-Python helpers (`is_vendor_hda_namespace`,
`extract_external_refs`) remain `hou`-free so drivers/tests can call them
without a session.
"""


def compute_subtree_hashes(root_path: str) -> dict:
    """Compute (params + vex_code + flags + seed) sha256 for every descendant
    of `root_path`. Returns: {node_path: hash}.

    This must be invoked from within Houdini (e.g., via execute_python MCP tool).
    """
    import hou  # noqa: only available inside Houdini
    import hashlib
    import json

    root = hou.node(root_path)
    if root is None:
        raise ValueError(f"node not found: {root_path}")

    result: dict = {}
    for node in root.allSubChildren():
        info = _serialize_node(node)
        canonical = json.dumps(info, sort_keys=True, separators=(",", ":"), default=str)
        result[node.path()] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return result


def compute_hashes_and_flags_for_paths(paths: list) -> dict:
    """Chain-scoped variant that returns BOTH hash and flags per node, in one
    Houdini call. Returns: {node_path: {"hash": str, "flags": {bypass, lock,
    template, display, render}}}. Paths that don't resolve are skipped.

    Use this in tracking/sync drivers so manifest can persist flag state
    (Plan 2 Task B2 — flags drive used_by ⚠️ rendering and diff detection).
    """
    import hou
    import hashlib
    import json

    result: dict = {}
    for p in paths:
        node = hou.node(p)
        if node is None:
            continue
        info = _serialize_node(node)
        canonical = json.dumps(info, sort_keys=True, separators=(",", ":"), default=str)
        result[p] = {
            "hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "flags": info["flags"],
        }
    return result


def compute_hashes_for_paths(paths: list) -> dict:
    """Compute hashes ONLY for the given node paths. Chain-scoped variant of
    compute_subtree_hashes — avoids walking vendor HDA internals or unused nodes.

    Returns: {node_path: hash}. Paths that don't resolve are silently skipped.
    """
    import hou
    import hashlib
    import json

    result: dict = {}
    for p in paths:
        node = hou.node(p)
        if node is None:
            continue
        info = _serialize_node(node)
        canonical = json.dumps(info, sort_keys=True, separators=(",", ":"), default=str)
        result[p] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return result


# Vendor HDA namespaces — treat as black boxes (Plan 1 + permanent rule per user feedback).
VENDOR_HDA_NAMESPACES = {"sidefx", "labs", "kinefx", "chop"}


def is_vendor_hda(node) -> bool:
    """True if node is an HDA instance from a vendor namespace (SideFX / Labs)."""
    try:
        defn = node.type().definition()
        if defn is None:
            return False
        comps = node.type().nameComponents()
        # comps = (scope, namespace, name, version)
        ns = comps[1] if len(comps) > 1 else ""
        return ns.lower() in VENDOR_HDA_NAMESPACES
    except Exception:
        return False


def _serialize_node(node) -> dict:
    """Extract hash-relevant fields from a hou.Node."""
    import hou
    params: dict = {}
    seed_values: dict = {}
    for parm in node.parms():
        name = parm.name()
        try:
            raw = parm.rawValue() if hasattr(parm, "rawValue") else parm.unexpandedString()
        except Exception:
            raw = None
        if raw and ("$" in str(raw) or "ch(" in str(raw) or "`" in str(raw)):
            params[name] = {"_expression": str(raw)}
        else:
            try:
                params[name] = parm.eval()
            except Exception:
                params[name] = str(raw) if raw is not None else None
        if "seed" in name.lower():
            seed_values[name] = params[name]

    vex_code = ""
    if node.parm("snippet") is not None:
        try:
            vex_code = node.parm("snippet").unexpandedString() or ""
        except Exception:
            vex_code = ""

    def _safe(fn_name):
        fn = getattr(node, fn_name, None)
        if fn is None:
            return False
        try:
            return bool(fn())
        except Exception:
            return False

    flags = {
        "bypass": _safe("isBypassed"),
        "lock": _safe("isHardLocked"),
        "template": _safe("isTemplateFlagSet"),
        "display": _safe("isDisplayFlagSet"),
        "render": _safe("isRenderFlagSet"),
    }

    return {
        "params": params,
        "vex_code": vex_code,
        "flags": flags,
        "seed_values": seed_values,
    }


def extract_segment_nodes(paths: list) -> list:
    """Batch-extract rich info for a list of node paths. One call = full segment data.

    Returns a list of dicts (same order as input), each with:
      {name, type, path, is_hda, hda_type, kind, flags, params_non_default,
       vex_code, runover, reads, writes, groups_read, groups_write, random_seeds}

    `kind` is one of: wrangle, data_transform, passthrough.
    Default-valued params are omitted. Flags only included if non-default (bypass True etc).
    VEX reads/writes/groups/random_seeds are extracted via vex_analyzer when applicable.
    """
    import hou
    try:
        from . import vex_analyzer as va
    except Exception:
        import vex_analyzer as va  # fallback when run standalone

    # --- Houdini parm default detection ---
    def _is_default(parm) -> bool:
        try:
            return parm.isAtDefault()
        except Exception:
            return False

    def _parm_value(parm):
        try:
            raw = parm.rawValue() if hasattr(parm, "rawValue") else parm.unexpandedString()
        except Exception:
            raw = None
        if raw and ("$" in str(raw) or "ch(" in str(raw) or "`" in str(raw)):
            return {"_expression": str(raw)}
        try:
            return parm.eval()
        except Exception:
            return str(raw) if raw is not None else None

    def _node_kind(node) -> str:
        t = node.type().name().lower()
        if "wrangle" in t or t in ("python",):
            return "wrangle"
        if t in ("null", "output"):
            return "passthrough"
        return "data_transform"

    def _flags_nondefault(node) -> dict:
        flags = {}
        # only record flags that are in a non-normal state
        for fn_name, key, default in [
            ("isBypassed", "bypass", False),
            ("isHardLocked", "lock", False),
            ("isTemplateFlagSet", "template", False),
        ]:
            fn = getattr(node, fn_name, None)
            if fn is None:
                continue
            try:
                v = bool(fn())
            except Exception:
                continue
            if v != default:
                flags[key] = v
        return flags

    result: list = []
    for p in paths:
        node = hou.node(p)
        if node is None:
            result.append({"path": p, "error": "not_found"})
            continue

        entry: dict = {
            "name": node.name(),
            "type": node.type().name(),
            "path": p,
            "is_hda": node.type().definition() is not None and node.type().nameComponents()[1] != "",
            "kind": _node_kind(node),
            "flags": _flags_nondefault(node),
        }

        # HDA — black box: just record type + non-default params, skip VEX
        # (user rule: Houdini Labs / SideFX vendor HDAs are handled identically to regular nodes)
        if entry["is_hda"]:
            comps = node.type().nameComponents()
            ns = comps[1] if len(comps) > 1 else ""
            entry["hda_type"] = f"{ns}::{comps[2]}::{comps[3]}" if ns else f"{comps[2]}::{comps[3]}"

        # Non-default params + seed detection
        params_nd: dict = {}
        seeds: list = []
        for parm in node.parms():
            if _is_default(parm):
                # exception: always record seed-related params even if default
                if "seed" not in parm.name().lower():
                    continue
            val = _parm_value(parm)
            params_nd[parm.name()] = val
            if "seed" in parm.name().lower():
                seeds.append({"node": node.name(), "source": f"param: {parm.name()}", "value": val})
        entry["params_non_default"] = params_nd

        # VEX code for wrangles
        if entry["kind"] == "wrangle":
            snip_parm = node.parm("snippet")
            vex_code = ""
            if snip_parm is not None:
                try:
                    vex_code = snip_parm.unexpandedString() or ""
                except Exception:
                    vex_code = ""
            entry["vex_code"] = vex_code
            # runover
            runover_parm = node.parm("class")
            if runover_parm is not None:
                try:
                    ro_map = {0: "Detail", 1: "Primitives", 2: "Points", 3: "Vertices", 4: "Numbers"}
                    entry["runover"] = ro_map.get(runover_parm.eval(), str(runover_parm.eval()))
                except Exception:
                    pass
            # VEX analyze
            if vex_code:
                analyzed = va.analyze_vex(vex_code)
                entry["reads"] = analyzed["reads"]
                entry["writes"] = analyzed["writes"]
                entry["groups_read"] = analyzed["groups_read"]
                entry["groups_write"] = analyzed["groups_write"]
                for src, val in analyzed["random_seeds"]:
                    seeds.append({"node": node.name(), "source": f"vex: {src}()", "value": val})

        entry["random_seeds"] = seeds
        result.append(entry)
    return result


def list_endnode_chain(endnode_path: str, max_depth: int = 10000) -> list:
    """Walk cook chain upstream from `endnode_path`. Return ordered list of dicts:
    [{name, type, path, is_landmark, is_hda, hda_type}].

    Order = upstream → downstream (deepest source first).
    HDA instances are emitted as boundary entries with is_hda=True; their internals
    are NOT walked (Plan 1 treats HDAs as black boxes).
    """
    import hou

    end = hou.node(endnode_path)
    if end is None:
        raise ValueError(f"endnode not found: {endnode_path}")

    visited: set = set()
    ordered: list = []

    def walk(node, depth):
        if depth > max_depth:
            return
        if node.path() in visited:
            return
        visited.add(node.path())
        for inp in node.inputs():
            if inp is not None:
                walk(inp, depth + 1)
        type_name = node.type().name()
        is_hda = node.type().definition() is not None and node.type().nameComponents()[1] != ""
        hda_type = ""
        if is_hda:
            ns, name, ver = node.type().nameComponents()[1:4]
            hda_type = f"{ns}::{name}::{ver}" if ns else f"{name}::{ver}"
        ordered.append({
            "name": node.name(),
            "type": type_name,
            "path": node.path(),
            "is_hda": is_hda,
            "hda_type": hda_type,
        })

    walk(end, 0)
    return ordered


def extract_landmark_inputs(landmark_paths: list[str]) -> dict[str, list[str | None]]:
    """Query Houdini for the actual input connections of landmark nodes.

    For each merge/switch/object_merge landmark, returns the paths of its
    input nodes. Disconnected input slots are represented as None.

    Args:
        landmark_paths: List of absolute Houdini node paths.

    Returns:
        {landmark_path: [input_0_path, input_1_path, ...]}
        Missing/invalid paths are silently skipped.
    """
    import hou

    result: dict[str, list[str | None]] = {}
    for path in landmark_paths:
        node = hou.node(path)
        if node is None:
            continue
        inputs = node.inputs()
        result[path] = [
            inp.path() if inp is not None else None
            for inp in inputs
        ]
    return result


def extract_external_refs(
    landmark_records: list[dict],
    objpath1_by_landmark: dict[str, str],
    chain_paths: set[str],
) -> list[dict]:
    """Identify object_merge landmarks that reference nodes outside the cook chain.

    Pure Python — no ``hou`` dependency. The caller collects ``objpath1``
    parameter values via Houdini and passes them in.

    Parameters
    ----------
    landmark_records:
        Landmark dicts with ``id``, ``path``, ``type``, ``between``.
    objpath1_by_landmark:
        {landmark_path: objpath1_value} for object_merge landmarks.
    chain_paths:
        Set of all node paths in the current cook chain.

    Returns
    -------
    list[dict]
        Each dict: ``landmark_id``, ``landmark_path``, ``source_path``, ``between``.
    """
    results: list[dict] = []
    for lm in landmark_records:
        if lm["type"] not in ("object_merge", "objectmerge"):
            continue
        source = objpath1_by_landmark.get(lm["path"], "")
        if not source:
            continue
        if source in chain_paths:
            continue
        results.append({
            "landmark_id": lm["id"],
            "landmark_path": lm["path"],
            "source_path": source,
            "between": lm.get("between", ""),
        })
    return results


def query_objpath1_for_landmarks(landmark_paths: list[str]) -> dict[str, str]:
    """Query Houdini for the ``objpath1`` parameter of object_merge landmarks.

    Must be called inside a Houdini session (via execute_python).

    Returns:
        {landmark_path: objpath1_value}. Paths without ``objpath1`` are omitted.
    """
    import hou

    result: dict[str, str] = {}
    for path in landmark_paths:
        node = hou.node(path)
        if node is None:
            continue
        parm = node.parm("objpath1")
        if parm is None:
            continue
        try:
            val = parm.eval()
            if val:
                result[path] = val
        except Exception:
            pass
    return result


# ---------- Plan 2 Task C: HDA walker helpers ----------


def is_vendor_hda_namespace(hda_type: str) -> bool:
    """Type-id form (`ns::name::ver`) — namespace-only check.

    Pure-Python (no `hou` needed) so it's reusable from drivers/tests.
    """
    parts = hda_type.split("::")
    return len(parts) >= 3 and parts[0].lower() in VENDOR_HDA_NAMESPACES


def is_vendor_hda_type(node_type) -> bool:
    """hou.NodeType variant — same check via nameComponents()."""
    try:
        comps = node_type.nameComponents()
        ns = comps[1] if len(comps) > 1 else ""
        return ns.lower() in VENDOR_HDA_NAMESPACES
    except Exception:
        return False


def _find_output_type_node(parent_node):
    """Find the first child of parent_node whose type name is 'output'.
    Used as a fallback when displayNode/renderNode are unset.
    """
    for child in parent_node.children():
        if child.type().name() == "output":
            return child
    return None


def _serialize_parm_template(pt) -> dict:
    """Serialize a hou.ParmTemplate to a portable dict for manifest persistence.
    Recurses into Folder templates. Used by walk_hda_definition (O2).
    """
    info: dict = {
        "name": pt.name(),
        "label": pt.label(),
        "type": pt.type().name(),
    }
    try:
        info["num_components"] = pt.numComponents()
    except Exception:
        pass
    try:
        if hasattr(pt, "defaultValue"):
            dv = pt.defaultValue()
            info["default"] = list(dv) if isinstance(dv, tuple) else dv
    except Exception:
        pass
    if pt.type().name() == "Folder":
        try:
            info["children"] = [_serialize_parm_template(c) for c in pt.parmTemplates()]
        except Exception:
            info["children"] = []
    return info


def walk_hda_definition(hda_type: str) -> dict:
    """Walk a user HDA's internal cook chain by spawning a temporary
    unlocked instance, extracting its node graph, then destroying the
    temp container. Houdini-only — must run inside an `hou` session
    (typically via fxhoudinimcp.execute_python).

    Plan 2 Task C §3.

    Returns:
        {
            "hda_type": str,
            "library_file_path": str,
            "modification_time": float,
            "internal_endnode_name": str,
            "chain": [...],                 # HDA-internal relative paths
            "extracted": [...],
            "hashes_with_flags": {...},
            "nested_hdas": [hda_type, ...], # nested USER HDAs found, NOT walked
            "errors": [],
        }
    """
    import hou
    import os
    import time
    import uuid

    # 1. Resolve type
    nt = hou.sopNodeTypeCategory().nodeType(hda_type)
    if nt is None:
        return {
            "hda_type": hda_type,
            "errors": [f"unknown type: {hda_type}"],
        }
    defn = nt.definition()
    if defn is None:
        return {
            "hda_type": hda_type,
            "errors": [f"no definition for: {hda_type}"],
        }
    if is_vendor_hda_type(nt):
        return {
            "hda_type": hda_type,
            "errors": [f"vendor HDA blocked: {hda_type}"],
        }

    lib_path = defn.libraryFilePath()
    try:
        mtime = float(defn.modificationTime() or 0.0)
    except Exception:
        mtime = 0.0
    if mtime == 0.0:
        try:
            mtime = float(os.path.getmtime(lib_path))
        except Exception:
            mtime = 0.0

    # 2. Temp container with collision-resistant tag
    tag = f"hda_walker_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    parent = hou.node("/obj").createNode("geo", tag)
    try:
        parent.setDisplayFlag(False)
    except Exception:
        pass

    # O2: capture HDA spare parm interface from definition (no temp container needed)
    spare_parameters_schema: list = []
    try:
        ptg = defn.parmTemplateGroup()
        for pt in ptg.parmTemplates():
            spare_parameters_schema.append(_serialize_parm_template(pt))
    except Exception:
        pass  # non-fatal — definition may have no parm template group

    result = {
        "hda_type": hda_type,
        "library_file_path": lib_path,
        "modification_time": mtime,
        "spare_parameters_schema": spare_parameters_schema,
        "errors": [],
    }

    try:
        # 3. Instantiate + unlock
        inst = parent.createNode(hda_type, "inst")
        inst.allowEditingOfContents()

        # 4. Find internal endnode (fallback ladder)
        end = inst.displayNode() or inst.renderNode()
        if end is None:
            end = _find_output_type_node(inst)
        if end is None:
            result["errors"].append(
                "no internal endnode (displayNode/renderNode/output type)"
            )
            return result
        result["internal_endnode_name"] = end.name()

        # 5. Walk chain (REUSE Plan 1 functions)
        raw_chain = list_endnode_chain(end.path())

        # 6. Path normalization: strip the temp prefix
        prefix = inst.path() + "/"
        def _strip(p: str) -> str:
            return p[len(prefix):] if p.startswith(prefix) else p

        chain = []
        for n in raw_chain:
            n2 = dict(n)
            n2["path"] = _strip(n2["path"])
            chain.append(n2)
        result["chain"] = chain

        # 7. Hashes/flags + extracted (using TEMP paths, then strip)
        temp_paths = [n["path"] for n in raw_chain]
        hwf_raw = compute_hashes_and_flags_for_paths(temp_paths)
        result["hashes_with_flags"] = {_strip(p): v for p, v in hwf_raw.items()}
        ext_raw = extract_segment_nodes(temp_paths)
        for e in ext_raw:
            if "path" in e:
                e["path"] = _strip(e["path"])
        result["extracted"] = ext_raw

        # 8. Detect nested USER HDAs (don't recurse — deferred)
        result["nested_hdas"] = sorted({
            n["hda_type"] for n in chain
            if n.get("is_hda") and n.get("hda_type")
            and not is_vendor_hda_namespace(n["hda_type"])
        })
    except Exception as e:
        result["errors"].append(
            f"walker exception: {type(e).__name__}: {e}"
        )
    finally:
        # 9. ALWAYS clean up temp container
        try:
            parent.destroy()
        except Exception:
            pass

    return result


# ---------- Forward BFS — terminal detection & boundary-aware traversal ----------


def forward_bfs_from(start_node, scope: str,
                     include_logical_terminals: bool = True) -> dict:
    """Downstream BFS from a start node. Returns a tree dict.

    Terminals:
        - display_flag True         (logical; gated by include_logical_terminals)
        - node type is 'output'     (logical; gated by include_logical_terminals)
        - no outputs()              (physical; always terminal)
        - boundary (for sop scope: exits /obj/<geo>; for hda_internal: exits HDA)

    `include_logical_terminals=False` lets the walk continue past display-
    flagged or `output`-type nodes, reaching everything that is physically
    wired downstream. That matters for downstream-usage scans (e.g. the
    external-consumption filter), where a display flag is merely UI state
    and does not imply the data pipeline ends there.

    HDA instances are treated as single nodes (black-box at BFS level);
    consume scanning handles their internals separately.

    Plan task A2. See spec §4.
    """
    nodes: dict[str, dict] = {}
    edges: list[tuple[str, str, int]] = []
    visit_order: list[str] = []
    external_refs: list[dict] = []

    start_path = start_node.path()
    start_boundary = _scope_boundary_path(start_node, scope)

    def classify_terminal(node) -> tuple[bool, str]:
        if include_logical_terminals:
            try:
                if node.isDisplayFlagSet():
                    return True, "display_flag"
            except Exception:
                pass
            try:
                if node.type().name() == "output":
                    return True, "output_node"
            except Exception:
                pass
        if not node.outputs():
            return True, "leaf_no_outputs"
        return False, ""

    queue = [start_node]
    while queue:
        node = queue.pop(0)
        path = node.path()
        if path in nodes:
            continue
        visit_order.append(path)
        is_term, reason = classify_terminal(node)
        # The start node is the user's explicit BFS root. Logical terminals
        # (display_flag, output_node) must NOT cut the walk off at the start
        # — users commonly pick the display node as the starting point and
        # we still need to traverse downstream. Physical terminals
        # (leaf_no_outputs) remain honored because there is literally
        # nothing to expand.
        if path == start_path and reason in ("display_flag", "output_node"):
            is_term, reason = False, ""
        try:
            ntype_name = node.type().name()
        except Exception:
            ntype_name = "unknown"
        is_hda = False
        vendor = False
        hda_type = ""
        try:
            defn = node.type().definition()
            if defn is not None:
                is_hda = True
                hda_type = node.type().name()
                vendor = is_vendor_hda_type(node.type())
        except Exception:
            pass
        nodes[path] = {
            "type": ntype_name,
            "is_terminal": is_term,
            "terminal_reason": reason,
            "is_hda": is_hda,
            "hda_type": hda_type,
            "vendor": vendor,
        }
        if is_term:
            continue
        for idx, out in enumerate(node.outputs() or []):
            if not _within_boundary(out, start_boundary, scope):
                external_refs.append({
                    "from": path, "to": out.path(),
                    "reason": "boundary_cross",
                })
                continue
            edges.append((path, out.path(), idx))
            queue.append(out)

    return {
        "start": start_path,
        "scope": scope,
        "nodes": nodes,
        "edges": edges,
        "external_refs": external_refs,
        "visit_order": visit_order,
    }


def _scope_boundary_path(start_node, scope: str) -> str:
    """The container path a BFS must stay inside."""
    parent = start_node.parent()
    return parent.path()


def _within_boundary(node, boundary_path: str, scope: str) -> bool:
    """True if `node` is inside (or equal to) `boundary_path` subtree."""
    p = node.path()
    return p == boundary_path or p.startswith(boundary_path + "/")


# ---------- Single-call MCP extraction ----------


def extract_and_dump(endnode_path: str, temp_dir: str) -> dict:
    """Combine chain walk, segment extraction, and hash computation into one
    call.  Writes four JSON files to *temp_dir* and returns a lightweight
    summary dict (no bulk data).

    Files written:
        chain.json              – list_endnode_chain result
        segments_enriched.json  – extract_segment_nodes result
        hashes_with_flags.json  – compute_hashes_and_flags_for_paths result
        scene_meta.json         – hipname / hipfile / houdini version

    Returns:
        {status, node_count, segment_count, endnode_name, hipname, hda_deps}
    """
    import hou  # noqa: only available inside Houdini
    import json
    import os

    from .hipname import hip_to_folder

    # 1. Chain
    chain = list_endnode_chain(endnode_path)
    chain_path = os.path.join(temp_dir, "chain.json")
    with open(chain_path, "w", encoding="utf-8") as f:
        json.dump(chain, f, ensure_ascii=False, indent=2)

    # 2. Segments — enrich all nodes, then chunk into segmented format
    from .chunking import is_landmark_type as _is_lm
    paths = [n["path"] for n in chain]
    flat_enriched = extract_segment_nodes(paths)
    flat_by_path = {n["path"]: n for n in flat_enriched}

    # Split chain into runs by landmarks
    runs: list[list[dict]] = []
    current_run: list[dict] = []
    for n in chain:
        if _is_lm(n["type"]):
            if current_run:
                runs.append(current_run)
                current_run = []
        else:
            current_run.append(n)
    if current_run:
        runs.append(current_run)

    segments: list[dict] = []
    for i, run in enumerate(runs):
        first_name = run[0]["name"] if run else f"run{i}"
        seg_id = f"seg_{i+1:02d}_{first_name}"
        nodes_enriched = [flat_by_path[n["path"]] for n in run if n["path"] in flat_by_path]
        segments.append({
            "seg_num": i + 1,
            "seg_id": seg_id,
            "endnode": endnode_path,
            "nodes": nodes_enriched,
        })

    seg_path = os.path.join(temp_dir, "segments_enriched.json")
    with open(seg_path, "w", encoding="utf-8") as f:
        json.dump(segments, f, ensure_ascii=False, indent=2)

    # 3. Hashes + flags
    hashes = compute_hashes_and_flags_for_paths(paths)
    hash_path = os.path.join(temp_dir, "hashes_with_flags.json")
    with open(hash_path, "w", encoding="utf-8") as f:
        json.dump(hashes, f, ensure_ascii=False, indent=2)

    # 4. Scene meta
    hipfile_current = hou.hipFile.name()
    hipfile_path = hou.hipFile.path()
    houdini_version = hou.applicationVersionString()
    hipname = hip_to_folder(hipfile_current)

    scene_meta = {
        "hipname": hipname,
        "hipfile_current": hipfile_current,
        "hipfile_path": hipfile_path,
        "houdini_version": houdini_version,
    }
    meta_path = os.path.join(temp_dir, "scene_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(scene_meta, f, ensure_ascii=False, indent=2)

    # 5. Landmark inputs for cross-segment ref analysis
    landmark_paths = [n["path"] for n in chain if _is_lm(n["type"])]
    landmark_inputs = extract_landmark_inputs(landmark_paths)
    li_path = os.path.join(temp_dir, "landmark_inputs.json")
    with open(li_path, "w", encoding="utf-8") as f:
        json.dump(landmark_inputs, f, ensure_ascii=False, indent=2)

    # 6. objpath1 for external refs (object_merge → outside chain)
    merge_paths = [n["path"] for n in chain if n["type"] in ("object_merge", "objectmerge")]
    objpath1_map = query_objpath1_for_landmarks(merge_paths)
    op_path = os.path.join(temp_dir, "objpath1.json")
    with open(op_path, "w", encoding="utf-8") as f:
        json.dump(objpath1_map, f, ensure_ascii=False, indent=2)

    # 7. Summary (no bulk data)
    endnode_name = chain[-1]["name"] if chain else ""
    hda_deps = sorted({
        n.get("hda_type", "") for n in chain if n.get("is_hda")
    } - {""})

    return {
        "status": "ok",
        "node_count": len(chain),
        "segment_count": len(segments),
        "endnode_name": endnode_name,
        "hipname": hipname,
        "hda_deps": hda_deps,
        "landmark_input_count": len(landmark_inputs),
        "objpath1_count": len(objpath1_map),
    }


# ============================================================================
# Phase C: Real HouOps implementation for HDA agent clone.
# ============================================================================
def _lookup_hda_node_type(hda_type: str):
    """Resolve an HDA type name across node categories. `hou.nodeType(name)`
    alone returns None for category-scoped types like
    `blueitems::KJI_OffsetExtrude::1.2`; category-aware lookup is required.
    """
    import hou
    for cat in (
        hou.sopNodeTypeCategory(),
        hou.objNodeTypeCategory(),
        hou.dopNodeTypeCategory(),
        hou.lopNodeTypeCategory(),
        hou.ropNodeTypeCategory(),
        hou.chopNodeTypeCategory(),
        hou.cop2NodeTypeCategory(),
    ):
        nt = cat.nodeType(hda_type)
        if nt is not None:
            return nt
    return hou.nodeType(hda_type)


class DefaultHouOps:
    """Production HouOps — wraps hou.* APIs. Only usable inside Houdini session."""

    def get_source_signature(self, hda_type: str) -> dict:
        nt = _lookup_hda_node_type(hda_type)
        if nt is None:
            raise RuntimeError(f"hou.nodeType({hda_type!r}) → None")
        defn = nt.definition()
        if defn is None:
            raise RuntimeError(f"No definition for {hda_type}")
        return self._read_signature_from_defn(defn)

    def copy_definition(self, source_hda_type: str, new_otl_path,
                        new_name: str, new_menu_name: str) -> None:
        nt = _lookup_hda_node_type(source_hda_type)
        if nt is None:
            raise RuntimeError(f"hou.nodeType({source_hda_type!r}) → None")
        defn = nt.definition()
        if defn is None:
            raise RuntimeError(f"No definition for {source_hda_type}")
        from pathlib import Path
        new_otl_path = Path(new_otl_path)
        defn.copyToHDAFile(
            str(new_otl_path),
            new_name=new_name,
            new_menu_name=new_menu_name,
        )

    def install(self, otl_path) -> None:
        import hou
        hou.hda.installFile(str(otl_path))

    def get_agent_signature(self, agent_hda_type: str) -> dict:
        nt = _lookup_hda_node_type(agent_hda_type)
        if nt is None:
            raise RuntimeError(f"agent node type not found: {agent_hda_type}")
        defn = nt.definition()
        if defn is None:
            raise RuntimeError(f"No definition for agent {agent_hda_type}")
        return self._read_signature_from_defn(defn)

    def discover_agent_type_in_otl(self, otl_path) -> str:
        """Read the first definition from the installed OTL and return its
        fully-qualified nodeTypeName. Lets callers reconcile the predicted
        agent type with whatever `copyToHDAFile` actually produced."""
        import hou
        defs = hou.hda.definitionsInFile(str(otl_path))
        if not defs:
            raise RuntimeError(f"No definitions found in OTL: {otl_path}")
        return defs[0].nodeTypeName()

    def uninstall(self, otl_path) -> None:
        import hou
        try:
            hou.hda.uninstallFile(str(otl_path))
        except Exception:
            pass  # already-uninstalled is OK

    @staticmethod
    def _read_signature_from_defn(defn) -> dict:
        """Extract {inputs, outputs, spare_parms} from a hou.HDADefinition."""
        nt = defn.nodeType()
        try:
            input_types = list(nt.inputDataTypes())
        except Exception:
            input_types = []
        try:
            output_types = list(nt.outputDataTypes())
        except Exception:
            output_types = []
        inputs = [input_types[i] if i < len(input_types) else ""
                  for i in range(nt.maxNumInputs())]
        outputs = [output_types[i] if i < len(output_types) else ""
                   for i in range(nt.maxNumOutputs())]
        spare_parms = []
        for parm_tpl in defn.parmTemplateGroup().parmTemplates():
            spare_parms.append({
                "name": parm_tpl.name(),
                "type": str(parm_tpl.type()).rsplit(".", 1)[-1],
                "default": _safe_default_value(parm_tpl),
            })
        return {"inputs": inputs, "outputs": outputs, "spare_parms": spare_parms}


def _safe_default_value(parm_tpl):
    try:
        dv = parm_tpl.defaultValue()
        if isinstance(dv, (tuple, list)) and len(dv) == 1:
            return dv[0]
        return dv
    except Exception:
        return None


# ---------- R-5: Geometry baseline snapshot (cook-level regression guard) ----------


def _snapshot_geometry(geo) -> dict:
    """Extract comparable structure + value statistics from a hou.Geometry.

    Returns a JSON-safe dict with point/prim counts, attribute schema, group
    schema, and per-attribute numeric statistics (min/max/mean/stddev). Strings
    and non-numeric attribs record only schema + unique count.
    """
    import hou  # noqa

    def _attr_schema(a):
        try:
            dt = str(a.dataType()).rsplit(".", 1)[-1]
        except Exception:
            dt = "?"
        try:
            size = a.size()
        except Exception:
            size = 0
        return {"name": a.name(), "dtype": dt, "size": size}

    def _numeric_stats(values, size):
        if not values:
            return None
        n = len(values)
        if size <= 1:
            flat = [float(v) for v in values if v is not None]
        else:
            flat = []
            for v in values:
                if v is None:
                    continue
                try:
                    flat.extend(float(x) for x in v)
                except Exception:
                    pass
        if not flat:
            return None
        mn = min(flat)
        mx = max(flat)
        mean = sum(flat) / len(flat)
        var = sum((x - mean) ** 2 for x in flat) / len(flat)
        return {
            "count": n,
            "elements": len(flat),
            "min": mn,
            "max": mx,
            "mean": mean,
            "stddev": var ** 0.5,
        }

    def _collect(owner_name, attribs, entities):
        schema = []
        stats = {}
        for a in attribs:
            sch = _attr_schema(a)
            schema.append(sch)
            if sch["dtype"] in ("Int", "Float"):
                try:
                    vals = [e.attribValue(a.name()) for e in entities]
                except Exception:
                    vals = []
                s = _numeric_stats(vals, sch["size"])
                if s is not None:
                    stats[a.name()] = s
            elif sch["dtype"] == "String":
                try:
                    uniq = {e.attribValue(a.name()) for e in entities}
                    stats[a.name()] = {"unique_count": len(uniq)}
                except Exception:
                    pass
        return schema, stats

    info = {
        "npoints": len(geo.points()),
        "nprims": len(geo.prims()),
        "attribs": {},
        "attrib_stats": {},
        "groups": {},
    }
    point_schema, point_stats = _collect("point", geo.pointAttribs(), geo.points())
    prim_schema, prim_stats = _collect("prim", geo.primAttribs(), geo.prims())
    vtx_schema, vtx_stats = _collect("vertex", geo.vertexAttribs(), [])
    info["attribs"]["point"] = point_schema
    info["attribs"]["prim"] = prim_schema
    info["attribs"]["vertex"] = vtx_schema
    info["attribs"]["global"] = [_attr_schema(a) for a in geo.globalAttribs()]
    info["attrib_stats"]["point"] = point_stats
    info["attrib_stats"]["prim"] = prim_stats
    info["attrib_stats"]["vertex"] = vtx_stats
    info["groups"]["point"] = [
        {"name": g.name(), "count": len(g.points())} for g in geo.pointGroups()
    ]
    info["groups"]["prim"] = [
        {"name": g.name(), "count": len(g.prims())} for g in geo.primGroups()
    ]
    try:
        info["groups"]["edge"] = [
            {"name": g.name()} for g in geo.edgeGroups()
        ]
    except Exception:
        info["groups"]["edge"] = []
    return info


def baseline_capture_batch(samples: list[dict], strict_hash: bool = False) -> list[dict]:
    """Capture current node geometry + load baseline bgeo, return snapshot pairs.

    Each sample:
        {"name": str, "node_path": str, "baseline_bgeo": str}

    Returns per sample:
        {"name", "node_path", "baseline_bgeo",
         "current": snapshot_dict,
         "baseline": snapshot_dict,
         "errors": [str, ...]}

    Read-only — does not modify the hip. `strict_hash` is accepted for future
    L3 full-data hashing; currently ignored.
    """
    import hou  # noqa

    out: list[dict] = []
    for s in samples:
        entry = {
            "name": s.get("name", ""),
            "node_path": s.get("node_path", ""),
            "baseline_bgeo": s.get("baseline_bgeo", ""),
            "errors": [],
        }
        # Current geo from node
        try:
            node = hou.node(s["node_path"])
            if node is None:
                entry["errors"].append(f"node not found: {s['node_path']}")
            else:
                cur_geo = node.geometry()
                if cur_geo is None:
                    entry["errors"].append("node.geometry() is None — not a SOP?")
                else:
                    entry["current"] = _snapshot_geometry(cur_geo)
        except Exception as e:
            entry["errors"].append(f"current snapshot exception: {type(e).__name__}: {e}")

        # Baseline from bgeo file
        try:
            base_geo = hou.Geometry()
            base_geo.loadFromFile(s["baseline_bgeo"])
            entry["baseline"] = _snapshot_geometry(base_geo)
        except Exception as e:
            entry["errors"].append(f"baseline load exception: {type(e).__name__}: {e}")

        out.append(entry)
    return out
