# Naming Conventions

This repository uses one naming system across branches, PR titles, and commit subjects.

## 1. Branch names

Use:

```text
type/short-slug
```

Examples:

- `feat/repo-guard`
- `fix/commit-parser`
- `doc/pr-template`
- `chore/github-actions`

Allowed `type` values:

- `feat`
- `fix`
- `doc`
- `docs`
- `chore`
- `refactor`
- `test`
- `ci`
- `infra`
- `perf`
- `build`
- `style`
- `research`
- `revert`

Rules:

- lowercase only
- use `-` to separate words in the slug
- keep it short and specific
- one branch should focus on one intent

## 2. PR titles

Use:

```text
type(scope): summary
```

Examples:

- `feat(repo-guard): add pre-push quality checks`
- `fix(repo-guard): reject non-conventional commit subjects`
- `doc(github): document branch protection setup`

Rules:

- `type` must be one of the allowed values above
- `scope` should describe the subsystem or area being changed
- `summary` should be concise and start lowercase
- do not add trailing periods
- do not use `WIP`, `Draft`, `tmp`, `fixup!`, or `squash!`

## 3. Commit subjects

Commit subjects follow the same rule as PR titles:

```text
type(scope): summary
```

Example:

```text
feat(repo-guard): enforce conventional subject shapes
```

Commit bodies must then include the repository Lore trailers:

```text
Confidence: high|medium|low
Scope-risk: narrow|moderate|broad
Tested: <what was verified>
```

Optional trailers:

- `Constraint: ...`
- `Rejected: ...`
- `Directive: ...`
- `Not-tested: ...`

## 4. Scope guidance

Good scopes are stable and review-friendly. Prefer:

- `repo-guard`
- `github`
- `docs`
- `rag`
- `planner`
- `copilot`
- `workflow`

Avoid:

- overly broad scopes like `misc`
- temporary scopes like `test2`
- ticket-only scopes that have no product meaning

## 5. Reviewer goal

The naming system should let a reviewer understand three things immediately:

1. what kind of change this is
2. which area it touches
3. what the change is trying to accomplish
