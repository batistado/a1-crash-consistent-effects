# A1 Manuscript Trim Note (2026-10-08)

**Goal:** reduce 14-page Phase-7 manuscript to ≤12 pages to avoid TPDS
Mandatory Overlength Page Charges. **Result: 12 pages**, 0 LaTeX errors,
0 unresolved references.

## What was compressed (substance preserved)

1. **Table 1 (positioning, `tab:positioning`)** — the largest single
   space consumer. Set in `\scriptsize` (was full-size), column widths
   narrowed, cell prose tightened ~30%. All 10 rows, all 8 columns, and
   every reviewer-required distinction kept (LogAct single-agent focus,
   LIMBO Prop. 2 conditional exactly-once, Khan formal-neighbor
   citation, ACRFence/LogAct/AgentRewind/Safe-to-Resume/RIFL/ARIES/Sagas
   rows).
2. **Table 8 (boundary experiments, `tab:boundary`)** — set in
   `\footnotesize`, verbose cells shortened (E1/E3/E5). All rows
   (E1/E2a/E2b/E3/E4/E5), all columns, all numbers unchanged.
3. **§6.5 E-paragraphs (E1/E2/E4/E5)** — prose tightened ~35%; every
   reviewer-required fact kept (E1 native-setup detail, E2
   transformations + combined-design attribution, E4 representative
   trace + separate-fault-model note, E5 honest inconclusive interval
   + CI method).
4. **Abstract / Introduction / Background** — prose tightened
   10–20%; all contributions, all related-work corrections, all
   citations kept.
5. **Ablation intro** — zombie-writer description deduplicated via
   cross-reference to E4 (was stated twice in full).
6. **Discussion** — planner-agnostic paragraph merged into a closing
   sentence of the preceding paragraph.
7. **Evaluation intro, Q4 LLM-supervisor paragraph, Threats to
   validity** — prose tightened; all numbers and reconciliations kept.
8. **Removed:** the `Artifact Availability` section (draft
   meta-content: GitHub/HF links; not part of the submitted paper)
   and the redundant `A concrete failure` subsection (§3; the
   Introduction already tells the refund story; Fig. 1 stays,
   referenced from Formalization).

## What was NOT touched

- Theorem 1 (+ non-invariance condition), Theorem 2a/2b/2c, all proofs
- Identity consistency: (action,target,occurrence) everywhere
- A6/A7 assumptions, Definition 3 invariant, create-or-reuse algorithm
- E1–E7 results and all result numbers/tables
- Related-work corrections, all 11 bibliography entries
- FORMAL_MODEL.md (not page-counted; untouched)

## Layout

- Float placement parameters tightened
  (`\textfraction` 0.05, `\topfraction`/`\bottomfraction` 0.95) so
  Tables 1/2/7/8 sit inline (pp. 4, 5, 11) instead of piling at the
  end; references on p. 12.
- Table 1 renders in `\scriptsize` — readable at normal zoom, dense
  by design; flag if the reviewer finds it too small.

## Before/after

| Metric | Before | After |
|---|---|---|
| Pages (pdfinfo) | 14 | **12** |
| LaTeX errors | 0 | 0 |
| Unresolved refs | 0 | 0 |
| main.tex size | 83,806 B | 79,332 B |

**Verdict:** PASS — 12-page TPDS-regular limit met with all
reviewer-required content intact. Nothing committed or pushed;
awaiting Mohammed's review of the trim.
