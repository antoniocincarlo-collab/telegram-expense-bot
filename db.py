"""
db.py — Connessione PostgreSQL e operazioni CRUD asincrone.
Utilizza asyncpg per connessioni async al database.
"""
import os, logging, uuid, asyncpg
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)
_pool: Optional[asyncpg.Pool] = None


async def init_db():
    """Inizializza il pool di connessioni PostgreSQL e lo schema."""
    global _pool
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL non configurata nel file .env")
    _pool = await asyncpg.create_pool(database_url, min_size=2, max_size=10, command_timeout=60)
    logger.info("Pool PostgreSQL inizializzato")
    # Esegui schema.sql se presente
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            async with _pool.acquire() as conn:
                await conn.execute(f.read())
        logger.info("Schema DB inizializzato")
    except FileNotFoundError:
        logger.warning("schema.sql non trovato")


async def close_db():
    global _pool
    if _pool:
        await _pool.close()
        logger.info("Pool chiuso")


def _p() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database non inizializzato. Chiama init_db().")
    return _pool


# === UTENTI ===
async def upsert_utente(user_id: int, username: str = None):
    async with _p().acquire() as c:
        await c.execute(
            "INSERT INTO utenti (user_id, username) VALUES ($1,$2) ON CONFLICT (user_id) DO UPDATE SET username=$2",
            user_id, username)


async def get_active_group(user_id: int) -> Optional[int]:
    async with _p().acquire() as c:
        r = await c.fetchrow("SELECT active_group_id FROM utenti WHERE user_id=$1", user_id)
        return r["active_group_id"] if r and r["active_group_id"] else None


async def set_active_group(user_id: int, group_id: int):
    async with _p().acquire() as c:
        await c.execute("UPDATE utenti SET active_group_id=$1 WHERE user_id=$2", group_id, user_id)


# === GRUPPI ===
async def crea_gruppo(nome: str, owner_id: int) -> dict:
    token = uuid.uuid4().hex[:16]
    async with _p().acquire() as c:
        async with c.transaction():
            r = await c.fetchrow(
                "INSERT INTO gruppi (nome,owner_id,invite_token) VALUES ($1,$2,$3) RETURNING *",
                nome, owner_id, token)
            gid = r["id"]
            await c.execute("INSERT INTO membri_gruppo (group_id,user_id) VALUES ($1,$2) ON CONFLICT DO NOTHING", gid, owner_id)
            await c.execute("SELECT insert_default_categories($1)", gid)
            await c.execute("UPDATE utenti SET active_group_id=$1 WHERE user_id=$2", gid, owner_id)
            return dict(r)


async def get_gruppo_by_token(token: str) -> Optional[dict]:
    async with _p().acquire() as c:
        r = await c.fetchrow("SELECT * FROM gruppi WHERE invite_token=$1", token)
        return dict(r) if r else None


async def get_gruppi_utente(user_id: int) -> list:
    async with _p().acquire() as c:
        rows = await c.fetch(
            "SELECT g.* FROM gruppi g JOIN membri_gruppo mg ON g.id=mg.group_id WHERE mg.user_id=$1 ORDER BY g.created_at", user_id)
        return [dict(r) for r in rows]


async def aggiungi_membro(group_id: int, user_id: int):
    async with _p().acquire() as c:
        await c.execute("INSERT INTO membri_gruppo (group_id,user_id) VALUES ($1,$2) ON CONFLICT DO NOTHING", group_id, user_id)
        await c.execute("UPDATE utenti SET active_group_id=$1 WHERE user_id=$2", group_id, user_id)


async def is_membro(group_id: int, user_id: int) -> bool:
    async with _p().acquire() as c:
        return await c.fetchrow("SELECT 1 FROM membri_gruppo WHERE group_id=$1 AND user_id=$2", group_id, user_id) is not None


# === CATEGORIE ===
async def get_categorie(group_id: int) -> list:
    async with _p().acquire() as c:
        return [dict(r) for r in await c.fetch("SELECT * FROM categorie WHERE group_id=$1 ORDER BY nome", group_id)]


