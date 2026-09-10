# includes/

Shared Jinja macros and partials. Added to `_exclude` in the generated
`copier.yml` so they resolve for `include`/`import` but never land in a
generated project.

Owner: Registry & Copier Architect (per `docs/overlay-contract.md` §2).

Expected contents (created by the Registry Architect / Base Template Engineer):

- `slugify.jinja`
- `answers_helpers.jinja` - `selected_overlays()`, `overlay_enabled()`, ordered iteration
- `fragment_loops.jinja` - macros that walk overlays and pull their fragments

This file is a placeholder so the directory exists in version control. Remove it
once real macros land.
