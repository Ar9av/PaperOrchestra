# PaperOrchestra Upgrade Notes

- Use [PLANS.md](/Users/jeff/paper-orchestra/PLANS.md) as the long-form execution brief for the local web app upgrade.
- Implement only in `/Users/jeff/paper-orchestra`; treat the archive workspaces and attached papers as reference material.
- Preserve the existing `gui_app/`, `scripts/launch_gui.py`, and test scaffolding, and evolve them in place.
- Keep the canonical pipeline semantics: `ingest -> validate -> outline -> plotting + literature -> section_writing -> refinement -> compile -> finalize`.
