"""
CAKI - caki_stabilnost.py (14.10.2026.)
Zaštite protiv pada cijelog Streamlit procesa ("Segmentation fault" / "free(): corrupted ...")
koji se javlja kad se u Test Builderu odabere cjelina s puno slika (npr. Planimetrija).

1) faulthandler - ako proces ipak padne u C kodu, u Streamlit logu ostaje Python stack svih
   dretvi (inače piše samo "Segmentation fault" bez ikakvog traga).
2) DRIVE_LOCK - Google API klijent (httplib2) NIJE sigurna za istodobno korištenje iz više
   dretvi, a Streamlit pokreće svaki rerun u svojoj dretvi i dijeli jedan Drive servis
   (st.cache_resource). Kad korisnik klikne dok se slike još učitavaju, dva reruna zovu Drive
   istovremeno -> oštećenje memorije. Svi Drive pozivi za slike zato idu kroz ovaj lock.
3) slika_izgleda_valjano / slika_html - slika se NE dekodira na serveru (nema Pillowa/C
   dekodera): provjeri se samo "magic" zaglavlje i veličina, a prikaz prepusti pregledniku
   preko data: URI-ja u <img>. Oštećena slika tako u najgorem slučaju ispadne kao slomljena
   ikona u pregledniku, ne kao pad procesa.
"""
import base64
import faulthandler
import html
import sys
import threading

try:
    faulthandler.enable(file=sys.stderr, all_threads=True)
except Exception:
    pass

DRIVE_LOCK = threading.RLock()

MAX_BAJTOVA_SLIKE = 8 * 1024 * 1024


def mime_slike(b):
    """MIME tip prema zaglavlju datoteke, ili None ako nije PNG/JPEG/GIF/WebP."""
    if not b or len(b) < 12:
        return None
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if b[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    return None


def slika_izgleda_valjano(b):
    return mime_slike(b) is not None and len(b) <= MAX_BAJTOVA_SLIKE


def slika_html(b, width=130, opis=""):
    """<img> s ugrađenom slikom (data URI); '' ako slika nije valjana."""
    mime = mime_slike(b)
    if not mime or len(b) > MAX_BAJTOVA_SLIKE:
        return ""
    kodirano = base64.b64encode(b).decode("ascii")
    return (f'<img src="data:{mime};base64,{kodirano}" alt="{html.escape(opis, quote=True)}" '
            f'style="width:{int(width)}px;max-width:100%;height:auto;" loading="lazy">')
