"""
ocr_nlp.py — Pipeline EasyOCR + spaCy + parsing testo libero.
Estrae importo, descrizione, data da foto scontrini e testo italiano.
"""
import re, logging, io
from datetime import date, datetime
from typing import Optional
from PIL import Image

logger = logging.getLogger(__name__)

# Componenti caricati lazy
_ocr_reader = None
_nlp = None


def _get_ocr():
    """Carica EasyOCR reader (lazy loading per risparmiare RAM)."""
    global _ocr_reader
    if _ocr_reader is None:
        import easyocr
        _ocr_reader = easyocr.Reader(['it', 'en'], gpu=False)
        logger.info("EasyOCR reader inizializzato (it/en)")
    return _ocr_reader


def _get_nlp():
    """Carica modello spaCy italiano (lazy loading)."""
    global _nlp
    if _nlp is None:
        import spacy
        try:
            _nlp = spacy.load("it_core_news_sm")
        except OSError:
            logger.error("Modello spaCy 'it_core_news_sm' non trovato. "
                         "Installa con: python -m spacy download it_core_news_sm")
            raise
        logger.info("spaCy it_core_news_sm caricato")
    return _nlp


# === PATTERN REGEX PER IMPORTI ===
IMPORTO_PATTERNS = [
    # €12.50, € 12,50, 12.50€, 12,50 €
    r'€\s*(\d+[.,]\d{2})',
    r'(\d+[.,]\d{2})\s*€',
    # EUR 12.50
    r'EUR\s*(\d+[.,]\d{2})',
    r'(\d+[.,]\d{2})\s*EUR',
    # TOTALE: 12.50 / TOTALE 12,50
    r'(?:TOTALE|TOTAL|TOT\.?)\s*[:\s]*(\d+[.,]\d{2})',
    # IMPORTO: 12.50
    r'(?:IMPORTO|AMOUNT)\s*[:\s]*(\d+[.,]\d{2})',
    # Numero con virgola/punto decimale isolato
    r'\b(\d{1,6}[.,]\d{2})\b',
    # Numero intero (euro senza centesimi) solo se preceduto da indicatori
    r'(?:€|euro|EUR)\s*(\d{1,6})\b',
]

# === PATTERN REGEX PER DATE ===
DATA_PATTERNS = [
    # dd/mm/yyyy o dd-mm-yyyy
    r'(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})',
    # dd/mm/yy
    r'(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2})\b',
]

MESI_IT = {
    'gennaio': 1, 'febbraio': 2, 'marzo': 3, 'aprile': 4,
    'maggio': 5, 'giugno': 6, 'luglio': 7, 'agosto': 8,
    'settembre': 9, 'ottobre': 10, 'novembre': 11, 'dicembre': 12,
    'gen': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'mag': 5, 'giu': 6,
    'lug': 7, 'ago': 8, 'set': 9, 'ott': 10, 'nov': 11, 'dic': 12,
}


def _parse_importo(testo: str) -> Optional[float]:
    """Estrae l'importo dal testo usando regex patterns."""
    testo_upper = testo.upper()
    # Cerca pattern prioritari (TOTALE, €) prima
    for pattern in IMPORTO_PATTERNS:
        matches = re.findall(pattern, testo_upper if 'TOTALE' in pattern.upper() or 'IMPORTO' in pattern.upper()
                             else testo, re.IGNORECASE)
        if matches:
            # Prendi l'ultimo match per TOTALE (di solito è il totale finale)
            val = matches[-1] if 'TOTALE' in pattern.upper() else matches[0]
            try:
                return float(val.replace(',', '.'))
            except (ValueError, AttributeError):
                continue
    return None


def _parse_data(testo: str) -> Optional[date]:
    """Estrae la data dal testo."""
    for pattern in DATA_PATTERNS:
        m = re.search(pattern, testo)
        if m:
            groups = m.groups()
            try:
                giorno = int(groups[0])
                mese = int(groups[1])
                anno = int(groups[2])
                if anno < 100:
                    anno += 2000
                return date(anno, mese, giorno)
            except (ValueError, IndexError):
                continue

    # Cerca date testuali: "5 marzo 2024"
    pattern_testuale = r'(\d{1,2})\s+(' + '|'.join(MESI_IT.keys()) + r')\s+(\d{4})'
    m = re.search(pattern_testuale, testo.lower())
    if m:
        try:
            return date(int(m.group(3)), MESI_IT[m.group(2)], int(m.group(1)))
        except (ValueError, KeyError):
            pass

    return None


