#!/usr/bin/env python3
"""Generate README.md by assembling the split spec files into a single page.

README.md is a build artifact. Edit template.md (and the source files it
includes), not README.md. Run `python3 tools/build-readme.py` to rebuild,
`--check` to verify it is in sync.

template.md is the assembly root: the head of the document followed by
`<!-- include: <path> -->` directives naming the source files to append, in
order. HTML comments are dropped from the generated page; a `<!-- keep: ... -->`
line marks the comment right after it to be emitted verbatim (that is how the
generated-file banner reaches the top of README.md).
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = "template.md"

COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
INCLUDE_RE = re.compile(r"include:\s*(\S+)\s*$")


def slug(heading):
    h = re.sub(r"[^a-z0-9 -]", "", heading.strip().lower())
    return h.strip().replace(" ", "-")


def headings(text):
    return re.findall(r"^#{1,6}\s+(.*)$", text, re.M)


def read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


def pieces_from_template():
    """Ordered content pieces from template.md.

    Each piece is ("inline", text) for prose or a kept comment, or ("file",
    path) for an included source file. Dropped comments and the include/keep
    directives themselves yield no piece.
    """
    text = read(TEMPLATE)
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


def generate():
    rendered = []  # (repo-relative path or "", stripped text)
    for kind, val in pieces_from_template():
        if kind == "inline":
            rendered.append(("", val.strip("\n")))
        else:
            rendered.append((val, read(val).strip("\n")))

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
        sys.exit(
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
        sys.exit(
            "Links point at anchors with no matching heading: "
            + ", ".join("#" + a for a in dangling)
        )

    return body + "\n"


def head_readme():
    import subprocess

    r = subprocess.run(
        ["git", "-C", ROOT, "show", "HEAD:README.md"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return r.stdout if r.returncode == 0 else None


if __name__ == "__main__":
    out = generate()
    readme = os.path.join(ROOT, "README.md")
    cur = open(readme, encoding="utf-8").read() if os.path.exists(readme) else ""

    if "--check" in sys.argv:
        if cur != out:
            sys.exit("README.md is out of sync. Run: python3 tools/build-readme.py")
        print("README.md is in sync.")

    elif "--precommit" in sys.argv:
        # Auto-update README from sources, but never overwrite a hand-edited one.
        import subprocess

        if cur == out:
            subprocess.run(["git", "-C", ROOT, "add", "README.md"])
        else:
            head = head_readme()
            if head is not None and cur != head:
                sys.exit(
                    "README.md is a generated file (see the banner at its top).\n"
                    "Your direct edits to README.md would be lost on rebuild.\n"
                    "Put the change in template.md or the source files it includes,\n"
                    "or discard it with: git checkout -- README.md"
                )
            open(readme, "w", encoding="utf-8", newline="\n").write(out)
            subprocess.run(["git", "-C", ROOT, "add", "README.md"])
            print("README.md regenerated from sources and staged.")

    else:
        open(readme, "w", encoding="utf-8", newline="\n").write(out)
        print("wrote README.md (%d lines)" % out.count("\n"))
