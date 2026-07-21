# Contributing

## The spec is authored in split source files

`README.md` is a generated single-page rendering of the spec. Do not edit it
directly. Edit the source files and rebuild:

- `preamble.md` - title, overview diagram, definitions, role versioning
- `connection.md`, `messaging.md`, `pairing.md`, `management.md`
- `roles/<role>/<version>.md` - one file per role version

The concatenation order lives in `tools/build-readme.py` (`ORDER`). Add a new
source file there.

Cross-file Markdown links are written file-relative (e.g. `pairing.md#pairing`
from a top-level file, `../../messaging.md#...` from a role file) and rewritten
to intra-page anchors at build time.

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