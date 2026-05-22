# houdini-ankr

**ANKR — Agent Network Knowledge Reader.**
A canonical Claude Code plugin that tracks SideFX Houdini networks into a hierarchical markdown knowledge base (L0 card → L1 skeleton → L1.5 dataflow → L2 segments → L3 manifest), with drift detection, history accumulation, overflow handling, and topology invariants.

> Status: **alpha**, Phase 0 (Foundation). Public surface unstable until v0.1.0.

## Design principles (load-bearing — do not violate)

1. **Zero hardcoded paths.** Every path resolves through `ankr.config.yaml` (see `ankr.config.example.yaml`). The plugin runs on any OS, any user, any project layout.
2. **Zero coupling to external memory systems.** ANKR is self-contained. An optional `RuleStore` Protocol exists for opt-in integration (e.g. with a project's own memory system), but the default is `NullRuleStore` and nothing requires wiring.
3. **Read-only on Houdini scenes.** Never `save_scene`, never `execute_python` that mutates nodes, never enter vendor HDAs (`sidefx::`, `labs::`, `kinefx::`).
4. **Single CLI surface: `ankr <subcommand>`.** All workflows go through one entrypoint (rolled out incrementally Phase 1+).

## Install (alpha)

```bash
pip install -e .
ankr init               # scaffolds ankr.config.yaml in the current project
ankr check              # (Phase 1) runs topology invariants
```

## Architecture

See the master roadmap atlas in the parent project for current phase, decisions, and gates:
`E:/01_houdiniAgent/handover_doc/task_atlas/active/ankr_canonical_atlas.md`

The atlas — not this README — is the source of truth for "where are we and where are we going".

## License

MIT.
