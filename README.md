# houdini-ankr

**ANKR — Agent Network Knowledge Reader.**
A canonical [Claude Code](https://claude.com/claude-code) plugin that converts SideFX Houdini networks into a hierarchical Markdown **knowledge base** an AI agent can reliably read, query, and keep in sync — without ever mutating the scene.

> Status: **alpha**, Phase 1.6 (CLI unification). Public surface unstable until v0.1.0.

---

## Why ANKR?

A Houdini `.hip` file is *opaque* to an LLM:
- Vendor HDAs (`sidefx::`, `labs::`, `kinefx::`) are black boxes.
- Parameter graphs are wide; cook chains are deep.
- Reloading a hip file just to answer "what does this endnode do?" is wasteful — and dangerous, because most agent runtimes can also save and mutate.

**ANKR solves this by extracting once, reading forever.** A Houdini-side runtime (`hou_runtime.py`) walks the cook chain of a target endnode, dumps structural JSON to a temp dir, and a host-side CLI (`ankr track`) materializes that into a fixed, human-readable directory layout. Re-syncing is a hash-diff against the existing markdown — only changed segments are rewritten.

The result is a folder you `git commit` and an agent reads with plain file I/O.

---

## The knowledge-base layout (5 levels)

For every tracked endnode, ANKR produces:

```
docs/ankr/
└── <hipname>/                       # e.g. MyHipScene/
    └── <endnode>/                   # e.g. OUT_endnode/
        ├── card.md                  # L0 — one-paragraph executive summary
        ├── skeleton.md              # L1 — chain overview, segment index, frontmatter
        ├── dataflow.md              # L1.5 — attribute/group lifecycle across segments
        ├── used_by.md               # back-references (who reads this endnode)
        ├── segments/
        │   ├── seg_01_<title>.md    # L2 — node-by-node detail for one chain segment
        │   ├── seg_02_<title>.md
        │   └── ...
        └── manifest.yaml            # L3 — machine-readable inventory (HDAs only by default)
```

And separately, for every custom HDA encountered:

```
docs/ankr/custom_hda/
└── <namespace>__<name>__<version>/   # e.g. mystudio__MyCustomHDA__1.0/
    ├── card.md  skeleton.md  dataflow.md  used_by.md
    ├── segments/seg_*.md
    └── manifest.yaml                 # required (I3 invariant)
```

The level hierarchy is the contract:

| Level | File | Purpose | Typical size |
|-------|------|---------|--------------|
| **L0** | `card.md` | "What is this in one paragraph?" — agent's first read | ≤ 60 lines |
| **L1** | `skeleton.md` | Chain map + segment table + frontmatter (`endnode`, `last_sync`, `segment_count`, …) | ≤ 300 lines |
| **L1.5** | `dataflow.md` | Cross-segment attribute / group / vex symbol flow | ≤ 600 lines |
| **L2** | `segments/seg_NN_*.md` | Per-segment narrative + node parameters (Haiku-generated) | ≤ 800 lines |
| **L3** | `manifest.yaml` | Inventory: HDAs used, internal segments, lock-file fields | n/a |
| — | `used_by.md` | Reverse-index of who reads this unit | ≤ 200 lines |

`ankr check` (see [Invariants](#topology-invariants-i1i10)) verifies the layout never drifts from this contract.

---

## Install

```bash
# inside the canonical plugin repo
pip install -e .

# verify
ankr version             # → houdini-ankr 0.1.0a0
ankr --help              # → init | install-to-houdini | track | check | version
```

For a project that uses ANKR, you typically also install the runtime side into Houdini so the in-Houdini extractor (`hou_runtime.py`) is importable from `hou`'s Python session:

```bash
cd <your-houdini-project>
ankr init                                   # scaffolds ankr.config.yaml (interactive)
# edit ankr.config.yaml — fill houdini.user_libs_dir
ankr install-to-houdini --force             # copies ankr/ into Houdini's python3.11libs/
```

---

## Quick start (canonical workflow)

### 1. Scaffold config

```bash
cd /path/to/your/houdini-project
ankr init
# OR re-run on an existing config without clobbering hand edits:
ankr init --repair --no-interactive
```

Hand-edit `ankr.config.yaml` so `houdini.user_libs_dir` points at your Houdini user prefs python libs dir, e.g.:

```yaml
houdini:
  install_root: null
  user_libs_dir: C:/Users/<you>/Documents/houdini21.0/python3.11libs
  version_hint: '21.0'
```

### 2. Push the plugin into Houdini

```bash
ankr install-to-houdini --force
```

This copies `ankr/` into the directory above so `hou_runtime` is importable from inside Houdini's Python.

### 3. From inside Houdini, dump the endnode

```python
# in Houdini's Python source editor (read-only — no scene mutation)
from ankr.hou_runtime import extract_and_dump

extract_and_dump(
    endnode_path="/obj/MY_GEO/OUT_endnode",
    temp_dir="C:/Users/<you>/AppData/Local/Temp/ankr_dump",
    prefix="",  # optional
)
```

This produces four JSON files (`chain.json`, `segments_enriched.json`, `narratives.json`, `hashes.json`) plus optional `landmark_inputs.json`, `objpath1.json`, `hda_mtimes.json`.

### 4. Materialize the markdown KB

```bash
ankr track \
  --endnode "/obj/MY_GEO/OUT_endnode" \
  --hipname "MyHipScene" \
  --hip-current "MyHipScene_v003.hiplc" \
  --temp "C:/Users/<you>/AppData/Local/Temp/ankr_dump"
```

Output:

```
manifest mode: <create|incremental|reseat>
out dir:       <docs_root>/MyHipScene/OUT_endnode/
segments:      <N>
used_by:       <K>

--- commit bundle (run from docs_root) ---
  git add ...
  git commit -m "..."

--- HDA cache report ---
  ✓ mystudio::MyCustomHDA::1.0 [fresh]
  ⚠ mystudio::OtherHDA::2.1 [stale]
```

### 5. Verify topology

```bash
ankr check
# → docs_root: …
#   units: N (X hip, Y hda)
#   ✓ no violations
```

---

## Command reference

| Command | Purpose |
|---------|---------|
| `ankr version` | Print the plugin version. |
| `ankr init [--repair\|--force] [--no-interactive] [-n NAME] [-d DOCS_ROOT] [--houdini-version 21.0]` | Scaffold or repair `ankr.config.yaml`. `--repair` preserves hand-edited keys; `--force` overwrites the file outright. They are mutually exclusive. |
| `ankr install-to-houdini [--dry-run] [--force] [-c CONFIG]` | Copy the `ankr/` package into `houdini.user_libs_dir/ankr/`. `--dry-run` lists files without writing. |
| `ankr track --endnode … --hipname … --hip-current … --temp … [--prefix …] [--hip-path …] [--hou-version …] [--hda-mtimes-file …] [-c CONFIG]` | Materialize the KB from JSON dumps produced inside Houdini. First-track creates; re-track diffs and rewrites only changed segments. |
| `ankr check [--json] [-c CONFIG]` | Run topology invariants I1~I10 over the configured KB. Exit `0` if no critical violations, `1` otherwise. Warnings never change the exit code. |

All commands resolve `ankr.config.yaml` by walking up from the current working directory, or honor `-c <path>` if you need to override.

---

## Configuration (`ankr.config.yaml`)

```yaml
ankr_version: "0.1.0"

project:
  name: my-houdini-project    # arbitrary label
  root: ${ANKR_PROJECT_ROOT}  # MUST resolve to an absolute path; `${VAR}` is expanded

docs:
  root: docs/ankr             # KB root (relative → resolved against project.root)
  hip_subdir: ""              # "" = <docs.root>/<hipname>/<endnode>/   (legacy layout, depth 2)
                              # "X" = <docs.root>/X/<hipname>/<endnode>/ (depth 3)
  hda_subdir: custom_hda      # HDA units live at <docs.root>/<hda_subdir>/<safe_id>/
  deadflow_reports_subdir: deadflow_reports
  logs_subdir: logs

houdini:
  install_root: null          # null = auto-detect via HFS (best effort)
  user_libs_dir: null         # null = derive from OS + version_hint; SET THIS for `install-to-houdini`
  version_hint: null          # informational only (e.g. "21.0"); never used as a path literal

hda_search_paths: []          # additional .hda dirs (absolute or relative to project.root)

logging:
  dir: logs/ankr
  level: INFO                 # DEBUG | INFO | WARNING | ERROR

rule_store:                   # OPTIONAL Phase 3 hook — keep null unless you wire an adapter
  kind: null                  # null → NullRuleStore (no-op)
  config: {}

hooks:                        # Phase 2 feature flags
  enable_drift_reminder: true
  enable_session_end_check: true
```

**`${VAR}` expansion:** any `${NAME}` in a string value is replaced by `os.environ["NAME"]` at load time. This is the canonical way to keep machine-specific paths (like `project.root` or `houdini.user_libs_dir`) out of version control.

**Hand-editing is safe.** `ankr init --repair` walks the existing YAML and only overwrites keys you explicitly passed on the command line; everything else is preserved verbatim.

---

## Topology invariants (I1~I10)

`ankr check` enforces ten structural invariants over the KB. Severities: **critical** (exit 1) or **warning** (exit 0).

| ID | Severity | Rule |
|----|----------|------|
| **I1** | critical | Every tracked unit has exactly one `skeleton.md`. |
| **I2** | critical | No segment file lives without a sibling `skeleton.md` in its parent dir. |
| **I3** | critical | Every HDA unit carries a `manifest.yaml`. (Hip units may omit it.) |
| **I4** | critical | If `skeleton.md` declares `segment_count: N` in frontmatter, exactly `N` segment files exist. |
| **I5** | warning | Soft size caps: card ≤ 60, skeleton ≤ 300, dataflow ≤ 600, segment ≤ 800, used_by ≤ 200 lines; manifest threshold separate. |
| **I6** | (deferred) | dataflow.md cited attribs/groups appear in at least one segment. Reserved; not yet enforced. |
| **I7** | critical | HDA `manifest.yaml`'s `internal_segments:` list length equals `segments/` file count. |
| **I8** | critical | Required frontmatter keys present: `endnode`, `last_sync` on skeletons; `segment_id` on segments. |
| **I9** | critical | Path layout matches config: hip endnodes at the configured depth; HDA units under `<hda_subdir>/<safe_id>/`. |
| **I10** | (deferred) | `used_by.md` cited hip paths still resolve. Awaits git-history awareness. |

Use `--json` for machine-readable output suitable for CI gating.

---

## Design principles (load-bearing — do not violate)

1. **Zero coupling to external memory systems.** ANKR is self-contained. An optional `RuleStore` Protocol exists for opt-in integration with a project's own memory system, but the default is `NullRuleStore` and nothing requires wiring.
2. **Read-only on Houdini scenes.** Never `save_scene`, never `execute_python` that mutates nodes, never enter vendor HDAs (`sidefx::`, `labs::`, `kinefx::`). The one historical carve-out is `walk_hda_definition`, which restores Houdini's hip-dirty flag after introspection so the scene state is bit-identical to its pre-call form.
3. **Single CLI surface: `ankr <subcommand>`.** All workflows go through one entrypoint (rolled out incrementally Phase 1+).

---

## What's in the box

```
src/ankr/
├── cli.py                  # `ankr` entrypoint (Typer)
├── commands/
│   ├── install_to_houdini.py
│   └── track.py
├── drivers/
│   ├── _card.py            # L0 card builder
│   ├── _hip.py             # first-track + sync for hip endnodes
│   ├── _helpers.py
│   └── _shared_steps.py
├── hou_runtime.py          # Houdini-side extractor (only file that imports `hou`)
├── config.py               # pydantic schema + ${VAR} expansion + YAML loader
├── topology.py             # I1~I10 invariants + KB scanner
├── paths.py                # docs_root / hda_docs_dir / houdini_user_libs_dir
├── card.py  skeleton (via drivers)  dataflow.py  used_by.py  manifest.py
├── chunking.py             # segment-boundary detection (≤ 800-line caps)
├── markdown_gen.py         # frontmatter writer + safe markdown emission
├── node_hash.py            # chain-based hashing (drives incremental sync)
├── hipname.py              # safe filename derivation
├── hda_cache.py            # fresh/stale/missing accounting per HDA
├── cross_refs.py  used_by.py
├── vex_analyzer.py         # VEX symbol scraping
├── tag_vocabulary.py
└── rule_store/             # optional Protocol for external memory integration
```

The current canonical port is **27 .py files, 271/271 tests green** as of commit `492e976` (Session 49 audit).

---

## Status & roadmap

ANKR ports an in-tree predecessor into a canonical package. The migration is phased; current public surface and gates are tracked in the parent project's task atlas, which is the source of truth for "where are we and where are we going". This README covers stable user-facing behavior only.

---

## License

MIT.

---

# 한글 설명

## ANKR란?

**ANKR(Agent Network Knowledge Reader, "앵커")는 SideFX Houdini 네트워크를 AI 에이전트가 읽을 수 있는 계층적 마크다운 지식 베이스로 변환하는 Claude Code 플러그인**입니다. hip 파일 자체는 LLM 입장에서 불투명한 블랙박스 — 벤더 HDA는 내부를 못 들여다보고, 쿡 체인은 깊고 넓으며, hip을 다시 열어 "이 엔드노드가 뭐하는 거지?"를 묻는 건 비효율적이고 위험합니다(쓰기 가능한 런타임은 실수로 씬을 수정할 수 있음).

**ANKR의 해법: 한 번 추출하고 영원히 읽는다.** Houdini 안에서 도는 런타임 `hou_runtime.py`가 대상 엔드노드의 쿡 체인을 워크하면서 구조 정보를 JSON으로 temp에 덤프하고, 호스트(Houdini 바깥) Python의 CLI `ankr track`이 이를 고정된 디렉터리 레이아웃으로 머터리얼라이즈합니다. 재싱크는 마크다운과의 해시 차이만 비교 — **바뀐 세그먼트만 다시 씀**. 결과물은 `git commit` 가능한 폴더이고, 에이전트는 평범한 파일 I/O로 읽기만 합니다.

## 지식 베이스 5단계 구조

추적된 엔드노드마다 다음이 생성됩니다:

```
docs/ankr/
└── <hipname>/                       # 예: MyHipScene/
    └── <endnode>/                   # 예: OUT_endnode/
        ├── card.md                  # L0 — 한 단락 요약
        ├── skeleton.md              # L1 — 체인 개요 + 세그먼트 인덱스 + frontmatter
        ├── dataflow.md              # L1.5 — 세그먼트 간 attribute/group 흐름
        ├── used_by.md               # 역참조 (누가 이 엔드노드를 읽는지)
        ├── segments/
        │   ├── seg_01_<title>.md    # L2 — 한 세그먼트 노드별 상세
        │   └── ...
        └── manifest.yaml            # L3 — 머신 가독 인벤토리 (HDA는 필수)
```

| 레벨 | 파일 | 역할 | 권장 크기 |
|------|------|------|----------|
| **L0** | `card.md` | "이게 한 단락으로 뭐임?" — 에이전트 첫 읽기 | ≤ 60줄 |
| **L1** | `skeleton.md` | 체인 맵 + 세그먼트 테이블 + frontmatter | ≤ 300줄 |
| **L1.5** | `dataflow.md` | 세그먼트 횡단 어트리뷰트/그룹/vex 흐름 | ≤ 600줄 |
| **L2** | `segments/seg_NN_*.md` | 세그먼트별 내러티브 + 파라미터 (Haiku 생성) | ≤ 800줄 |
| **L3** | `manifest.yaml` | HDA/세그먼트/락 인벤토리 | — |
| — | `used_by.md` | 역참조 인덱스 | ≤ 200줄 |

## 설치

```bash
# 캐노니컬 플러그인 repo에서
pip install -e .
ankr version             # → houdini-ankr 0.1.0a0
ankr --help              # → init | install-to-houdini | track | check | version
```

프로젝트에서 사용할 때:

```bash
cd <당신의-houdini-프로젝트>
ankr init                            # ankr.config.yaml 스캐폴드 (인터랙티브)
# ankr.config.yaml 손편집 — houdini.user_libs_dir 설정
ankr install-to-houdini --force      # Houdini의 python3.11libs/에 ankr/ 복사
```

## 표준 워크플로우

### 1단계 — config 스캐폴드

```bash
cd /path/to/your/houdini-project
ankr init
# 또는 기존 config를 보존하면서 재실행:
ankr init --repair --no-interactive
```

`ankr.config.yaml`을 손편집해서 `houdini.user_libs_dir`를 본인 Houdini 사용자 환경의 python libs 디렉터리로 지정:

```yaml
houdini:
  install_root: null
  user_libs_dir: C:/Users/<당신>/Documents/houdini21.0/python3.11libs
  version_hint: '21.0'
```

### 2단계 — Houdini에 플러그인 푸시

```bash
ankr install-to-houdini --force
```

### 3단계 — Houdini 안에서 엔드노드 덤프 (읽기 전용)

```python
# Houdini Python source editor에서 (씬 변경 없음)
from ankr.hou_runtime import extract_and_dump

extract_and_dump(
    endnode_path="/obj/MY_GEO/OUT_endnode",
    temp_dir="C:/Users/<당신>/AppData/Local/Temp/ankr_dump",
    prefix="",
)
```

4개 JSON 파일(`chain.json`, `segments_enriched.json`, `narratives.json`, `hashes.json`) + 선택적으로 `landmark_inputs.json`, `objpath1.json`, `hda_mtimes.json`이 생성됩니다.

### 4단계 — 마크다운 KB 머터리얼라이즈

```bash
ankr track \
  --endnode "/obj/MY_GEO/OUT_endnode" \
  --hipname "MyHipScene" \
  --hip-current "MyHipScene_v003.hiplc" \
  --temp "C:/Users/<당신>/AppData/Local/Temp/ankr_dump"
```

> **⚠ Git Bash 사용 시 주의:** `--endnode "/obj/..."` 처럼 슬래시로 시작하는 인자는 MSYS가 Windows 경로로 변환할 수 있습니다. 변환 방지를 위해 `MSYS_NO_PATHCONV=1 ankr track ...`로 실행하세요.

### 5단계 — 토폴로지 검증

```bash
ankr check
# → docs_root: …
#   units: N (X hip, Y hda)
#   ✓ no violations
```

## 명령어 레퍼런스

| 명령 | 역할 |
|------|------|
| `ankr version` | 플러그인 버전 출력. |
| `ankr init [--repair\|--force] [--no-interactive] [-n NAME] [-d DOCS_ROOT] [--houdini-version 21.0]` | `ankr.config.yaml` 스캐폴드 또는 보수. `--repair`는 손편집 키를 보존하고, `--force`는 파일을 완전히 새로 씁니다. 상호 배제. |
| `ankr install-to-houdini [--dry-run] [--force] [-c CONFIG]` | `ankr/` 패키지를 `houdini.user_libs_dir/ankr/`로 복사. `--dry-run`은 파일 목록만 출력. |
| `ankr track --endnode … --hipname … --hip-current … --temp … [옵션…] [-c CONFIG]` | Houdini 안에서 만든 JSON 덤프로부터 KB를 머터리얼라이즈. 최초 추적은 생성, 재추적은 변경된 세그먼트만 덮어씀. |
| `ankr check [--json] [-c CONFIG]` | KB에 토폴로지 invariants I1~I10 적용. critical 위반이 없으면 exit 0, 있으면 1. warning은 exit code에 영향 없음. |

모든 명령은 cwd에서 위로 걸으며 `ankr.config.yaml`을 찾습니다. 명시 지정은 `-c <경로>`.

## 토폴로지 Invariants (I1~I10)

`ankr check`이 KB에 대해 검사하는 10개의 구조적 불변식.

| ID | 심각도 | 규칙 |
|----|--------|------|
| **I1** | critical | 추적된 모든 unit은 정확히 하나의 `skeleton.md`를 갖는다. |
| **I2** | critical | 형제 `skeleton.md` 없이 떠 있는 segment 파일 금지. |
| **I3** | critical | 모든 HDA unit은 `manifest.yaml`을 갖는다 (hip unit은 생략 가능). |
| **I4** | critical | `skeleton.md` frontmatter의 `segment_count: N`은 실제 segment 파일 개수와 일치. |
| **I5** | warning | 소프트 크기 상한: card ≤ 60, skeleton ≤ 300, dataflow ≤ 600, segment ≤ 800, used_by ≤ 200줄. |
| **I6** | (보류) | dataflow.md에서 인용된 attrib/group은 최소 한 segment에 등장. 표준화 대기. |
| **I7** | critical | HDA `manifest.yaml`의 `internal_segments:` 길이가 `segments/` 파일 수와 일치. |
| **I8** | critical | 필수 frontmatter 키 존재: skeleton에는 `endnode`/`last_sync`, segment에는 `segment_id`. |
| **I9** | critical | 경로 레이아웃이 config와 일치: hip endnode는 설정된 깊이, HDA unit은 `<hda_subdir>/<safe_id>/` 아래. |
| **I10** | (보류) | `used_by.md`에 인용된 hip 경로가 여전히 유효. git history 인식 대기. |

CI 게이팅 용도로는 `--json` 출력 추천.

## 설계 원칙 (절대 위반 금지)

1. **외부 메모리 시스템과의 결합 0.** ANKR은 독립적. 옵션 `RuleStore` Protocol은 프로젝트별 메모리 시스템과의 통합용 훅이지만, 기본은 `NullRuleStore`로 아무 연결도 필요 없음.
2. **Houdini 씬에 대해 읽기 전용.** `save_scene` 금지, 노드를 변경하는 `execute_python` 금지, 벤더 HDA(`sidefx::`, `labs::`, `kinefx::`) 내부 진입 금지. 역사적 단일 예외 `walk_hda_definition`은 introspection 후 hip-dirty 플래그를 복원해 호출 전후 씬 상태를 비트 동일하게 보존.
3. **단일 CLI 진입점: `ankr <subcommand>`.** 모든 워크플로우는 하나의 entrypoint를 거침 (Phase 1+에 걸쳐 점진 출시).

## 상태 & 로드맵

ANKR는 in-tree 전신을 캐노니컬 패키지로 포팅 중. 마이그레이션은 단계적으로 진행되며, 현재 공개 표면과 게이트는 상위 프로젝트의 task atlas에서 추적됩니다 — atlas가 "지금 어디에 있고 어디로 가는가"의 단일 진실 원천이며, 이 README는 안정된 사용자 표면 동작만 다룹니다.

## 라이선스

MIT.
