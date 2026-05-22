"""Subcommand modules for the `ankr` CLI.

Each subcommand is implemented in its own module here and registered by
`ankr.cli`. Keeping commands out of `cli.py` prevents that file from
growing into a monolith as Phase 1.6 absorbs the 12 legacy scripts.
"""
