# CONTEXT — Cygnus glossary

Shared vocabulary. Glossary only — no implementation detail. Product/domain terms
live in `docs/{zh,en}/domain-model.md`; this file holds cross-cutting UI-surface terms.

## Operation Console
The application behind `/console`: an operational **portal** — persistent left sidebar
+ multiple sections + dense functional pages — modeled on the structure of the sibling
product **Arkon** (NOT Arkon's warm visual style). This replaced the earlier single
"Command Center" hero, which read as a toy / AI demo.

## Review Queue
The first / entry page of the Operation Console — a dense **risk inbox**: governance
risks ranked by risk (not time), each row opening the Consequence drawer. Bound to
`GET /api/command-center`.

## Consequence drawer
The pre-action view of a risk's scope / blast radius — affected audiences × downstream
surfaces — shown before any command is issued (the "Every Action Has Scope" principle).
Opens from a Review Queue row.

## Owner gap
A governance risk whose queue owner is unassigned (`owner_state = unassigned`); shown as
a caution-colored signal.

## Blue DNA (design language)
The Operation Console's visual language: clean **light only**, blue accent `#185ee0`,
light-blue tint `#e6eef9`, soft blue-tinted elevation (no hard shadows), rounded/pill
shapes, smooth slide transitions. Derived from a user-supplied component reference.
Implemented as shadcn-convention tokens in `frontend/src/index.css`.

> Retired / superseded surfaces & languages (do not reintroduce): "Command Brutalism"
> (hard shadows + purple), "Restrained Ops" (flat + purple, dual-theme), and the single
> "Command Center" hero with its Command Horizon / Command Ribbon. The skiper6 marketing
> **landing** (`/`) is unaffected and retained.
