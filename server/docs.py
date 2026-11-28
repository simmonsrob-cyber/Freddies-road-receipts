"""PDF and Word uploads: turn each page into a photo-style PNG so the normal scan + OCR path handles it."""
import shutil
import subprocess
import tempfile
from pathlib import Path

MAX_PAGES = 6


def kind(head: bytes, name: str = ""):
    n = (name or "").lower()
    if head[:5] == b"%PDF-":
        return "pdf"
    if head[:4] == b"PK\x03\x04" and n.endswith(".docx"):
        return "docx"
    if head[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" and n.endswith(".doc"):
        return "doc"
    return None


def _pdf_to_pngs(pdf: Path, outdir: Path, prefix: str):
    if not shutil.which("pdftoppm"):
        raise RuntimeError("PDF support is not installed on the Pi (poppler-utils). Run the update again.")
    subprocess.run(["pdftoppm", "-r", "200", "-png", "-l", str(MAX_PAGES), str(pdf), str(outdir / prefix)],
                   check=True, timeout=120, capture_output=True)
    return sorted(outdir.glob(prefix + "*.png"))


def _docx_text_pdf(src: Path, pdf: Path):
    """Fallback when LibreOffice is not installed: plain text of the .docx on a letter page."""
    import docx
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    d = docx.Document(str(src))
    lines = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            lines.append("   ".join(c.text.strip() for c in row.cells))
    c = canvas.Canvas(str(pdf), pagesize=letter)
    y = 750
    c.setFont("Helvetica", 11)
    for ln in lines or [" "]:
        while len(ln) > 95:
            c.drawString(50, y, ln[:95])
            ln, y = ln[95:], y - 14
            if y < 50:
                c.showPage(); c.setFont("Helvetica", 11); y = 750
        c.drawString(50, y, ln)
        y -= 14
        if y < 50:
            c.showPage(); c.setFont("Helvetica", 11); y = 750
    c.save()


def to_pngs(src: Path, k: str, outdir: Path, prefix: str):
    """Returns a list of PNG paths (one per page). Raises RuntimeError with a plain message on failure."""
    outdir.mkdir(parents=True, exist_ok=True)
    try:
        if k == "pdf":
            return _pdf_to_pngs(src, outdir, prefix)
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            pdf = td / (src.stem + ".pdf")
            office = shutil.which("soffice") or shutil.which("libreoffice")
            if office:
                subprocess.run([office, "--headless", "--convert-to", "pdf", "--outdir", str(td), str(src)],
                               check=True, timeout=180, capture_output=True, env={"HOME": str(td), "PATH": "/usr/bin:/bin:/usr/local/bin"})
            elif k == "docx":
                _docx_text_pdf(src, pdf)
            else:
                raise RuntimeError("Old .doc files need LibreOffice on the Pi. Save it as .docx or PDF and try again.")
            if not pdf.exists():
                raise RuntimeError("Could not open that Word file. Save it as PDF and try again.")
            return _pdf_to_pngs(pdf, outdir, prefix)
    except subprocess.TimeoutExpired:
        raise RuntimeError("That file took too long to open.")
    except subprocess.CalledProcessError:
        raise RuntimeError("Could not open that file. Try saving it as a PDF.")
