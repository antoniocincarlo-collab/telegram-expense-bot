"""
gruppi.py — Gestione gruppi famiglia e inviti.
Permette di creare gruppi, invitare utenti e gestire i membri.
"""
import logging
from typing import Optional
import db

logger = logging.getLogger(__name__)


async def ensure_user_group(user_id: int, username: str = None) -> int:
    """
    Assicura che l'utente abbia un gruppo attivo.
    Se non ne ha, crea un gruppo personale.
    Ritorna il group_id attivo.
    """
    await db.upsert_utente(user_id, username)
    group_id = await db.get_active_group(user_id)

    if group_id is None:
        # Crea gruppo personale
        nome = f"Personale_{username or user_id}"
        gruppo = await db.crea_gruppo(nome, user_id)
        group_id = gruppo["id"]
        logger.info(f"Creato gruppo personale '{nome}' per utente {user_id}")

    return group_id


async def crea_gruppo_famiglia(nome: str, owner_id: int, username: str = None) -> dict:
    """Crea un nuovo gruppo famiglia."""
    await db.upsert_utente(owner_id, username)
    gruppo = await db.crea_gruppo(nome, owner_id)
    logger.info(f"Gruppo famiglia '{nome}' creato da {owner_id}")
    return gruppo


async def genera_link_invito(group_id: int, user_id: int) -> Optional[str]:
    """
    Genera il link di invito per un gruppo.
    Solo il proprietario o un membro può generare inviti.
    """
    if not await db.is_membro(group_id, user_id):
        return None

    gruppi = await db.get_gruppi_utente(user_id)
    for g in gruppi:
        if g["id"] == group_id:
            return g["invite_token"]
    return None


async def accetta_invito(token: str, user_id: int, username: str = None) -> Optional[dict]:
    """
    Accetta un invito e aggiunge l'utente al gruppo.
    Ritorna il gruppo se l'invito è valido.
    """
    await db.upsert_utente(user_id, username)
    gruppo = await db.get_gruppo_by_token(token)

    if not gruppo:
        logger.warning(f"Token invito non valido: {token}")
        return None

    # Verifica se già membro
    if await db.is_membro(gruppo["id"], user_id):
        logger.info(f"Utente {user_id} già membro del gruppo {gruppo['id']}")
        return gruppo

    await db.aggiungi_membro(gruppo["id"], user_id)
    logger.info(f"Utente {user_id} aggiunto al gruppo '{gruppo['nome']}'")
    return gruppo


async def get_info_gruppo(group_id: int) -> Optional[dict]:
    """Restituisce informazioni dettagliate su un gruppo."""
    gruppi_all = await db.get_gruppi_utente(0)  # Non va bene, serve query diretta
    # Usiamo una query diretta
    pool = db._get_pool()
    async with pool.acquire() as conn:
        gruppo = await conn.fetchrow("SELECT * FROM gruppi WHERE id=$1", group_id)
        if not gruppo:
            return None

        membri = await conn.fetch(
            "SELECT user_id FROM membri_gruppo WHERE group_id=$1", group_id)
        categorie = await conn.fetch(
            "SELECT nome FROM categorie WHERE group_id=$1 ORDER BY nome", group_id)

    return {
        "id": gruppo["id"],
        "nome": gruppo["nome"],
        "owner_id": gruppo["owner_id"],
        "invite_token": gruppo["invite_token"],
        "membri": [m["user_id"] for m in membri],
        "num_membri": len(membri),
        "categorie": [c["nome"] for c in categorie]
    }


async def cambia_gruppo_attivo(user_id: int, group_id: int) -> bool:
    """Cambia il gruppo attivo dell'utente."""
    if not await db.is_membro(group_id, user_id):
        return False
    await db.set_active_group(user_id, group_id)
    return True


async def lista_gruppi_formattata(user_id: int) -> str:
    """Formatta la lista gruppi per il messaggio Telegram."""
    gruppi = await db.get_gruppi_utente(user_id)
    active = await db.get_active_group(user_id)

    if not gruppi:
        return "Non fai parte di nessun gruppo."

    testo = "👥 *I tuoi gruppi:*\n\n"
    for g in gruppi:
        marker = "✅" if g["id"] == active else "⬜"
        testo += f"{marker} *{g['nome']}* (ID: {g['id']})\n"

    testo += "\nUsa /gruppo <id> per cambiare gruppo attivo."
    return testo