def _extract_descrizione_nlp(testo: str, importo: float = None) -> str:
    """Usa spaCy per estrarre una descrizione significativa dal testo."""
    nlp = _get_nlp()
    doc = nlp(testo)

    # Rimuovi cifre/importi e date dal testo per ottenere la descrizione
    parti_utili = []
    for token in doc:
        # Salta punteggiatura, numeri puri, simboli valuta
        if token.is_punct or token.is_currency:
            continue
        if token.like_num:
            continue
        if token.text in ('€', 'EUR', 'euro'):
            continue
        # Salta parole come TOTALE, SCONTRINO, etc.
        if token.text.upper() in ('TOTALE', 'TOTAL', 'TOT', 'SCONTRINO', 'RICEVUTA',
                                   'IVA', 'SUBTOTALE', 'CONTANTE', 'CARTA', 'POS',
                                   'DATA', 'ORA', 'NR', 'N', 'IMPORTO'):
            continue
        if len(token.text) > 1:
            parti_utili.append(token.text)

    descrizione = ' '.join(parti_utili).strip()

    # Se troppo corta, usa il testo originale pulito
    if len(descrizione) < 3:
        descrizione = re.sub(r'[€\d.,/\-]', ' ', testo)
        descrizione = ' '.join(descrizione.split()).strip()

    # Limita lunghezza
    if len(descrizione) > 200:
        descrizione = descrizione[:200].rsplit(' ', 1)[0]

    return descrizione if descrizione else "Spesa generica"


def parse_testo(testo: str) -> dict:
    """
    Analizza testo libero in italiano ed estrae informazioni strutturate.
    Ritorna: {"importo": float|None, "descrizione": str, "data": date|None}
    """
    importo = _parse_importo(testo)
    data = _parse_data(testo)
    descrizione = _extract_descrizione_nlp(testo, importo)

    risultato = {
        "importo": importo,
        "descrizione": descrizione,
        "data": data,
        "testo_originale": testo
    }

    logger.info(f"Parse testo: {risultato}")
    return risultato


async def parse_foto(image_bytes: bytes) -> dict:
    """
    Analizza foto scontrino con EasyOCR e poi estrae dati con NLP.
    Ritorna: {"importo": float|None, "descrizione": str, "data": date|None, "testo_ocr": str}
    """
    try:
        # Converti bytes in immagine PIL
        image = Image.open(io.BytesIO(image_bytes))
        # Converti in RGB se necessario
        if image.mode != 'RGB':
            image = image.convert('RGB')

        # OCR con EasyOCR
        reader = _get_ocr()
        import numpy as np
        img_array = np.array(image)
        risultati_ocr = reader.readtext(img_array)

        # Unisci tutto il testo OCR
        testo_ocr = '\n'.join([r[1] for r in risultati_ocr])
        logger.info(f"OCR testo estratto ({len(testo_ocr)} chars): {testo_ocr[:200]}...")

        if not testo_ocr.strip():
            return {
                "importo": None,
                "descrizione": "Scontrino non leggibile",
                "data": None,
                "testo_ocr": "",
                "errore": "Nessun testo riconosciuto nella foto"
            }

        # Analizza il testo OCR
        risultato = parse_testo(testo_ocr)
        risultato["testo_ocr"] = testo_ocr
        return risultato

    except Exception as e:
        logger.error(f"Errore OCR: {e}")
        return {
            "importo": None,
            "descrizione": "Errore analisi scontrino",
            "data": None,
            "testo_ocr": "",
            "errore": str(e)
        }


def parse_comando_aggiungi(testo: str) -> dict:
    """
    Analizza il testo dopo /aggiungi.
    Formati supportati:
    - /aggiungi 25.50 pizza
    - /aggiungi pizza 25,50
    - /aggiungi 15€ benzina
    - /aggiungi ho speso 30 euro per la spesa al supermercato
    """
    # Rimuovi il comando se presente
    testo = re.sub(r'^/aggiungi\s*', '', testo, flags=re.IGNORECASE).strip()

    if not testo:
        return {"importo": None, "descrizione": None, "data": None}

    return parse_testo(testo)
