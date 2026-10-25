#!/bin/sh
# Rebuild the diagram PDFs after editing a diagram's .tex file here.
#   ./build.sh            every diagram
#   ./build.sh er states  only these
# Uses pdflatex if installed, otherwise tectonic. On Overleaf: set the
# diagram's .tex file as the main document, compile, download the PDF and
# upload it here under the same name (then set main.tex back as main).
set -e
cd "$(dirname "$0")"
[ $# -gt 0 ] && names="$*" || names=$(ls *.tex | grep -v '^style.tex$' | sed 's/\.tex$//')
for n in $names; do
  if command -v pdflatex >/dev/null 2>&1; then
    pdflatex -interaction=nonstopmode -halt-on-error "$n.tex" >/dev/null || { echo "failed: $n (see $n.log)"; exit 1; }
  else
    tectonic "$n.tex" >/dev/null 2>&1 || { echo "failed: $n (run: tectonic $n.tex)"; exit 1; }
  fi
  rm -f "$n.aux" "$n.log"
  echo "built $n.pdf"
done
