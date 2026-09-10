# Copier reference (current upstream)

Research date: 2026-09-07. All facts pulled from live upstream docs and package
metadata on that date, not from model memory. Every section cites the page and
access date it came from.

Sources used throughout:

- Copier docs, "Creating a template": https://copier.readthedocs.io/en/stable/creating/ and raw source https://raw.githubusercontent.com/copier-org/copier/master/docs/creating.md (accessed 2026-09-07)
- Copier docs, "Configuring a template": https://copier.readthedocs.io/en/stable/configuring/ and raw source https://raw.githubusercontent.com/copier-org/copier/master/docs/configuring.md (accessed 2026-09-07)
- Copier docs, "Generating a project": https://copier.readthedocs.io/en/stable/generating/ and raw source https://raw.githubusercontent.com/copier-org/copier/master/docs/generating.md (accessed 2026-09-07)
- Copier docs, "Updating a project": https://copier.readthedocs.io/en/stable/updating/ and raw source https://raw.githubusercontent.com/copier-org/copier/master/docs/updating.md (accessed 2026-09-07)
- Copier docs, "Settings": https://raw.githubusercontent.com/copier-org/copier/master/docs/settings.md (accessed 2026-09-07)
- Copier docs, "API reference": https://copier.readthedocs.io/en/stable/reference/api/ (accessed 2026-09-07)
- Copier docs, "Comparisons" and "FAQ": https://raw.githubusercontent.com/copier-org/copier/master/docs/comparisons.md , https://raw.githubusercontent.com/copier-org/copier/master/docs/faq.md (accessed 2026-09-07)
- PyPI JSON API for copier: https://pypi.org/pypi/copier/json (accessed 2026-09-07)
- GitHub releases: https://github.com/copier-org/copier/releases (accessed 2026-09-07)

## Version and runtime

- Latest stable Copier version: 9.18.2, released 2026-09-07 (source: PyPI JSON
  `info.version`, and GitHub releases page, accessed 2026-09-07). Recent line:
  v9.17.0 (2026-07-13), v9.17.1 (2026-08-04), v9.17.2 (2026-08-19), v9.18.0
  (2026-09-01), v9.18.1 (2026-09-01), v9.18.2 (2026-09-07).
- Python requirement: `>=3.10` (source: PyPI JSON `info.requires_python`, and the
  docs landing page which states Python 3.10 or newer, accessed 2026-09-07).
- Install: `pipx install copier`, `uv tool install copier`, or `pip install
  copier`. Jinja extensions must be installed into the same environment as Copier
  (`pipx inject copier <ext>`, `uv tool install --with <ext> copier`). Source:
  configuring.md `jinja_extensions`, accessed 2026-09-07.
- A template can pin a minimum with `_min_copier_version` (PEP 440). Generation
  aborts if the installed Copier is older. Major version mismatch only warns.
  Source: configuring.md `min_copier_version`, accessed 2026-09-07.

## The copier.yml question file

Source for this whole section: configuring.md, accessed 2026-09-07.

The file is `copier.yml` or `copier.yaml` at the template root (or at
`_subdirectory`). It is parsed as YAML. Keys that are Copier settings start with
an underscore. All other keys are questions.

### Question short form

```yaml
name_of_the_project: My awesome project
number_of_eels: 1234
your_email: ""
```

The value is the default. Type is inferred; default question type is `yaml`.

### Question long form (dict) keys

- `type`: one of `bool`, `float`, `int`, `json`, `path`, `str`, `yaml`. `yaml` is
  the default when `type` is omitted.
- `help`: help text shown with the prompt.
- `default`: default value. Leave unset to force the user to answer. For `choices`
  the default must be the choice value, not its key, and must match `type`. Render
  the special `{{ UNSET }}` variable inside a templated default to force an answer
  under some conditions (the variable becomes undefined in the render context).
- `choices`: restrict allowed values. See the choices forms below.
- `multiselect`: `true` makes the answer a `list[T]` instead of `T`.
- `secret`: `true` masks input with asterisks and does not write the answer to the
  answers file. A `default` is required when `secret: true`.
