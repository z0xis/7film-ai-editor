"""P6.22 -- reference-conditioned editor brain (foundation, shadow-only).

A sidecar subsystem, entirely separate from the production planner: it ingests human reference edits
into a structured corpus, retrieves analogous human EDIT GRAMMAR (never shot ids), and emits an
abstract Stage-1 story/sequence plan. Nothing here is wired into build_timeline. No DB / Resolve /
timeline write. See docs/p6_22_reference_conditioned_editor_brain.md.
"""
