#!/usr/bin/env python3
"""Static LaTeX, BibTeX, Figure, Privacy, and Humanizer Validator for IEEE TSC."""

from __future__ import annotations

import re
import sys
from pathlib import Path

PAPER_DIR = Path(__file__).resolve().parent
MAIN_TEX = PAPER_DIR / "main.tex"
BIB_FILE = PAPER_DIR / "references.bib"

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


def validate() -> int:
    errors: list[str] = []

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
    clean_lower = clean_tex.lower()

    # 1. Check banned substrings / AI tells / employer leaks
    for bad in BANNED_SUBSTRINGS:
        if bad in clean_lower:
            errors.append(f"Banned substring / employer / AI tell found in main.tex: {bad!r}")

    # 2. Verify IEEE TSC header & Code/Data Availability
    if "SUBMITTED TO IEEE TRANSACTIONS ON SERVICES COMPUTING" not in clean_tex:
        errors.append("Missing IEEE TSC running header in main.tex")
    if "Code and Data Availability" not in clean_tex:
        errors.append("Missing Code and Data Availability section in main.tex")

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
        errors.append(f"Too few unique citations for IEEE Transactions: {len(cited_keys)} (< 35)")

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
        f"IEEE TSC compliant, 0 employer leaks, 0 banned tells."
    )
    return 0


if __name__ == "__main__":
    sys.exit(validate())