- `placeholder`: string shown while the answer field is empty. Multiline
  placeholders are not supported.
- `qmark`: custom symbol before the prompt. Defaults to a microphone emoji for
  normal questions and a detective emoji for secret questions.
- `multiline`: `true` allows multi-line input, useful with `json` or `yaml` types.
- `validator`: a Jinja template rendered with the combined answers. It must render
  nothing (or whitespace only) when the value is valid, and an error message
  otherwise.
- `when`: condition that skips the question when false. If a boolean, used
  directly. If a string, parsed to boolean with a YAML-like parser and may be
  templated. A skipped question does not record an answer, but its default value
  is still available in the render context.

### choices forms

List form (label equals value):

```yaml
your_favorite_book:
    choices:
        - The Bible
        - The Hitchhiker's Guide to the Galaxy
```

Dict form (key is shown, value is stored):

```yaml
project_license:
    type: str
    choices:
        MIT: &mit_text |
            Full MIT text...
        Apache2: |
            Full Apache2 text...
    default: *mit_text
```

Tuple form (`[label, value]`):

```yaml
close_to_work:
    choices:
        - [at home, I work at home]
        - [less than 10km, quite close]
```

Extended dict form with per-choice validator (a non-empty render disables that
choice and shows the message):

```yaml
iac:
    type: str
    choices:
        Terraform: tf
        Cloud Formation:
            value: cf
            validator: "{% if cloud != 'AWS' %}Requires AWS{% endif %}"
```

Dynamic choices via a templated string that renders valid YAML list/dict/tuple
choices:

```yaml
dependency_manager:
    type: str
    choices: |
        {%- if language == "python" %}
        - poetry
        - pipenv
        {%- else %}
        - npm
        - yarn
        {%- endif %}
```

Notes: a choice value of `null` makes the value equal to its key. When combining
dynamic choices with validators, wrap the validator template in
`{% raw %}...{% endraw %}`.

### multiselect

```yaml
python_versions:
    type: int
    choices:
        - 3.10
        - 3.11
        - 3.12
    multiselect: true
    default: "[3.10, 3.11]"
```

The default is a templated or literal string that renders a YAML list of choice
values. Items are parsed per the question `type`. Quote items when they are
ambiguous against the list brackets (for example `default: '["[", "]"]'`).

### Prompt templating

Most long-form keys accept Jinja, but only inside string values, and only
referencing variables declared earlier in the file. Example:

```yaml
username:
    type: str
email:
    type: str
    default: "{{ username }}@company.com"
user_config:
    type: "{% if target == 'humans' %}yaml{% else %}json{% endif %}"
```

### _secret_questions

`_secret_questions: [password]` marks short-form questions as secret without
converting them to long form.

### Include other YAML files

