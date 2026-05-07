"""
budgets.py — Logica limiti mensili e avvisi automatici.
Genera avvisi quando la spesa supera soglie del budget.
"""
import logging
from datetime import date
from typing import Optional
import db

logger = logging.getLogger(__name__)

# Soglie per gli avvisi (percentuali)
SOGLIE_AVVISO = [50, 75, 90, 100]


async def controlla_budget(group_id: int, categoria: str) -> Optional[dict]:
    """
    Controlla lo stato del budget per una categoria.
    Ritorna info su budget, speso, percentuale e avviso.
    """
    budget = await db.get_budget_categoria(group_id, categoria)
    if not budget:
        return None

    oggi = date.today()
    speso = await _get_speso_categoria_mese(group_id, categoria, oggi.year, oggi.month)
    limite = float(budget["limite_mensile"])
    percentuale = (speso / limite * 100) if limite > 0 else 0

    # Determina livello avviso
    avviso = None
    for soglia in reversed(SOGLIE_AVVISO):
        if percentuale >= soglia:
            avviso = soglia
            break

    return {
        "categoria": categoria,
        "limite": limite,
        "speso": speso,
        "rimanente": max(0, limite - speso),
        "percentuale": round(percentuale, 1),
        "avviso": avviso,
        "superato": percentuale >= 100
    }


async def controlla_tutti_budget(group_id: int) -> list:
    """Controlla tutti i budget di un gruppo per il mese corrente."""
    budgets = await db.get_budgets(group_id)
    oggi = date.today()
    risultati = []

    for b in budgets:
        cat = b["categoria"]
        limite = float(b["limite_mensile"])
        speso = await _get_speso_categoria_mese(group_id, cat, oggi.year, oggi.month)
        perc = (speso / limite * 100) if limite > 0 else 0

        avviso = None
        for soglia in reversed(SOGLIE_AVVISO):
            if perc >= soglia:
                avviso = soglia
                break

        risultati.append({
            "categoria": cat,
            "limite": limite,
            "speso": round(speso, 2),
            "rimanente": round(max(0, limite - speso), 2),
            "percentuale": round(perc, 1),
            "avviso": avviso,
            "superato": perc >= 100
        })

    return risultati


async def genera_avviso_spesa(group_id: int, categoria: str, importo_aggiunto: float) -> Optional[str]:
    """
    Genera messaggio di avviso dopo l'aggiunta di una spesa.
    Controlla se la spesa ha fatto superare una soglia.
    """
    budget = await db.get_budget_categoria(group_id, categoria)
    if not budget:
        return None

    oggi = date.today()
    speso_totale = await _get_speso_categoria_mese(group_id, categoria, oggi.year, oggi.month)
    speso_prima = speso_totale - importo_aggiunto
    limite = float(budget["limite_mensile"])

    if limite <= 0:
        return None

    perc_prima = (speso_prima / limite * 100)
    perc_dopo = (speso_totale / limite * 100)

    # Verifica se abbiamo superato una soglia
    for soglia in SOGLIE_AVVISO:
        if perc_prima < soglia <= perc_dopo:
            if soglia >= 100:
                return (
                    f"🚨 *BUDGET SUPERATO!*\n"
                    f"Categoria: *{categoria}*\n"
                    f"Speso: €{speso_totale:.2f} / €{limite:.2f}\n"
                    f"Superamento: €{speso_totale - limite:.2f} oltre il limite!"
                )
            else:
                emoji = "⚠️" if soglia >= 75 else "📊"
                return (
                    f"{emoji} *Avviso budget {soglia}%*\n"
                    f"Categoria: *{categoria}*\n"
                    f"Speso: €{speso_totale:.2f} / €{limite:.2f} ({perc_dopo:.0f}%)\n"
                    f"Rimanente: €{max(0, limite - speso_totale):.2f}"
                )

    return None


def format_barra_progresso(percentuale: float, lunghezza: int = 20) -> str:
    """Genera una barra di progresso testuale."""
    riempiti = int(min(percentuale, 100) / 100 * lunghezza)
    vuoti = lunghezza - riempiti

    if percentuale >= 100:
        barra = "🟥" * riempiti
    elif percentuale >= 75:
        barra = "🟧" * riempiti + "⬜" * vuoti
    elif percentuale >= 50:
        barra = "🟨" * riempiti + "⬜" * vuoti
    else:
        barra = "🟩" * riempiti + "⬜" * vuoti

    return f"{barra} {percentuale:.0f}%"


async def format_panoramica_budget(group_id: int) -> str:
    """Formatta la panoramica di tutti i budget per il messaggio Telegram."""
    risultati = await controlla_tutti_budget(group_id)

    if not risultati:
        return "📋 Nessun budget impostato.\nUsa /budget per impostarne uno."

    oggi = date.today()
    testo = f"📊 *Budget — {oggi.strftime('%B %Y').title()}*\n\n"

    for r in risultati:
        emoji = "🟢"
        if r["superato"]:
            emoji = "🔴"
        elif r["avviso"] and r["avviso"] >= 75:
            emoji = "🟡"

        barra = format_barra_progresso(r["percentuale"], 10)
        testo += (
            f"{emoji} *{r['categoria']}*\n"
            f"  {barra}\n"
            f"  €{r['speso']:.2f} / €{r['limite']:.2f}"
            f" (rimangono €{r['rimanente']:.2f})\n\n"
        )

    return testo


async def _get_speso_categoria_mese(group_id: int, categoria: str,
                                      anno: int, mese: int) -> float:
    """Calcola il totale speso per una categoria in un mese."""
    totali = await db.get_totali_per_categoria(group_id, anno, mese)
    for t in totali:
        if t["categoria"] == categoria:
            return float(t["totale"])
    return 0.0


async def proiezione_fine_mese(group_id: int) -> dict:
    """
    Calcola la proiezione di spesa a fine mese basata sull'andamento attuale.
    """
    oggi = date.today()
    giorno_corrente = oggi.day

    # Totale speso finora
    totale_attuale = await db.get_totale_mese(group_id, oggi.year, oggi.month)

    # Giorni nel mese
    import calendar
    giorni_mese = calendar.monthrange(oggi.year, oggi.month)[1]

    # Media giornaliera
    media_giornaliera = totale_attuale / giorno_corrente if giorno_corrente > 0 else 0

    # Proiezione
    proiezione = media_giornaliera * giorni_mese

    return {
        "totale_attuale": round(totale_attuale, 2),
        "media_giornaliera": round(media_giornaliera, 2),
        "proiezione_fine_mese": round(proiezione, 2),
        "giorni_passati": giorno_corrente,
        "giorni_totali": giorni_mese,
        "giorni_rimanenti": giorni_mese - giorno_corrente
    }
