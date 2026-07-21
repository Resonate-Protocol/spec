#!/usr/bin/env python3
"""Generate README.md by concatenating the split spec files into a single page.

README.md is a build artifact. Edit the source files, not README.md.
Run `python3 tools/build-readme.py` to rebuild, `--check` to verify it is in sync.
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Concatenation order (the single-page section order).
ORDER = [
    "preamble.md",  # title, overview diagram, definitions, role versioning
    "connection.md",
    "messaging.md",
    "pairing.md",
    "management.md",
    "roles/player/v1.md",
    "roles/source/v1.md",
    "roles/controller/v1.md",
    "roles/metadata/v1.md",
    "roles/artwork/v1.md",
    "roles/visualizer/v1.md",
    "roles/color/v1.md",
]

BANNER = (
    "<!--\n"
    "  GENERATED FILE - do not edit directly.\n"
    "  README.md is generated from the split spec source .md files.\n"
    "  Edit those, not this file. Enable the pre-commit hook once with\n"
    "  `git config core.hooksPath .githooks` to keep README.md up to date\n"
    "  automatically. See CONTRIBUTING.md for details.\n"
    "-->\n"
)


def slug(heading):
    h = re.sub(r"[^a-z0-9 -]", "", heading.strip().lower())
    return h.strip().replace(" ", "-")


def headings(text):
    return re.findall(r"^#{1,6}\s+(.*)$", text, re.M)


def generate():
    texts = {
        f: open(os.path.join(ROOT, f), encoding="utf-8").read().strip("\n")
        for f in ORDER
    }

    # Every heading's page anchor. Two headings sharing a slug would give GitHub
    # ambiguous anchors, so require them disambiguated at the source instead.
    anchors, dupes = set(), []
    for f in ORDER:
        for h in headings(texts[f]):
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
    top = {f: slug(headings(texts[f])[0]) for f in ORDER}
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
        link_re.sub(rewrite_in(os.path.dirname(f)), texts[f]) for f in ORDER
    )

    dangling = sorted(
        a for a in re.findall(r"\]\(#([^)]*)\)", body) if a not in anchors
    )
    if dangling:
        sys.exit(
            "Links point at anchors with no matching heading: "
            + ", ".join("#" + a for a in dangling)
        )

    return BANNER + "\n" + body + "\n"


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
                    "Put the change in the source files (preamble.md, *.md, roles/*/*.md),\n"
                    "or discard it with: git checkout -- README.md"
                )
            open(readme, "w", encoding="utf-8", newline="\n").write(out)
            subprocess.run(["git", "-C", ROOT, "add", "README.md"])
            print("README.md regenerated from sources and staged.")

    else:
        open(readme, "w", encoding="utf-8", newline="\n").write(out)
        print("wrote README.md (%d lines)" % out.count("\n"))