async def aggiungi_categoria(group_id: int, nome: str) -> Optional[dict]:
    async with _p().acquire() as c:
        try:
            r = await c.fetchrow("INSERT INTO categorie (group_id,nome) VALUES ($1,$2) RETURNING *", group_id, nome)
            return dict(r) if r else None
        except asyncpg.UniqueViolationError:
            return None


async def rinomina_categoria(group_id: int, vecchio: str, nuovo: str) -> bool:
    async with _p().acquire() as c:
        async with c.transaction():
            res = await c.execute("UPDATE categorie SET nome=$1 WHERE group_id=$2 AND nome=$3", nuovo, group_id, vecchio)
            if res == "UPDATE 0":
                return False
            await c.execute("UPDATE spese SET categoria=$1 WHERE group_id=$2 AND categoria=$3", nuovo, group_id, vecchio)
            await c.execute("UPDATE budgets SET categoria=$1 WHERE group_id=$2 AND categoria=$3", nuovo, group_id, vecchio)
            return True


async def elimina_categoria(group_id: int, nome: str) -> bool:
    async with _p().acquire() as c:
        return (await c.execute("DELETE FROM categorie WHERE group_id=$1 AND nome=$2", group_id, nome)) != "DELETE 0"


# === SPESE ===
async def aggiungi_spesa(group_id: int, user_id: int, importo: float,
                         descrizione: str, categoria: str, data_spesa: date = None) -> dict:
    data_spesa = data_spesa or date.today()
    async with _p().acquire() as c:
        async with c.transaction():
            r = await c.fetchrow(
                "INSERT INTO spese (group_id,user_id,data,importo,descrizione,categoria) VALUES ($1,$2,$3,$4,$5,$6) RETURNING *",
                group_id, user_id, data_spesa, importo, descrizione, categoria)
            await c.execute("INSERT INTO ml_data (descrizione,categoria) VALUES ($1,$2)", descrizione, categoria)
            logger.info(f"Spesa: {importo}€ '{descrizione}' [{categoria}] g={group_id} u={user_id}")
            return dict(r)


async def get_spese_mese(group_id: int, anno: int, mese: int) -> list:
    async with _p().acquire() as c:
        rows = await c.fetch(
            "SELECT * FROM spese WHERE group_id=$1 AND EXTRACT(YEAR FROM data)=$2 AND EXTRACT(MONTH FROM data)=$3 ORDER BY data DESC",
            group_id, anno, mese)
        return [dict(r) for r in rows]


async def get_totali_per_categoria(group_id: int, anno: int, mese: int) -> list:
    async with _p().acquire() as c:
        rows = await c.fetch(
            "SELECT categoria, SUM(importo) as totale, COUNT(*) as num_spese FROM spese WHERE group_id=$1 AND EXTRACT(YEAR FROM data)=$2 AND EXTRACT(MONTH FROM data)=$3 GROUP BY categoria ORDER BY totale DESC",
            group_id, anno, mese)
        return [dict(r) for r in rows]


async def get_totale_mese(group_id: int, anno: int, mese: int) -> float:
    async with _p().acquire() as c:
        r = await c.fetchrow(
            "SELECT COALESCE(SUM(importo),0) as totale FROM spese WHERE group_id=$1 AND EXTRACT(YEAR FROM data)=$2 AND EXTRACT(MONTH FROM data)=$3",
            group_id, anno, mese)
        return float(r["totale"])


async def get_spesa_by_id(spesa_id: int, group_id: int) -> Optional[dict]:
    async with _p().acquire() as c:
        r = await c.fetchrow("SELECT * FROM spese WHERE id=$1 AND group_id=$2", spesa_id, group_id)
        return dict(r) if r else None


