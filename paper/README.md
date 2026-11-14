# ClaimFence — Archival Manuscript & Reproducibility Bundle

Contains the two-column archival manuscript (`main.tex` & compiled `main.pdf`), Elsevier *Future Generation Computer Systems (FGCS)* Research Highlights (`highlights.tex` & `highlights.pdf`), BibTeX database (`references.bib`), auto-synced telemetry macros (`metrics_macros.tex`), 6 vector PDF figures (`figures/fig1..fig6.pdf`), static validator (`validate_latex.py`), and one-click Overleaf bundle (`claimfence_fgcs_overleaf.zip`).

## Quick Commands

### 1. Sync Quantitative Macros & Regenerate Vector PDF Figures
```bash
python3 ../scripts/sync_paper_macros.py
python3 generate_figures.py
```

### 2. Run Static LaTeX, Citation, Highlights & Prose Validator
```bash
python3 validate_latex.py
```

### 3. Compile Manuscript & Highlights PDFs
```bash
pdflatex main.tex && bibtex main && pdflatex main.tex && pdflatex main.tex
pdflatex highlights.tex
```
