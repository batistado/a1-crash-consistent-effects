#!/usr/bin/env python3
"""Static LaTeX, BibTeX, Highlights, Figure, and Humanizer Validator for Elsevier FGCS."""

from __future__ import annotations

import re
import sys
from pathlib import Path

PAPER_DIR = Path(__file__).resolve().parent
MAIN_TEX = PAPER_DIR / "main.tex"
BIB_FILE = PAPER_DIR / "references.bib"
HIGHLIGHTS_TEX = PAPER_DIR / "highlights.tex"

BANNED_SUBSTRINGS = [
    "reviewer-requested",
    "private review",
    "$0.114",
    "0.114",
    "---",
    "—",
    "delve",
    "tapestry",
    "testament to",
    "pivotal moment",
]


def check_highlights() -> list[str]:
    errs = []
    if not HIGHLIGHTS_TEX.exists():
        return ["Missing highlights.tex"]
    txt = HIGHLIGHTS_TEX.read_text(encoding="utf-8")
    items = [m.group(1).strip() for m in re.finditer(r"\\item\s+(.+)", txt)]
    if not (3 <= len(items) <= 5):
        errs.append(f"Elsevier FGCS requires 3-5 highlights, found {len(items)}")
    for idx, it in enumerate(items, 1):
        # Strip simple LaTeX math delimiters if any when checking character count,
        # AND enforce raw string <= 85 chars as conservative upper bound!
        if len(it) > 85:
            errs.append(f"Highlight {idx} exceeds 85 chars ({len(it)}): {it!r}")
    return errs


def validate() -> int:
    errors: list[str] = []
    errors.extend(check_highlights())

    if not MAIN_TEX.exists():
        print("ERROR: main.tex not found")
        return 1
    tex = MAIN_TEX.read_text(encoding="utf-8")
    bib = BIB_FILE.read_text(encoding="utf-8") if BIB_FILE.exists() else ""

    # Strip comments for structural checks
    clean_lines = []
    for line in tex.splitlines():
        line_nc = re.sub(r"(?<!\\)%.*$", "", line)
        clean_lines.append(line_nc)
    clean_tex = "\n".join(clean_lines)

    # 1. Check banned substrings / AI tells / leftover meta-notes
    for bad in BANNED_SUBSTRINGS:
        if bad in clean_tex:
            errors.append(f"Banned substring / AI tell found in main.tex: {bad!r}")

    # 2. Check Elsevier mandatory declarations
    for req_sec in [
        "CRediT authorship contribution statement",
        "Declaration of competing interest",
        "Declaration of generative AI",
    ]:
        if req_sec.lower() not in clean_tex.lower():
            errors.append(f"Missing mandatory Elsevier FGCS section: {req_sec!r}")

    # 3. Citations vs BibTeX keys
    bib_keys = set(re.findall(r"@\w+\{\s*([^,\s]+)\s*,", bib))
    cited_keys: set[str] = set()
    for m in re.finditer(r"\\cite\{([^}]+)\}", clean_tex):
        for k in m.group(1).split(","):
            cited_keys.add(k.strip())

    missing_bib = sorted(cited_keys - bib_keys)
    if missing_bib:
        errors.append(f"Missing BibTeX entries for cited keys: {missing_bib}")
    if len(cited_keys) < 35:
        errors.append(f"Too few unique citations for Q1 archival paper: {len(cited_keys)} (< 35)")

    # 4. Labels vs refs
    labels = set(re.findall(r"\\label\{([^}]+)\}", clean_tex))
    refs = set(re.findall(r"\\(?:eq)?ref\{([^}]+)\}", clean_tex))
    missing_labels = sorted(refs - labels)
    if missing_labels:
        errors.append(f"Unresolved \\ref / \\eqref labels: {missing_labels}")

    # 5. Figures exist
    figs = re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", clean_tex)
    for fg in figs:
        candidates = [PAPER_DIR / fg, PAPER_DIR / "figures" / fg]
        if not any(c.exists() for c in candidates):
            errors.append(f"Missing figure file referenced by \\includegraphics: {fg}")

    # 6. Environment balance
    begins = re.findall(r"\\begin\{([^}]+)\}", clean_tex)
    ends = re.findall(r"\\end\{([^}]+)\}", clean_tex)
    if len(begins) != len(ends):
        errors.append(f"Unbalanced \\begin ({len(begins)}) vs \\end ({len(ends)})")

    if errors:
        print("VALIDATION FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print(
        f"VALIDATION PASSED: {len(cited_keys)} unique citations verified, "
        f"{len(labels)} labels resolved, {len(figs)} figures verified, "
        f"Elsevier FGCS highlights & declarations compliant, 0 banned tells."
    )
    return 0


if __name__ == "__main__":
    sys.exit(validate())