async def modifica_spesa(spesa_id: int, group_id: int, **kwargs) -> bool:
    campi = {k: v for k, v in kwargs.items() if k in {"importo","descrizione","categoria","data"} and v is not None}
    if not campi:
        return False
    sets, vals = [], []
    for i, (k, v) in enumerate(campi.items(), 1):
        sets.append(f"{k}=${i}")
        vals.append(v)
    vals.extend([spesa_id, group_id])
    async with _p().acquire() as c:
        return (await c.execute(f"UPDATE spese SET {','.join(sets)} WHERE id=${len(vals)-1} AND group_id=${len(vals)}", *vals)) != "UPDATE 0"


async def elimina_spesa(spesa_id: int, group_id: int) -> bool:
    async with _p().acquire() as c:
        return (await c.execute("DELETE FROM spese WHERE id=$1 AND group_id=$2", spesa_id, group_id)) != "DELETE 0"


# === BUDGETS ===
async def set_budget(group_id: int, categoria: str, limite: float) -> dict:
    async with _p().acquire() as c:
        r = await c.fetchrow(
            "INSERT INTO budgets (group_id,categoria,limite_mensile) VALUES ($1,$2,$3) ON CONFLICT (group_id,categoria) DO UPDATE SET limite_mensile=$3 RETURNING *",
            group_id, categoria, limite)
        return dict(r)


async def get_budgets(group_id: int) -> list:
    async with _p().acquire() as c:
        return [dict(r) for r in await c.fetch("SELECT * FROM budgets WHERE group_id=$1 ORDER BY categoria", group_id)]


async def get_budget_categoria(group_id: int, categoria: str) -> Optional[dict]:
    async with _p().acquire() as c:
        r = await c.fetchrow("SELECT * FROM budgets WHERE group_id=$1 AND categoria=$2", group_id, categoria)
        return dict(r) if r else None


async def elimina_budget(group_id: int, categoria: str) -> bool:
    async with _p().acquire() as c:
        return (await c.execute("DELETE FROM budgets WHERE group_id=$1 AND categoria=$2", group_id, categoria)) != "DELETE 0"


# === ML DATA ===
async def get_ml_data() -> list:
    async with _p().acquire() as c:
        return [dict(r) for r in await c.fetch("SELECT descrizione, categoria FROM ml_data ORDER BY id")]


async def get_ml_data_count() -> int:
    async with _p().acquire() as c:
        return (await c.fetchrow("SELECT COUNT(*) as cnt FROM ml_data"))["cnt"]


async def insert_ml_data_batch(records: list):
    async with _p().acquire() as c:
        await c.executemany("INSERT INTO ml_data (descrizione,categoria) VALUES ($1,$2)", records)
        logger.info(f"Inseriti {len(records)} record ML")


# === REPORT ===
async def get_spese_per_utente_mese(group_id: int, anno: int, mese: int) -> list:
    async with _p().acquire() as c:
        rows = await c.fetch(
            "SELECT user_id, SUM(importo) as totale, COUNT(*) as num_spese FROM spese WHERE group_id=$1 AND EXTRACT(YEAR FROM data)=$2 AND EXTRACT(MONTH FROM data)=$3 GROUP BY user_id ORDER BY totale DESC",
            group_id, anno, mese)
        return [dict(r) for r in rows]


async def get_andamento_giornaliero(group_id: int, anno: int, mese: int) -> list:
    async with _p().acquire() as c:
        rows = await c.fetch(
            "SELECT data, SUM(importo) as totale FROM spese WHERE group_id=$1 AND EXTRACT(YEAR FROM data)=$2 AND EXTRACT(MONTH FROM data)=$3 GROUP BY data ORDER BY data",
            group_id, anno, mese)
        return [dict(r) for r in rows]


async def get_media_giornaliera(group_id: int, anno: int, mese: int) -> float:
    async with _p().acquire() as c:
        r = await c.fetchrow(
            "SELECT COALESCE(AVG(dt),0) as media FROM (SELECT SUM(importo) as dt FROM spese WHERE group_id=$1 AND EXTRACT(YEAR FROM data)=$2 AND EXTRACT(MONTH FROM data)=$3 GROUP BY data) s",
            group_id, anno, mese)
        return float(r["media"])
