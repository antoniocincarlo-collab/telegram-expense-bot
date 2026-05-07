"""
psd2.py — Integrazione Tink OAuth e parsing transazioni PSD2.
Usa Tink API sandbox (gratuito) per importare transazioni bancarie.
"""
import os, logging, json
from typing import Optional
from datetime import datetime
import requests

logger = logging.getLogger(__name__)

# Tink API endpoints (sandbox)
TINK_BASE_URL = "https://api.tink.com"
TINK_AUTH_URL = f"{TINK_BASE_URL}/api/v1/oauth/token"
TINK_TRANSACTIONS_URL = f"{TINK_BASE_URL}/data/v2/transactions"
TINK_AUTHORIZE_URL = f"{TINK_BASE_URL}/1.0/authorize"


def _get_credentials() -> tuple:
    """Restituisce le credenziali Tink dal .env."""
    client_id = os.getenv("TINK_CLIENT_ID")
    client_secret = os.getenv("TINK_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise ValueError(
            "TINK_CLIENT_ID e TINK_CLIENT_SECRET devono essere configurati nel .env\n"
            "Registrati su https://console.tink.com per ottenere le credenziali sandbox."
        )
    return client_id, client_secret


def get_auth_token() -> Optional[str]:
    """
    Ottiene un access token dal Tink OAuth.
    Usa client_credentials grant per il sandbox.
    """
    try:
        client_id, client_secret = _get_credentials()

        response = requests.post(TINK_AUTH_URL, data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
            "scope": "transactions:read,accounts:read"
        }, timeout=30)

        response.raise_for_status()
        data = response.json()
        token = data.get("access_token")
        logger.info("Token Tink ottenuto con successo")
        return token

    except requests.exceptions.RequestException as e:
        logger.error(f"Errore autenticazione Tink: {e}")
        return None
    except ValueError as e:
        logger.error(str(e))
        return None


def get_user_auth_url(user_id: str) -> Optional[str]:
    """
    Genera l'URL di autorizzazione per collegare il conto bancario.
    L'utente deve visitare questo link per autorizzare l'accesso.
    """
    try:
        client_id, _ = _get_credentials()
        # In sandbox, generiamo un link per il Tink Link
        tink_link_url = (
            f"https://link.tink.com/1.0/transactions/connect-accounts"
            f"?client_id={client_id}"
            f"&redirect_uri=https://console.tink.com/callback"
            f"&market=IT"
            f"&locale=it_IT"
            f"&state={user_id}"
        )
        return tink_link_url
    except ValueError:
        return None


def fetch_transactions(access_token: str, page_token: str = None) -> dict:
    """
    Recupera le transazioni dall'API Tink.
    Ritorna: {"transazioni": [...], "next_page_token": str|None}
    """
    try:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        params = {"pageSize": 100}
        if page_token:
            params["pageToken"] = page_token

        response = requests.get(
            TINK_TRANSACTIONS_URL,
            headers=headers,
            params=params,
            timeout=30
        )
        response.raise_for_status()
        data = response.json()

        transazioni = []
        for tx in data.get("transactions", []):
            transazioni.append(parse_transaction(tx))

        return {
            "transazioni": transazioni,
            "next_page_token": data.get("nextPageToken")
        }

    except requests.exceptions.RequestException as e:
        logger.error(f"Errore fetch transazioni Tink: {e}")
        return {"transazioni": [], "next_page_token": None}


def parse_transaction(tx: dict) -> dict:
    """
    Converte una transazione Tink nel formato interno.
    """
    # Estrai importo (Tink usa formato con unscaledValue e scale)
    amount = tx.get("amount", {})
    unscaled = float(amount.get("value", {}).get("unscaledValue", 0))
    scale = int(amount.get("value", {}).get("scale", 0))
    importo = abs(unscaled / (10 ** scale))

    # Estrai data
    date_str = tx.get("dates", {}).get("booked", "")
    try:
        data = datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        data = None

    # Descrizione
    descriptions = tx.get("descriptions", {})
    descrizione = (
        descriptions.get("display", "") or
        descriptions.get("original", "") or
        "Transazione PSD2"
    )

    return {
        "importo": importo,
        "descrizione": descrizione,
        "data": data,
        "riferimento": tx.get("id", ""),
        "tipo": tx.get("type", ""),  # EXPENSE, INCOME, TRANSFER
        "stato": tx.get("status", "")
    }


async def importa_transazioni(access_token: str) -> list:
    """
    Importa tutte le transazioni disponibili.
    Ritorna lista di transazioni nel formato interno.
    """
    tutte_transazioni = []
    page_token = None

    while True:
        risultato = fetch_transactions(access_token, page_token)
        transazioni = risultato["transazioni"]

        if not transazioni:
            break

        # Filtra solo le spese (importi negativi nel conto = spese)
        spese = [t for t in transazioni if t.get("tipo") == "EXPENSE"]
        tutte_transazioni.extend(spese)

        page_token = risultato["next_page_token"]
        if not page_token:
            break

    logger.info(f"Importate {len(tutte_transazioni)} transazioni da Tink")
    return tutte_transazioni


def format_transazioni_preview(transazioni: list, limit: int = 10) -> str:
    """Formatta un'anteprima delle transazioni per Telegram."""
    if not transazioni:
        return "Nessuna transazione trovata."

    testo = f"📥 *Trovate {len(transazioni)} transazioni*\n\n"

    for i, t in enumerate(transazioni[:limit]):
        data_str = t['data'].strftime('%d/%m') if t['data'] else 'N/D'
        testo += (
            f"{i+1}. {data_str} — €{t['importo']:.2f}\n"
            f"   _{t['descrizione'][:50]}_\n"
        )

    if len(transazioni) > limit:
        testo += f"\n...e altre {len(transazioni) - limit} transazioni"

    testo += "\n\nConferma l'importazione? Usa i pulsanti sotto."
    return testo
