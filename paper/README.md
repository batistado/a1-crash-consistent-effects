# ClaimFence — Archival Manuscript & Reproducibility Bundle

Contains the two-column IEEE Transactions manuscript (`main.tex` & compiled `main.pdf`) targeting *IEEE Transactions on Services Computing (TSC)*, BibTeX database (`references.bib`), auto-synced telemetry macros (`metrics_macros.tex`), 6 vector PDF figures (`figures/fig1..fig6.pdf`), static validator (`validate_latex.py`), and one-click Overleaf bundle (`claimfence_tsc_overleaf.zip`).

## Quick Commands

### 1. Sync Quantitative Macros & Regenerate Vector PDF Figures
```bash
python3 ../scripts/sync_paper_macros.py
python3 generate_figures.py
```

### 2. Run Static LaTeX, Citation, Privacy & Prose Validator
```bash
python3 validate_latex.py
```

### 3. Compile Manuscript PDF
```bash
pdflatex main.tex && bibtex main && pdflatex main.tex && pdflatex main.tex
```
