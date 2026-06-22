"""
Shared prompt fragments for wiki generation.

These are intentionally lightweight and dependency-free so the compiler,
mini-agent, and writer prompts can share the same quality rules without
copy/paste drift.
"""

WIKI_PAGE_QUALITY_RULES = """\
# Mindset: COMPILE, do NOT summarize
You are not writing an executive summary. You are extracting structured knowledge
and rewriting it into reusable wiki pages. A wiki page must contain MORE
information density than a summary — organized differently, but never condensed.
A summary loses specifics. A wiki page preserves them in a queryable structure.

If someone reads a wiki page two years from now, they should still be able to
find the actual numbers, regulations, procedures, names, and edge cases — not
just a high-level recap.

# What to KEEP from the source (never lose these)
- Specific numbers: thresholds, dosages, timeframes, dimensions, distances, percentages.
- Named regulations, laws, articles, code references.
- Equipment names, model numbers, product specs, serial ranges.
- Procedure steps in order, with actual actions (not "follow the procedure"
  but "1. do X 2. do Y 3. do Z").
- Worked examples and exceptions — usually the highest-value content.
- Named parties, roles, contact paths, escalation chains.
- Definitions verbatim or near-verbatim if the source is authoritative.
- Cause-effect statements ("X causes Y because Z") — preserve all three parts.

# What to DROP
- Marketing language, mission statements, ceremonial filler.
- Source-specific framing: "This document explains...", "In Section 3 below..."
- Repeated boilerplate, tables of contents, cover page metadata.
- Prose that just rephrases what was already said.

# Language rule
Write in the SAME LANGUAGE as the source document. Never translate content.

# Page types
- `entity`  — a specific named thing: a person, organization, system, product, place.
- `concept` — a process, policy, rule, methodology, regulation, equipment type, or
              any other reusable idea that deserves its own permanent reference page.
- `topic`   — a broader subject area that groups related entities and concepts.
- `source`  — a one-page summary of THIS document. Always create exactly one.

# Slug rules
- URL-safe, lowercase, hyphenated, prefixed by type:
  `entity/jane-doe`, `concept/expense-approval`, `topic/fire-safety`,
  `source/<short-doc-slug>`.
- Slugs must be in Latin characters regardless of document language (transliterate
  or translate key words).
- Pick stable, generalizable slugs future sources will naturally update.

# Wikilinks
- Use `[[slug]]` or `[[slug|display text]]` to link between pages.
- Always link the first mention of any entity/concept to its dedicated page.
- Link to pages that don't exist yet when the workflow allows creating them.

# Content quality — CRITICAL
Each page must be a proper encyclopedic article, NOT a flat bullet list.

## Required structure
1. **Opening paragraph** — 2-4 sentences defining what this thing is and why it matters.
   No heading for this paragraph; it comes right after the H1 title.
2. **Sections with H2 headings** — group related facts under clear headings.
   Each section starts with a sentence of prose before any sub-bullets.
3. **Bold key terms** on first use. Link them to their wiki pages with [[slug]].
4. **Examples or implications** where the source provides them.
5. **See also** section at the end — wikilinks to closely related pages.

## Hard minimums
- `concept` and `topic` pages: at least 150 words of actual prose + structure.
- `entity` pages: at least 100 words.
- `source` pages: at least 150 words with links to all entity/concept pages it touches.
- Every page should link to at least 2 other pages when the content permits it.

## What NOT to do
- Do NOT write a page that is just a title + 3 bullets. That is not a wiki page.
- Do NOT omit the opening prose paragraph.
- Do NOT write a page with no wikilinks.
- Do NOT just copy-paste bullet points from the source as the entire content.
- Do NOT include a Citations or Footnotes section.
- Do NOT use [^N] footnote markers.

# Image markers
- PRESERVE image markers verbatim: ![caption](image://<uuid>)
- Place each marker where it's most contextually relevant.
- Do NOT invent image UUIDs.
"""

WIKI_FIRE_SAFETY_EXAMPLE = """\
## BAD example — what NOT to produce
```
# Fire safety responsibilities of a household

Defines the responsibilities of the household head and family members.

## Responsibilities of the household head
- Ensure members comply with fire safety rules.
- Inspect and mitigate fire and explosion risks.
```
Why bad: only bullet headlines. No legal references, no specific numbers, no procedure
steps. A person cannot answer any practical question from this.

## GOOD example — preserves substance
```
# Fire safety responsibilities of a household

Every household has a legal obligation within [[concept/fire-safety|fire safety work]]
under Article 5 of [[entity/fire-prevention-and-fighting-law-2001|the Fire Prevention and
Fighting Law 2001]] (as amended in 2013) and Decree 136/2020/ND-CP. Responsibility is shared
between the household head — the primary legal account holder — and the members, forming
the first line of defense before professional fire services are needed.

## Responsibilities of the household head

The household head carries the primary legal responsibility and must complete three groups of
duties:

### 1. Educate and enforce compliance
Organize basic fire safety training for every member aged 10 or older. Recommended:
- At least one internal briefing each quarter.
- [[concept/emergency-evacuation|Evacuation]] drills every 6 months.
- Teach children the 114 emergency number, escape routes, and low-crawl techniques in smoke.

## See also
- [[concept/fire-prevention-and-fighting]]
- [[concept/fire-safety]]
```
Why this works: it preserves legal references, specific numbers, procedure ordering, and
wikilinks throughout.
"""
