#!/usr/bin/env python3
"""Generate README.md by assembling the split spec files into a single page.

README.md is a build artifact. Edit template.md (and the source files it
includes), not README.md. Run `python3 tools/build-readme.py` to rebuild,
`--check` to verify it is in sync.

template.md is the assembly root: the head of the document followed by
`<!-- include: <path> -->` directives naming the source files to append, in
order. HTML comments in template.md are dropped from the generated page. A
`<!-- keep: ... -->` line marks the comment right after it to be emitted
verbatim, which is how the generated-file banner reaches the top of README.md.
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = "template.md"

COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
INCLUDE_RE = re.compile(r"include:\s*(\S+)\s*$")


class BuildError(Exception):
    """A source problem that stops the page from being generated."""


def slug(heading):
    h = re.sub(r"[^a-z0-9 -]", "", heading.strip().lower())
    return h.strip().replace(" ", "-")


def headings(text):
    return re.findall(r"^#{1,6}\s+(.*)$", text, re.M)


def _fs_read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


def _index_read(rel):
    """Read a source file from the git index (its staged content)."""
    import subprocess

    r = subprocess.run(
        ["git", "-C", ROOT, "show", ":" + rel],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if r.returncode != 0:
        sys.exit("Included file is not staged: %s (git add it first)" % rel)
    return r.stdout


def pieces_from_template(reader):
    """Ordered content pieces from template.md.

    Each piece is ("inline", text) for prose or a kept comment, or ("file",
    path) for an included source file. Dropped comments and the include/keep
    directives themselves yield no piece.
    """
    text = reader(TEMPLATE)
    pieces, pos, keep_next = [], 0, False

    def add_inline(chunk):
        if chunk.strip():
            pieces.append(("inline", chunk))

    for m in COMMENT_RE.finditer(text):
        add_inline(text[pos : m.start()])
        pos = m.end()
        inner = m.group(0)[4:-3].strip()
        inc = INCLUDE_RE.match(inner)
        if inner.startswith("keep:"):
            keep_next = True
        elif inc:
            pieces.append(("file", inc.group(1)))
            keep_next = False
        elif keep_next:
            pieces.append(("inline", m.group(0)))  # emit this comment verbatim
            keep_next = False
        # otherwise the comment is dropped
    add_inline(text[pos:])
    return pieces


def generate(reader=_fs_read):
    rendered = []  # (repo-relative path or "", stripped text)
    for kind, val in pieces_from_template(reader):
        if kind == "inline":
            rendered.append(("", val.strip("\n")))
        else:
            rendered.append((val, reader(val).strip("\n")))

    # Every heading's page anchor. Two headings sharing a slug would give GitHub
    # ambiguous anchors, so require them disambiguated at the source instead.
    anchors, dupes = set(), []
    for _, txt in rendered:
        for h in headings(txt):
            s = slug(h)
            if s in anchors:
                dupes.append(s)
            anchors.add(s)
    if dupes:
        raise BuildError(
            "Duplicate heading anchors (disambiguate in the source): "
            + ", ".join(sorted(set(dupes)))
        )

    # repo-relative path -> top-heading slug, for resolving anchorless file links
    top = {p: slug(headings(txt)[0]) for p, txt in rendered if p and headings(txt)}
    link_re = re.compile(r"\]\(([^)]+)\)")

    def rewrite_in(src_dir):
        def rewrite(m):
            tgt = m.group(1)
            if tgt.startswith(("http://", "https://", "#")):
                return m.group(0)
            path, _, anchor = tgt.partition("#")  # cross-file link -> intra-page
            if not anchor:
                rel = os.path.normpath(os.path.join(src_dir, path)).replace(os.sep, "/")
                anchor = top.get(rel, "")
            return "](#%s)" % anchor

        return rewrite

    body = "\n\n".join(
        link_re.sub(rewrite_in(os.path.dirname(p)), txt) for p, txt in rendered
    )

    dangling = sorted(
        a for a in re.findall(r"\]\(#([^)]*)\)", body) if a not in anchors
    )
    if dangling:
        raise BuildError(
            "Links point at anchors with no matching heading: "
            + ", ".join("#" + a for a in dangling)
        )

    return body + "\n"


def _build_or_exit(reader=_fs_read):
    try:
        return generate(reader)
    except BuildError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    readme = os.path.join(ROOT, "README.md")

    if "--check" in sys.argv:
        cur = open(readme, encoding="utf-8").read() if os.path.exists(readme) else ""
        if cur != _build_or_exit():
            sys.exit("README.md is out of sync. Run: python3 tools/build-readme.py")
        print("README.md is in sync.")

    elif "--precommit" in sys.argv:
        # Regenerate README from the STAGED sources so a partial commit gets a
        # README matching exactly what it commits. Only the staged sources need
        # to build, so unrelated work in progress does not block the commit.
        # Never overwrite a hand-edited README.
        import subprocess

        def show(ref):
            r = subprocess.run(
                ["git", "-C", ROOT, "show", ref],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            return r.stdout if r.returncode == 0 else None

        staged_out = _build_or_exit(_index_read)
        staged = show(":README.md")
        if staged == staged_out:
            sys.exit(0)  # staged README already matches the staged sources

        # A staged README that matches no generated rendering (staged sources,
        # working-tree sources, or HEAD) is a direct edit to a generated file.
        # The working tree may not build mid-edit, so tolerate that here.
        try:
            worktree_out = generate()
        except BuildError:
            worktree_out = None
        generated = {staged_out, worktree_out, show("HEAD:README.md")}
        if staged is not None and staged not in generated:
            sys.exit(
                "README.md is a generated file (see the banner at its top).\n"
                "Your direct edits to README.md would be lost on rebuild.\n"
                "Put the change in template.md or the source files it includes,\n"
                "or discard it with: git checkout -- README.md"
            )

        open(readme, "w", encoding="utf-8", newline="\n").write(staged_out)
        subprocess.run(["git", "-C", ROOT, "add", "README.md"])
        print("README.md regenerated from staged sources and staged.")

    else:
        out = _build_or_exit()
        open(readme, "w", encoding="utf-8", newline="\n").write(out)
        print("wrote README.md (%d lines)" % out.count("\n"))
