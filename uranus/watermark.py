"""Hidden authorship watermark for Uranus HTML pages and PDF documents.

HTML: author / copyright <meta> tags, a comment, and a visually hidden text element.
PDF:  document metadata (Author, Creator, Subject, Keywords, /Watermark) plus a line of
      invisible text (render mode 3) on every page, which survives copy/extract but never shows or prints.

    python -m uranus.watermark FILE [FILE ...]      # stamp files in place (HTML or PDF)
"""

import html as _html
import io
import os
import re
import sys

OWNER = "Kammie M Holder FSS, LUTCF, MBLAS"
MARK = f"Watermark: {OWNER}"


def html_head():
    o = _html.escape(OWNER, quote=True)
    return (f'<meta name="author" content="{o}">\n<meta name="copyright" content="{o}">\n'
            f'<meta name="watermark" content="{o}">\n<!-- {_html.escape(MARK)} -->\n')


def html_body():
    return ('<div aria-hidden="true" data-watermark="1" style="position:absolute;left:-9999px;top:0;width:1px;'
            'height:1px;overflow:hidden;opacity:0;pointer-events:none;user-select:none">'
            f'{_html.escape(MARK)}</div>\n')


def is_marked_html(text):
    return 'name="watermark"' in text and 'data-watermark="1"' in text


def stamp_html(text):
    """Return the HTML with the hidden watermark added (unchanged if already present)."""
    if is_marked_html(text):
        return text
    m = re.search(r"<head[^>]*>", text, re.I)
    text = text[:m.end()] + "\n" + html_head() + text[m.end():] if m else html_head() + text
    m = None
    for m in re.finditer(r"</body\s*>", text, re.I):
        pass
    return text[:m.start()] + html_body() + text[m.start():] if m else text + html_body()


def _invisible_page(width, height):
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))
    t = c.beginText(8, 8)
    t.setTextRenderMode(3)                      # neither fill nor stroke: invisible, still extractable
    t.setFont("Helvetica", 4)
    t.textLine(MARK)
    c.drawText(t)
    c.setAuthor(OWNER)
    c.save()
    buf.seek(0)
    return buf


def is_marked_pdf(path):
    from pypdf import PdfReader
    r = PdfReader(path)
    meta = r.metadata or {}
    return meta.get("/Watermark") == OWNER


def stamp_pdf(src, dst=None):
    """Write a copy of the PDF with the hidden watermark (in place when dst is None)."""
    from pypdf import PdfReader, PdfWriter
    dst = dst or src
    r = PdfReader(src)
    if (r.metadata or {}).get("/Watermark") == OWNER:
        if dst != src:
            with open(src, "rb") as a, open(dst, "wb") as b:
                b.write(a.read())
        return dst
    w = PdfWriter()
    for page in r.pages:
        box = page.mediabox
        overlay = PdfReader(_invisible_page(float(box.width), float(box.height))).pages[0]
        page.merge_page(overlay)
        w.add_page(page)
    meta = {k: v for k, v in (r.metadata or {}).items() if isinstance(v, str)}
    meta.update({"/Author": OWNER, "/Creator": f"{meta.get('/Creator', 'Uranus')} - {OWNER}".strip(" -"),
                 "/Subject": meta.get("/Subject", "") or MARK, "/Keywords": MARK, "/Watermark": OWNER,
                 "/Copyright": OWNER})
    w.add_metadata(meta)
    tmp = dst + ".tmp"
    with open(tmp, "wb") as f:
        w.write(f)
    os.replace(tmp, dst)
    return dst


def stamp_file(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return stamp_pdf(path)
    if ext in (".html", ".htm"):
        with open(path, encoding="utf-8") as f:
            t = f.read()
        s = stamp_html(t)
        if s != t:
            with open(path, "w", encoding="utf-8") as f:
                f.write(s)
        return path
    raise ValueError(f"not HTML or PDF: {path}")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print("stamped", stamp_file(p))