`copier.yml` can pull in other YAML files (see configuring.md "Include other YAML
files") so questions and settings can be split across files.

## Answers flow and precedence

Source: configuring.md "Configuration sources", accessed 2026-09-07.

Copier has two kinds of config: settings (Copier behavior) and answers (template
questions).

Settings priority, highest first:

1. CLI or API arguments.
2. `copier.yml` keys prefixed with underscore.

Answers priority, highest first:

1. CLI or API arguments (`--data`, `--data-file`, API `data`).
2. Interactive prompt (skipped for anything already answered by a higher source).
3. Answers from the last run, read from `.copier-answers.yml` in the destination.
4. Default values from `copier.yml`.

`--data` always beats `--data-file`. `--data-file` is CLI only (not API, not
`copier.yml`).

## Built-in template variables

Source: creating.md, accessed 2026-09-07.

- `_copier_answers`: current answers dict, stripped of secrets and of anything not
  cleanly YAML/JSON serializable, plus special keys `_commit` and `_src_path`.
  Write it to the answers file template.
- `_copier_conf`: JSON-serializable config object. Useful attributes:
  `answers_file` (PurePath relative to `dst_path`), `dst_path`, `src_path`
  (absolute path to the cloned template), `sep` (OS path separator), `os` (one of
  `"linux"`, `"macos"`, `"windows"`, or `None`), `vcs_ref`, `vcs_ref_hash`,
  `data`, plus the flag values `conflict`, `context_lines`, `pretend`, `quiet`,
  `overwrite`, `unsafe`, `defaults`, `skip_answered`, `skip_tasks`,
  `cleanup_on_error`, `use_prereleases`, `exclude`, `skip_if_exists`,
  `user_defaults`, `settings`. Warning: `_copier_conf.data` may contain secret
  answers.
- `_copier_python`: absolute path to the Python interpreter running Copier.
- `_copier_phase`: one of `"prompt"`, `"tasks"`, `"migrate"`, `"render"`, or
  `"undefined"`.
- `_copier_operation`: `"copy"` or `"update"`. Only available while rendering
  `exclude` and `tasks`.
- `_external_data`: dict of data loaded from `_external_data` files, parsed as
  YAML lazily on first use.
- `_folder_name`: name of the destination root directory.

Copier always loads `jinja2_ansible_filters.AnsibleCoreFiltersExtension`, so all
Ansible core filters plus `to_nice_yaml` / `to_nice_json` are available.

## Underscore settings reference

Source: configuring.md "Available settings", accessed 2026-09-07. "Not in
copier.yml" means the setting is CLI/API only.

- `_answers_file` (CLI `-a`, `--answers-file`, default `.copier-answers.yml`):
  path, relative to project root, where answers are recorded.
- `ask` (CLI `--ask`, not in copier.yml): glob patterns of questions to always
  ask even when `defaults`, `skip_answered`, or `data` would skip them.
- `cleanup_on_error` (CLI `-C` / `--no-cleanup` to disable, `copier copy` only,
  default true, not in copier.yml): delete the destination if Copier created it
  and rendering or tasks fail. No effect on `update` since Copier did not create
  the folder.
- `conflict` (CLI `-o`, `--conflict`, `copier update` only, `inline` or `rej`,
  default `inline`, not in copier.yml): output format for unresolved update diff
  hunks.
- `context_lines` (CLI `-c`, `--context-lines`, `copier update` only, default
  `1`, not in copier.yml): lines of context for the update diff. More lines means
  more accurate conflict detection and more conflicts to resolve. Git uses 3.
- `data` (CLI `-d`, `--data`, not in copier.yml): answers passed directly, as
  `key=value` on the CLI or a dict via API. Multiselect answers are YAML lists,
  for example `-d 'python_versions=[3.10, 3.11]'`.
- `data_file` (CLI `--data-file`, CLI only): path to a YAML file of answers.
  Equivalent to expanding its keys into `-d` flags. `--data` overrides it.
- `_external_data` (dict, default `{}`): maps a namespace to a YAML file path
  relative to the destination. Exposed as `_external_data[namespace]`. Reading
  files outside the subproject root requires `--trust` / `unsafe=True`. Used for
  template composition (read a parent template's answers file) and for loading
  Git-ignored secrets. A missing static path yields an empty dict.
- `_envops` (dict, default `{"keep_trailing_newline": true}`): Jinja environment
  options. Copier uses Jinja defaults except that it keeps the trailing newline
  at the end of template files. Set `undefined: jinja2.StrictUndefined` to error
  on undefined variables. Copier 7+ ignores the old bracket-based Copier 5
  defaults regardless of `_min_copier_version`.
- `_exclude` (CLI `-x`, `--exclude`, default `["copier.yaml", "copier.yml",
  "~*", "*.py[co]", "__pycache__", ".git", ".DS_Store", ".svn"]`): gitignore-style
  patterns matched against destination paths. Defining `_exclude` in `copier.yml`
  replaces the default list entirely. Adding via CLI or API extends rather than
  replaces. Each pattern may be templated; a single entry may render to multiple
  newline-separated patterns including comments and blank lines. When
  `_subdirectory` points at a real subdirectory the default becomes `[]`.
- `force` (CLI `-f`, `--force`, not in `copier update`, not in copier.yml):
  overwrite existing files without asking and do not prompt; use defaults from
  other sources. `-fd 'k=v'` is the common non-interactive combination.
- `defaults` (CLI `--defaults`, default false, not in copier.yml): use default
  answers. Any question without a default must then be supplied via `--data` or
  the run raises an error.
- `overwrite` (CLI `-w`, `--overwrite`): overwrite existing files without asking
  (distinct from `force`, which also disables prompting).
- `pretend` (CLI `-n`, `--pretend`, not in copier.yml): run without writing
  changes.
- `quiet` (CLI `-q`, `--quiet`, not in copier.yml): suppress status output. Also
  suppresses `_message_*`.
- `_jinja_extensions` (list, default `[]`): dotted paths of Jinja2 extensions to
  load. Loading an extension allows arbitrary code execution, which marks the
  template unsafe. Users must install each extension into Copier's environment.
- `_message_before_copy`, `_message_after_copy`, `_message_before_update`,
  `_message_after_update` (str, default `""`): messages printed around the
  operation. Rendered with the template context; a Jinja `include` can import the
  text from a file. Suppressed in quiet mode.
- `_migrations` (list, default `[]`): see the tasks vs migrations section.
- `_secret_questions` (list, default `[]`): see above.
- `_skip_if_exists` (CLI `-s`, `--skip`, default `[]`): gitignore-style patterns
  for files that must exist but must not be overwritten if already present. If
  missing during an `update` they are recreated. Patterns may be templated.
- `skip_tasks` (CLI `-T`, `--skip-tasks`, default false): skip `_tasks` (not
  `_migrations`). Does not imply `--trust`.
- `skip_answered` (CLI `-A`, `--skip-answered`, `copier update` only, default
  false, not in copier.yml): during update, do not re-ask questions that already
  have a recorded answer.
- `_subdirectory` (str, no CLI flag): directory inside the template repo to use
  as the template root. May be templated (for example
  `_subdirectory: "{{ python_engine }}"` to pick a variant). Recommended so
  template metadata and template code are separate. Copier's rule is one template
  per Git repository, because updates rely on Git tags that are repo-wide.
- `_tasks` (list, default `[]`): see the tasks vs migrations section.
- `_templates_suffix` (str, default `.jinja`): suffix that marks a file for Jinja
  rendering. An empty string renders every non-excluded file, falling back to a
  plain copy on read errors (binary files); with a non-empty suffix a read error
  aborts. If a file exists both with and without the suffix, the one without is
  ignored. Copier 7+ ignores the old `.tmpl` default.
- `unsafe` (CLI `--UNSAFE`, `--trust`, default false, not in copier.yml): allow
  templates that use `_jinja_extensions`, `_migrations`, or `_tasks`. Without it,
  Copier exits with code 4 when those features are present. Can be made permanent
  per-repo with the `trust` user setting.
- `use_prereleases` (CLI `-g`, `--prereleases`, default false, not in copier.yml):
  consider prerelease Git tags when picking the version to copy or update to.
- `vcs_ref` (CLI `-r`, `--vcs-ref`, not in copier.yml): which template Git ref to
  use. Default is the latest tag sorted by PEP 440. `--vcs-ref=HEAD` uses the
  latest commit. `--vcs-ref=:current:` (API `VcsRef.CURRENT`) keeps the template
  version unchanged and only re-runs questions. The chosen ref is stored as
  `_commit` in the answers file.
- `preserve_symlinks` / `_preserve_symlinks` (bool, default false): keep symlinks
  as symlinks instead of replacing them with the target's content. The symlink
  target is still rendered if it ends with the template suffix.
- `_min_copier_version` (str, PEP 440): see the version section.

### Pattern syntax

`exclude` and `skip` use full gitignore syntax via pathspec, including negation
(`"!a.txt"`). Patterns are matched against destination paths.

## Conditional file and directory inclusion

Source: configuring.md "Conditional files and directories" and "Generating a
directory structure", plus creating.md, accessed 2026-09-07.

The current recommended way to include a file or a whole directory only when an
answer is set is to put a Jinja `{% if %}` block in the file or directory name so
that it renders to an empty string when the condition is false, in which case
Copier does not create that path (and, for a directory, none of its contents).

Conditional single file. The template suffix must be outside the condition, or
the whole file is treated as a plain copy:

```
your_template/
    copier.yml
    {% if use_precommit %}.pre-commit-config.yaml{% endif %}.jinja
```

Conditional whole directory. Directory names must not end with the template
suffix:

```
your_template/
    copier.yml
    {% if ci == 'github' %}.github{% endif %}/
        workflows/
            ci.yml
    {% if ci == 'gitlab' %}.gitlab-ci.yml{% endif %}.jinja
```

Use single quotes inside these Jinja conditions, because double quotes are not
valid in Windows paths.

Templated path segments can also build nested directory structures from an
answer, for example
`{{ package.replace('.', _copier_conf.sep) }}{{ _copier_conf.sep }}__main__.py.jinja`
turns an answer of `your_package.cli.main` into
`your_package/cli/main/__main__.py`. Using `/` directly in the answer also works
on Windows.

Loop form with the `yield` tag generates repeated files or directories from a
list variable:

```
commands/
    {% yield cmd from commands %}{{ cmd.name }}{% endyield %}/
        __init__.py
        {% yield subcmd from cmd.subcommands %}{{ subcmd }}{% endyield %}.py.jinja
```

The looped variable (`cmd`, `subcmd`) is in scope inside the generated files.

Alternative and complementary approach: a templated `_exclude` entry that
references answers. A single multi-line entry can gate a group of paths:

```yaml
skip_ci:
    type: bool
_exclude:
    - |
        {% if skip_ci %}
        /.github/workflows/ci.yml
        /.github/workflows/deploy.yml
        /docs/ci/
        {% endif %}
```

`_exclude` templated on `_copier_operation` is how you make a file that is
rendered once on `copy` but never touched on `update`:

```yaml
_exclude:
    - "{% if _copier_operation == 'update' -%}src/*_example.py{% endif %}"
```

For "generate once, then never overwrite but keep present", use
`_skip_if_exists` instead.

Choosing between the techniques: use templated path names for structural
inclusion that should also be respected on update; use `_exclude` for
copy-vs-update asymmetry or for gating many existing paths with one condition;
use `_skip_if_exists` for generated-once files like secrets.

## copier copy vs copier update

Source: generating.md and updating.md, accessed 2026-09-07.

### copier copy

`copier copy SRC DST`. Creates `DST` if missing. `SRC` may be a local path, a
Git URL (`git+https://`, `git+ssh://`, `git@`, `git://`, or ending `.git`), or a
shortcut (`gh:namespace/project`, `gl:namespace/project`). By default Copier
checks out the latest PEP 440 tag. A local template with uncommitted changes is
used as-is (dirty) to aid template development; pass `--vcs-ref HEAD` to use the
current local commit including dirty changes, or `--vcs-ref master` for a branch.

### copier recopy

`copier recopy DST` reapplies the template over an existing project, keeping
answers but ignoring project history. It is the fallback when `copier update`
breaks. The new template overrides local changes, so reconcile with a Git diff
tool afterward. Not the recommended update path.

### copier update

Preconditions, all required:

1. Destination has a valid `.copier-answers.yml`.
2. Template is a Git repo with tags.
3. Destination is a Git repo.
4. `git status` in the destination is clean.

Algorithm (from the docs diagram):

1. Clone the template at the current tag and at the target tag into temp dirs.
2. Regenerate a fresh project from the current template version and run its tasks.
3. Diff the fresh regeneration against the actual current project. This diff is
   the user's own evolution.
4. Apply pre-migrations (`_stage == "before"`) to the current project.
5. Update the project in place with the target template version, prompting for
   answers (defaults come from the recorded answers), and run tasks again.
6. Re-apply the diff from step 3 onto the updated project.
7. Apply post-migrations (`_stage == "after"`).

`--vcs-ref=HEAD` updates to the latest commit rather than the latest tag.
`--vcs-ref=:current:` re-runs the questionnaire without changing template
version. `copier update --defaults` reuses every recorded answer without
prompting. `copier update --defaults --data k=v` changes one answer only.
`--skip-answered` skips questions that already have a recorded answer.

### What .copier-answers.yml must contain

The answers file template must be named `{{ _copier_conf.answers_file }}.jinja`
(so it works with multi-template projects) at the template root, with content:

```
# Changes here will be overwritten by Copier; NEVER EDIT MANUALLY
{{ _copier_answers|to_nice_yaml -}}
```

That records all JSON-serializable answers plus `_src_path` (template location)
and `_commit` (the Git ref or `git describe` of the template at last
copy/update). Secrets are excluded. The path must be relative to the project
root. Add the answers file to the template repo. For multiple templates on one
project, give each its own answers file with `-a`
(`.copier-answers.main.yml`, etc.) and update each separately.

### What causes an update conflict

A conflict is any diff hunk Copier cannot place automatically when re-applying the
user's evolution onto the updated project. With `--conflict inline` (default) the
file gets Git-style conflict markers. With `--conflict rej` a sibling `*.rej`
file holds the unresolved diff. Fewer `context_lines` means fewer conflicts but
less accuracy (lines can be misplaced when a file has similar chunks); more means
more conflicts but higher accuracy. Recommended guardrail: a pre-commit hook,
`check-merge-conflict --assume-in-merge` for inline, or a fail-on-`\.rej$` hook
for rej.

### Deleted paths

Template files or directories that were deleted in the generated project are
excluded from future updates automatically. `copier recopy` plus a recommit
brings them back under update control. `_skip_if_exists` paths are always
recreated even if deleted.

### Known gotchas that break copier update

- Editing `.copier-answers.yml` by hand. This makes Copier believe a different
  answer set produced the current tree, and the diff algorithm becomes
  unpredictable. Officially unsupported.
- The last generation depended on external resources that are no longer
  available.
- Old and new template versions need different incompatible versions of the same
  Jinja extension, and Copier can only load one.
- The old template version was built for an older Copier major version.
- Moving or re-pointing Git tags after projects were generated from them. Tags
  that are valid PEP 440 versions must be stable. Use branches or explicit
  `--vcs-ref` for moving refs.
- Recovery: `copier recopy`, or abort with `git reset` then `git checkout .`
  then `git clean -d -i`.

### check-update

`copier check-update` reports whether a newer template version exists.
`--output-format json` prints
`{"update_available": bool, "current_version": ..., "latest_version": ...}`.
`--quiet` prints nothing and exits 0 for up-to-date, 2 for update available.
`--prereleases` includes prerelease tags.

## Non-interactive usage

Source: configuring.md and generating.md, accessed 2026-09-07.

- `copier copy -fd 'k1=v1' -d 'k2=v2' SRC DST` is the standard fully
  non-interactive copy. `-f` (`--force`) both overwrites and stops all prompting,
  using defaults for everything not supplied.
- `--defaults` uses template defaults for unspecified questions but does not
  imply overwrite. Questions with no default must be given via `--data`, else it
  errors.
- `--data-file input.yml` supplies answers from a YAML file. `--data` overrides
  individual keys. CLI only.
- Answer source precedence again: CLI/API `data` > interactive > last run's
  answers file > `copier.yml` defaults.
- `--pretend` for a dry run. `--vcs-ref` to pin the template version. `--trust`
  (`--UNSAFE`) to allow tasks, migrations, and Jinja extensions; without it a
  template using those exits with code 4. `--skip-tasks` runs everything except
  `_tasks`.
- `--ask 'pattern'` forces specific questions to be asked even under `--defaults`
  or `--data`.
- `-x`/`--exclude` and `-s`/`--skip` can be repeated; from the CLI they extend
  the template's lists.
- `--help-all` prints the complete flag surface.
- User-level defaults: `<CONFIG_ROOT>/settings.yml` `defaults:` block supplies
  values (well-known names `user_name`, `user_email`, `github_user`,
  `gitlab_user`) that replace same-named question defaults. `COPIER_SETTINGS_PATH`
  overrides the config location. The `trust:` list in that file marks
  repositories (exact match, or prefix match when the entry ends with `/` and the
  URL path is only RFC 3986 unreserved characters) as always trusted.

## Tasks vs migrations execution model

Source: configuring.md `tasks` and `migrations`, accessed 2026-09-07.

### _tasks

- Run after generating or updating a project, in declared order, each in its own
  subprocess, with `STAGE=task` in the environment.
- Item forms: a string (run through the system default shell), a list of strings
  (run directly without a shell, no arg escaping needed), or a dict with
  `command`, optional `when` (Jinja condition), optional `working_directory`
  (defaults to the destination directory).
- Rendered with the full template context. `_copier_operation` is available here
  (`"copy"` vs `"update"`), so a task can be gated to copy-only with
  `when: "{{ _copier_operation == 'copy' }}"`.
- Require `--trust`. Skipped entirely by `--skip-tasks`.

### _migrations

- Like tasks, but run only during `update`, never on first copy.
- Item forms: string, list of strings, or dict with `command`, optional `version`
  (PEP 440), optional `when`, optional `working_directory` (defaults to the
  destination directory).
- Run in declared order. With `version` set, a migration runs only when
  `new version >= declared version > old version`. Declaration order wins over
  version order.
- Default stage is "after" the update. Gate to before with
  `when: "{{ _stage == 'before' }}"`. The answers file is reloaded after the
  "before" stage so a migration can rewrite answers.
- Template and env variables available to migrations: `_stage` / `$STAGE`
  (`before` or `after`), `_version_from` / `$VERSION_FROM`, `_version_to` /
  `$VERSION_TO`, `_version_current` / `$VERSION_CURRENT` (only with `version`),
  and PEP 440 normalized forms `_version_pep440_from` / `$VERSION_PEP440_FROM`,
  `_version_pep440_to`, `_version_pep440_current`. In Jinja the pep440 ones are
  `packaging.version.Version` objects; as env vars they are strings.
- A template with non-trivial migrations (a `version` condition that would fire)
  is marked unsafe and needs `--trust`.
- Pre-v9.3.0 used a `dict` with `version` / `before` / `after` keys. Still
  accepted but warns.

### Determinism concerns for tasks and migrations

- Each command runs in a fresh subprocess. String items go through the system
  default shell (`/bin/sh` or the platform equivalent, which varies by OS and
  host config); list items bypass the shell and are the deterministic choice.
- Working directory defaults to the destination but can be set per item with
  `working_directory`. On update, `_copier_conf.dst_path` may be a temporary
  directory because the algorithm regenerates into temp locations, so do not
  assume the final path during update tasks.
- Copier injects `STAGE` (tasks) and the migration `$VERSION_*` / `$STAGE`
  variables, but otherwise inherits the caller's full environment. For
  reproducible output, run Copier with a controlled environment (locale, PATH,
  any tool the tasks call) and prefer list-form commands with explicit
  interpreters such as `["{{ _copier_python }}", "script.py"]`.
- Tasks and migrations can reach the network and the filesystem freely. Keeping
  them minimal (or empty) is what the docs recommend for templates that must
  update reliably over time.

## Programmatic API

Source: https://copier.readthedocs.io/en/stable/reference/api/ , accessed
2026-09-07. Import from the top-level `copier` package.

`copier.run_copy(src_path, dst_path=".", data=None, *, ...) -> Worker`
Copies a template fresh. Key keyword parameters:

- `data: dict` answers.
- `answers_file: Path | str` alternative answers file path.
- `vcs_ref: str | VcsRef` template ref (use `VcsRef.CURRENT` for `:current:`).
- `exclude: Sequence[str]`, `skip_if_exists: Sequence[str]`.
- `use_prereleases: bool = False`.
- `cleanup_on_error: bool = True`.
- `defaults: bool = False`, `user_defaults: dict`.
- `overwrite: bool = False`, `pretend: bool = False`, `quiet: bool = False`.
- `unsafe: bool = False` (equivalent to `--trust`), `skip_tasks: bool = False`.
- `ask: Sequence[str]` questions to force-ask.
- `settings: copier.settings.Settings`.

`copier.run_update(dst_path=".", data=None, *, ...) -> Worker`
Updates an existing project. Same parameters as `run_copy` plus:

- `conflict: Literal["inline", "rej"] = "inline"`.
- `context_lines: int = 3` (API default is 3; the CLI default is 1).
- `skip_answered: bool = False`.

`copier.run_recopy(dst_path=".", data=None, *, ...) -> Worker`
Reapplies the template discarding project evolution. Same parameters as
`run_update` except no `conflict` and no `context_lines`.

All three return a `Worker` instance. `Worker` is the underlying dataclass that
carries every setting listed under `_copier_conf` above; it can be used directly
and as a context manager for finer control, but the three `run_*` helpers are the
supported wrapping surface for a CLI.

Wrapping notes for a deterministic generator CLI:

- Pass every answer through `data=` and set `defaults=True` so nothing prompts.
  Any question lacking a default must be in `data` or the call raises.
- Set `unsafe=True` only if the template genuinely needs tasks/migrations/
  extensions, and vendor or pin those extensions.
- For regeneration in place use `run_recopy`; for smart updates use `run_update`
  and surface the `conflict` choice.
- `vcs_ref` should be pinned to an explicit tag for reproducible output rather
  than relying on "latest tag".

## Reproducibility and deterministic output

Source: configuring.md `envops`, generating.md "Templates versions", updating.md,
faq.md, accessed 2026-09-07. Where the docs are silent this is noted.

- Trailing newlines: Copier overrides one Jinja default and sets
  `keep_trailing_newline: true`, so a template file's final newline is preserved.
  Override via `_envops` if undesired.
- Jinja whitespace: Copier uses stock Jinja whitespace behavior otherwise
  (`trim_blocks` and `lstrip_blocks` are off unless set in `_envops`). Control
  block whitespace with explicit `{%-` / `-%}` in templates.
- Version selection: by default Copier picks the highest PEP 440 tag, which is
  not deterministic across time as new tags land. Pin `vcs_ref` / `_commit` to a
  specific tag for reproducible generation. The docs explicitly warn that version
  tags must be stable and must not be moved after projects are generated.
- Undefined variables: default Jinja `Undefined` renders empty and does not
  error. Set `_envops: {undefined: jinja2.StrictUndefined}` to make missing
  answers fail loudly, which helps catch nondeterministic gaps.
- File ordering: the docs do not document a guaranteed traversal or output
  ordering for generated files. Output content is a pure function of answers plus
  template ref only if tasks, migrations, context hooks, and Jinja extensions are
  absent or themselves deterministic. Time-based extensions such as
  `jinja2_time` and random filters such as `ans_random` deliberately break
  reproducibility.
- Context hooks: the `copier_templates_extensions` `ContextHook` extension can
  mutate the render context (add or delete keys) before each file is rendered.
  Powerful, but it is arbitrary Python and marks the template unsafe.
- Secrets: excluded from `.copier-answers.yml`, so a project cannot be fully
  reproduced from the answers file alone if it has secret questions. Combine with
  `_external_data` reading a Git-ignored secrets file if reproducibility matters.
- OS coupling: `_copier_conf.os` and `_copier_conf.sep` differ by platform, and
  string-form tasks run under different shells per platform. A cross-platform
  deterministic template should avoid `when` conditions on `os` for file content
  and should use list-form tasks.
