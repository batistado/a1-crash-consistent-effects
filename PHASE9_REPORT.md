# A1 Phase 9 Report — Final Typesetting Pass (fifth private review)

**Date:** 2026-10-08. **Spend:** $0.00 API. **Verdict:** PASS — all five reviewer items addressed; 12 pages, 0 LaTeX errors; visually verified.

## Reviewer items → fixes

### 1. Table 2 (p. 5) — column spillover FIXED
- **Problem:** `tabular{ll}` natural width exceeded `\columnwidth`; spilled into the right column and overlapped the §4.2 heading.
- **Fix:** wrapped in `{\small ...}` with `\begin{tabular}{@{}p{0.30\columnwidth} p{0.62\columnwidth}@{}}` — both columns wrap, constrained to `\columnwidth`.
- **Verified:** p. 5 PNG — table sits fully inside the left column; §4.2 heading clear.

### 2. Figure 2 (p. 6) — label overlaps FIXED (redrawn)
- **Problem:** `call(k, epoch)` label overlapped "stale epochs rejected"; labels crowded the log/receiver boxes; arrows hidden behind boxes.
- **Fix:** full TikZ restructure with explicit coordinates: Claim/Commit arrows stop short of the cylinder (arrowheads visible); call lane on its own lower lane (y=-1.8) with label at x=1.6, clear of the fenced arrow; "fenced" label left of its arrow; reconcile-first dashed arrow rerouted *above* the boxes (fully clear); "stale epochs rejected" below the lane under the tool.
- **Verified:** p. 6 PNG — no label touches any box or another label.

### 3. Figure 1 (p. 4) — gutter width check FIXED
- **Problem:** timeline at `x=1.35cm` spanned 9.72cm > `\columnwidth` (~8.89cm) — bled toward the gutter.
- **Fix:** `x=1.15cm` (8.28cm total).
- **Verified:** p. 4 PNG — timeline fully inside the column, no bleed.

### 4. Artifact availability — RESTORED
- Restored as a compact paragraph after the Conclusion (it was removed in the Phase 8 trim): code/scripts/manuscript at `github.com/batistado/a1-crash-consistent-effects`; datasets/results at `huggingface.co/datasets/batistado/a1-crash-recovery-results`; both private, available to reviewers on request, public upon acceptance.
- **Verified:** present on p. 12 via pdftotext; renders as clickable links.

### 5. §1 "both theorems" → "three theorems" FIXED
- **Verified:** "three theorems" present, "both theorems" absent (pdftotext).

## Incidental fixes (same class, found during verification)
Three more tables spilled beyond `\columnwidth` (found via overfull-hbox audit):
- `tab:llm`: column spec declared 5 cols (`lcccc`) for 4 cols of content — fixed to `lccc`, then `\resizebox{\columnwidth}` (natural width 305pt).
- `tab:v2`: 55pt spill — `\resizebox{\columnwidth}` (preserves 4-decimal precision).
- `tab:crashpoints`: 31pt spill — `\resizebox{\columnwidth}`.
- All verified clean on p. 9 PNG.

## Author list (Mohammed's directive, same pass)
- `\author` block rewritten in IEEEtran style for 5 authors with affiliation superscripts (per AUTHORS.md): Mohammed Kamran Syed* (Mountain House), Anudeep Rentala† / Somesh Rahul† (Fremont), Raghuram Malpe Pai‡ / Krishna Suman Dara‡ (Sunnyvale); emails included; ORCIDs left for the submission system (not rendered by IEEEtran).
- Running head updated to "Syed *et al.*: ...".
- **Verified:** p. 1 PNG — block renders correctly.

## Page-count recovery (12pp constraint)
Author block (+7 lines) and artifact paragraph (+6) pushed the draft to 13pp. Recovered via prose tightening only (no content removed):
- Systems-lineage paragraph (~8 lines), 3 limitation items (~4), LogAct/Khan paragraph (~6), conclusion (~5), evaluation-questions paragraph (~4), artifact paragraph itself (6→4).
- Result: 12 pages, 0 errors, all reviewer-required content intact.

## Files
- `manuscript/main.tex`, `manuscript/main.pdf` (12pp, verified)
- `manuscript/a1-phase9-12pp.pdf` (cache-busted share copy, 12pp, verified)
- `AUTHORS.md` (project root — author source of truth; not committed per instructions)
