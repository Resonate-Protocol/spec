# Contributing

## The spec is authored in split source files

`README.md` is a generated single-page rendering of the spec. Do not edit it
directly. Edit the source files and rebuild:

- `template.md` - the document head (title, protocol overview, definitions,
  role versioning) plus the assembly order
- `connection.md`, `messaging.md`, `pairing.md`
- `roles/<role>/<version>.md` - one file per role version

`template.md` is the assembly root. It holds the head of the page and then
lists the files to append with `<!-- include: <path> -->` directives, in order.
To add a source file, place an `include` directive where it belongs.

HTML comments are dropped from the generated page. A `<!-- keep: ... -->` line
marks the comment right after it to be emitted verbatim (this is how the
generated-file banner reaches the top of `README.md`).

Cross-file Markdown links are written file-relative (e.g. `pairing.md#pairing`
from a top-level file, `../../messaging.md#...` from a role file) and rewritten
to intra-page anchors at build time.

## Editorial rules

The source files follow these rules. Check a change against them before proposing it; reviewers point to them instead of re-explaining.

- **Each role file is self-contained.** A reader who implements one role must not need to read another role file. Text that applies to more than one role therefore appears more than once - the PCM encoding convention and codec framing rules, for example, appear in both `roles/player/v1.md` and `roles/source/v1.md`. Do not combine such text into a shared section.
- **A client describes itself across `client/hello` and `client/state`.** A field expected to change during a connection belongs in `client/state`; a field expected to stay constant for the connection, such as device identity or a fixed hardware limit, belongs in `client/hello`. `client/hello` is sent once per connection, so a field placed there can only be updated by reconnecting.
- **Edit the source files, never `README.md`.** `README.md` is generated; the pre-commit hook regenerates it and blocks direct edits.
- **Every heading needs a unique anchor.** The build fails on two headings that produce the same anchor, and on a link to an anchor with no matching heading.
- **Use one canonical name per term.** Where the Definitions section defines a term, body text uses exactly that name - not a synonym or a prefixed variant, unless the prefix disambiguates (`Sendspin client`, where the WebSocket client is a different thing). Prose names agree with the wire identifiers they describe.
- **`**Note:**` blocks are non-normative.** Requirements - uppercase BCP 14 keywords (MUST, SHOULD, MAY, ...) - belong in body text. A note must read as a comment the reader can skip.

## Pre-commit hook

A hook keeps `README.md` regenerated in every commit from the sources and blocks accidental
direct edits to it. Enable it once per clone with:

```sh
git config core.hooksPath .githooks
```

You need to have `python3` installed for the hook and build tool to work.

## Manually Rebuilding

If you have the pre-commit hook set up, manually running the tool is unnecessary.

```sh
python3 tools/build-readme.py           # regenerate README.md
python3 tools/build-readme.py --check   # verify README.md is in sync (used by CI)
```

The build fails if two headings would produce the same page anchor,
or if a link points at an anchor with no matching heading.