"""
main.py — Entry point bot Telegram, handler comandi aiogram 3.x
"""
import os, sys, logging, asyncio, csv as csv_mod, io
from datetime import date, datetime
from dotenv import load_dotenv

load_dotenv()

from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (Message, CallbackQuery, BufferedInputFile,
                            InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile)
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

import db, ml, budgets, gruppi, export, ocr_nlp, psd2

# === Logging ===
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger(__name__)

# === Bot setup ===
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    sys.exit("TELEGRAM_BOT_TOKEN mancante nel .env")

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher()
router = Router()
dp.include_router(router)


# === Helper: garantisce gruppo attivo ===
async def _gid(msg: Message) -> int:
    uid = msg.from_user.id
    uname = msg.from_user.username
    return await gruppi.ensure_user_group(uid, uname)


# ===================== /start (con deep link per inviti) =====================
@router.message(CommandStart())
async def cmd_start(msg: Message, command: CommandObject = None):
    # Gestisci deep link per inviti: /start join_TOKEN
    if command and command.args and command.args.startswith("join_"):
        token = command.args[5:]
        gruppo = await gruppi.accetta_invito(token, msg.from_user.id, msg.from_user.username)
        if gruppo:
            await msg.answer(f"✅ Sei entrato nel gruppo *{gruppo['nome']}*!")
        else:
            await msg.answer("❌ Link invito non valido o scaduto.")
        return

    gid = await _gid(msg)
    await msg.answer(
        "👋 *Benvenuto nel Bot Spese!*\n\n"
        "Comandi disponibili:\n"
        "/aggiungi — Aggiungi spesa (testo o foto)\n"
        "/panoramica — Riepilogo mensile\n"
        "/categoria — Gestisci categorie\n"
        "/budget — Gestisci budget mensili\n"
        "/invita — Invita al gruppo famiglia\n"
        "/gruppo — Cambia gruppo attivo\n"
        "/addestra\\_ml — Addestra modello ML\n"
        "/esporta — Esporta PDF/CSV\n"
        "/importa\\_psd2 — Importa da banca\n"
        "/help — Mostra aiuto\n\n"
        f"📌 Gruppo attivo ID: {gid}\n"
        "Puoi anche inviare direttamente un messaggio di testo o una foto "
        "di uno scontrino per aggiungere una spesa!")


# ===================== /help =====================
@router.message(Command("help"))
async def cmd_help(msg: Message):
    await msg.answer(
        "📖 *Guida Bot Spese*\n\n"
        "*Aggiungere spese:*\n"
        "• `/aggiungi 25.50 pizza` — importo + descrizione\n"
        "• Invia testo libero: _ho speso 30€ al supermercato_\n"
        "• Invia foto scontrino\n\n"
        "*Report:*\n"
        "• `/panoramica` — riepilogo mese corrente\n"
        "• `/esporta pdf` o `/esporta csv`\n"
        "• `/esporta pdf 2024-03` — mese specifico\n\n"
        "*Budget:*\n"
        "• `/budget Cibo 300` — imposta limite\n"
        "• `/budget` — vedi tutti i budget\n\n"
        "*Categorie:*\n"
        "• `/categoria aggiungi Abbigliamento`\n"
        "• `/categoria rinomina Cibo Alimentari`\n"
        "• `/categoria elimina NomeCategoria`\n\n"
        "*Famiglia:*\n"
        "• `/invita` — genera link invito\n"
        "• `/gruppo` — lista e cambia gruppo")


# ===================== /aggiungi =====================
@router.message(Command("aggiungi"))
async def cmd_aggiungi(msg: Message):
    gid = await _gid(msg)
    testo = msg.text.replace("/aggiungi", "", 1).strip()
    if not testo:
        await msg.answer("💡 Uso: `/aggiungi 25.50 pizza`\nOppure invia un messaggio libero o una foto.")
        return
    await _processa_testo_spesa(msg, gid, testo)


async def _processa_testo_spesa(msg: Message, gid: int, testo: str):
    """Processa testo e salva la spesa."""
    parsed = ocr_nlp.parse_testo(testo)
    importo = parsed.get("importo")
    descrizione = parsed.get("descrizione", "Spesa generica")
    data_spesa = parsed.get("data")

    # Se NLP locale non trova l'importo, prova Groq
    if importo is None:
        groq_result = await ml.groq_parse_spesa(testo)
        if groq_result:
            importo = groq_result.get("importo")
            if not descrizione or descrizione == "Spesa generica":
                descrizione = groq_result.get("descrizione", descrizione)
            if not data_spesa and groq_result.get("data"):
                try:
                    data_spesa = datetime.strptime(groq_result["data"], "%Y-%m-%d").date()
                except (ValueError, TypeError):
                    pass

    if importo is None:
        await msg.answer("❌ Non riesco a trovare l'importo.\nProva: `/aggiungi 25.50 pizza`")
        return

    # Categorizzazione ML
    cats = await db.get_categorie(gid)
    cat_names = [c["nome"] for c in cats] if cats else None
    categoria, metodo = await ml.predict_with_fallback(descrizione, cat_names)

    spesa = await db.aggiungi_spesa(gid, msg.from_user.id, importo, descrizione, categoria, data_spesa)

    emoji_metodo = {"ml": "🤖", "groq": "🧠", "default": "📋"}.get(metodo, "📋")
    data_str = (data_spesa or date.today()).strftime("%d/%m/%Y")

    risposta = (
        f"✅ *Spesa registrata!*\n\n"
        f"💰 Importo: €{importo:.2f}\n"
        f"📝 Descrizione: {descrizione}\n"
        f"🏷️ Categoria: {categoria} {emoji_metodo}\n"
        f"📅 Data: {data_str}\n"
        f"🆔 ID: #{spesa['id']}"
    )

    # Controlla budget
    avviso = await budgets.genera_avviso_spesa(gid, categoria, importo)
    if avviso:
        risposta += f"\n\n{avviso}"

    # Pulsante modifica categoria
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✏️ Cambia categoria", callback_data=f"chcat_{spesa['id']}")
    ]])
    await msg.answer(risposta, reply_markup=kb)


# ===================== Foto scontrino =====================
@router.message(F.photo)
async def handle_foto(msg: Message):
    gid = await _gid(msg)
    await msg.answer("📸 Analizzo lo scontrino...")

    photo = msg.photo[-1]  # Massima risoluzione
    file = await bot.get_file(photo.file_id)
    data = io.BytesIO()
    await bot.download_file(file.file_path, data)

    parsed = await ocr_nlp.parse_foto(data.getvalue())

    if parsed.get("errore"):
        await msg.answer(f"❌ {parsed['errore']}\nProva con `/aggiungi importo descrizione`.")
        return

    importo = parsed.get("importo")
    if importo is None:
        testo_ocr = parsed.get("testo_ocr", "")
        groq_result = await ml.groq_parse_spesa(testo_ocr)
        if groq_result and groq_result.get("importo"):
            importo = groq_result["importo"]
            parsed["descrizione"] = groq_result.get("descrizione", parsed.get("descrizione"))

    if importo is None:
        ocr_text = parsed.get("testo_ocr", "N/D")[:300]
        await msg.answer(f"❌ Importo non trovato nello scontrino.\n\nTesto OCR:\n`{ocr_text}`\n\nProva `/aggiungi importo descrizione`.")
        return

    descrizione = parsed.get("descrizione", "Scontrino")
    data_spesa = parsed.get("data")
    cats = await db.get_categorie(gid)
    cat_names = [c["nome"] for c in cats] if cats else None
    categoria, metodo = await ml.predict_with_fallback(descrizione, cat_names)

    spesa = await db.aggiungi_spesa(gid, msg.from_user.id, importo, descrizione, categoria, data_spesa)

    data_str = (data_spesa or date.today()).strftime("%d/%m/%Y")
    risposta = (
        f"✅ *Spesa da scontrino registrata!*\n\n"
        f"💰 €{importo:.2f}\n📝 {descrizione}\n🏷️ {categoria}\n📅 {data_str}\n🆔 #{spesa['id']}"
    )
    avviso = await budgets.genera_avviso_spesa(gid, categoria, importo)
    if avviso:
        risposta += f"\n\n{avviso}"

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✏️ Cambia categoria", callback_data=f"chcat_{spesa['id']}")
    ]])
    await msg.answer(risposta, reply_markup=kb)


# ===================== Testo libero =====================
@router.message(F.text & ~F.text.startswith("/"))
async def handle_testo_libero(msg: Message):
    gid = await _gid(msg)
    await _processa_testo_spesa(msg, gid, msg.text)


# ===================== /panoramica =====================
@router.message(Command("panoramica"))
async def cmd_panoramica(msg: Message):
    gid = await _gid(msg)
    oggi = date.today()

    totali = await db.get_totali_per_categoria(gid, oggi.year, oggi.month)
    totale = await db.get_totale_mese(gid, oggi.year, oggi.month)
    proiezione = await budgets.proiezione_fine_mese(gid)

    if not totali:
        await msg.answer("📊 Nessuna spesa registrata questo mese.")
        return

    testo = f"📊 *Panoramica — {oggi.strftime('%B %Y').title()}*\n\n"
    testo += f"💰 *Totale: €{totale:.2f}*\n"
    testo += f"📈 Media giornaliera: €{proiezione['media_giornaliera']:.2f}\n"
    testo += f"🔮 Proiezione fine mese: €{proiezione['proiezione_fine_mese']:.2f}\n\n"
    testo += "*Per categoria:*\n"
    for t in totali:
        perc = (float(t['totale']) / totale * 100) if totale > 0 else 0
        testo += f"  • {t['categoria']}: €{float(t['totale']):.2f} ({perc:.0f}%)\n"

    await msg.answer(testo)

    # Invia grafici
    try:
        pie = await export.genera_grafico_torta(gid, oggi.year, oggi.month)
        await msg.answer_photo(BufferedInputFile(pie.read(), "panoramica.png"))
    except Exception as e:
        logger.warning(f"Grafico torta non generato: {e}")

    # Budget
    budget_text = await budgets.format_panoramica_budget(gid)
    await msg.answer(budget_text)

    try:
        budget_chart = await export.genera_grafico_budget(gid)
        await msg.answer_photo(BufferedInputFile(budget_chart.read(), "budget.png"))
    except Exception as e:
        logger.warning(f"Grafico budget non generato: {e}")


# ===================== /categoria =====================
@router.message(Command("categoria"))
async def cmd_categoria(msg: Message):
    gid = await _gid(msg)
    args = msg.text.replace("/categoria", "", 1).strip().split(None, 2)

    if not args:
        cats = await db.get_categorie(gid)
        lista = "\n".join([f"  • {c['nome']}" for c in cats]) if cats else "Nessuna"
        await msg.answer(f"🏷️ *Categorie:*\n{lista}\n\n"
                         "Usa:\n`/categoria aggiungi Nome`\n`/categoria rinomina Vecchio Nuovo`\n"
                         "`/categoria elimina Nome`")
        return

    azione = args[0].lower()
    if azione == "aggiungi" and len(args) >= 2:
        nome = args[1]
        r = await db.aggiungi_categoria(gid, nome)
        if r:
            await msg.answer(f"✅ Categoria *{nome}* aggiunta!")
        else:
            await msg.answer(f"⚠️ Categoria *{nome}* già esistente.")
    elif azione == "rinomina" and len(args) >= 3:
        ok = await db.rinomina_categoria(gid, args[1], args[2])
        if ok:
            await msg.answer(f"✅ *{args[1]}* → *{args[2]}*")
        else:
            await msg.answer(f"❌ Categoria *{args[1]}* non trovata.")
    elif azione == "elimina" and len(args) >= 2:
        ok = await db.elimina_categoria(gid, args[1])
        await msg.answer(f"✅ Eliminata." if ok else f"❌ Non trovata.")
    else:
        await msg.answer("❓ Uso: `/categoria aggiungi|rinomina|elimina ...`")


# ===================== /modifica =====================
@router.message(Command("modifica"))
async def cmd_modifica(msg: Message):
    gid = await _gid(msg)
    args = msg.text.replace("/modifica", "", 1).strip().split(None, 2)
    if len(args) < 3:
        await msg.answer("✏️ Uso: `/modifica ID campo valore`\nCampi: importo, descrizione, categoria")
        return
    try:
        sid = int(args[0])
    except ValueError:
        await msg.answer("❌ ID spesa non valido.")
        return
    campo, valore = args[1].lower(), args[2]
    kwargs = {}
    if campo == "importo":
        kwargs["importo"] = float(valore.replace(",", "."))
    elif campo == "descrizione":
        kwargs["descrizione"] = valore
    elif campo == "categoria":
        kwargs["categoria"] = valore
    else:
        await msg.answer("❌ Campo non valido. Usa: importo, descrizione, categoria")
        return
    ok = await db.modifica_spesa(sid, gid, **kwargs)
    await msg.answer(f"✅ Spesa #{sid} aggiornata!" if ok else f"❌ Spesa #{sid} non trovata.")


# ===================== /budget =====================
@router.message(Command("budget"))
async def cmd_budget(msg: Message):
    gid = await _gid(msg)
    args = msg.text.replace("/budget", "", 1).strip().split()

    if not args:
        testo = await budgets.format_panoramica_budget(gid)
        await msg.answer(testo)
        return

    if len(args) >= 2:
        cat = args[0]
        try:
            limite = float(args[1].replace(",", "."))
        except ValueError:
            await msg.answer("❌ Limite non valido. Uso: `/budget Cibo 300`")
            return
        await db.set_budget(gid, cat, limite)
        await msg.answer(f"✅ Budget *{cat}*: €{limite:.2f}/mese")
    else:
        await msg.answer("💡 Uso: `/budget Categoria Limite`\nEs: `/budget Cibo 300`")


# ===================== /invita =====================
@router.message(Command("invita"))
async def cmd_invita(msg: Message):
    gid = await _gid(msg)
    token = await gruppi.genera_link_invito(gid, msg.from_user.id)
    if token:
        bot_info = await bot.get_me()
        link = f"https://t.me/{bot_info.username}?start=join_{token}"
        await msg.answer(f"🔗 *Link invito gruppo:*\n{link}\n\nCondividi questo link!")
    else:
        await msg.answer("❌ Non puoi generare inviti per questo gruppo.")


# (Deep link /start join_ gestito dentro cmd_start sopra)


# ===================== /gruppo =====================
@router.message(Command("gruppo"))
async def cmd_gruppo(msg: Message):
    args = msg.text.replace("/gruppo", "", 1).strip()
    uid = msg.from_user.id

    if args:
        try:
            new_gid = int(args)
            ok = await gruppi.cambia_gruppo_attivo(uid, new_gid)
            if ok:
                await msg.answer(f"✅ Gruppo attivo cambiato a ID {new_gid}")
            else:
                await msg.answer("❌ Non sei membro di quel gruppo.")
        except ValueError:
            # Crea nuovo gruppo
            gruppo = await gruppi.crea_gruppo_famiglia(args, uid, msg.from_user.username)
            await msg.answer(f"✅ Gruppo *{args}* creato! (ID: {gruppo['id']})")
        return

    testo = await gruppi.lista_gruppi_formattata(uid)
    await msg.answer(testo)


# ===================== /addestra_ml =====================
@router.message(Command("addestra_ml"))
async def cmd_addestra(msg: Message):
    await msg.answer("🤖 Avvio training ML...")
    data = await db.get_ml_data()
    if len(data) < 5:
        await msg.answer(f"❌ Servono almeno 5 esempi. Attuali: {len(data)}")
        return
    desc = [d["descrizione"] for d in data]
    cats = [d["categoria"] for d in data]
    stats = ml.train(desc, cats)
    if "errore" in stats:
        await msg.answer(f"❌ {stats['errore']}")
    else:
        acc = stats.get('accuracy_media', 'N/D')
        await msg.answer(
            f"✅ *Modello addestrato!*\n"
            f"📊 Esempi: {stats['num_esempi']}\n"
            f"🏷️ Categorie: {stats['num_categorie']}\n"
            f"🎯 Accuracy: {acc}")


# ===================== /esporta =====================
@router.message(Command("esporta"))
async def cmd_esporta(msg: Message):
    gid = await _gid(msg)
    args = msg.text.replace("/esporta", "", 1).strip().split()
    formato = args[0].lower() if args else "pdf"
    oggi = date.today()
    anno, mese = oggi.year, oggi.month

    if len(args) >= 2:
        try:
            parts = args[1].split("-")
            anno, mese = int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            await msg.answer("❌ Formato data: YYYY-MM (es. 2024-03)")
            return

    await msg.answer(f"📄 Genero export {formato.upper()} per {mese:02d}/{anno}...")

    try:
        if formato == "csv":
            buf = await export.genera_csv(gid, anno, mese)
            fname = f"spese_{anno}_{mese:02d}.csv"
            await msg.answer_document(BufferedInputFile(buf.read(), fname))
        else:
            buf = await export.genera_pdf(gid, anno, mese)
            fname = f"report_{anno}_{mese:02d}.pdf"
            await msg.answer_document(BufferedInputFile(buf.read(), fname))
    except Exception as e:
        logger.error(f"Errore export: {e}")
        await msg.answer(f"❌ Errore generazione: {e}")


# ===================== /importa_psd2 =====================
@router.message(Command("importa_psd2"))
async def cmd_importa_psd2(msg: Message):
    try:
        url = psd2.get_user_auth_url(str(msg.from_user.id))
        if url:
            await msg.answer(
                f"🏦 *Importazione PSD2*\n\n"
                f"1. Collega il tuo conto:\n{url}\n\n"
                f"2. Dopo l'autorizzazione, usa:\n`/importa_fetch`")
        else:
            await msg.answer("❌ Tink non configurato. Imposta TINK\\_CLIENT\\_ID nel .env")
    except Exception as e:
        await msg.answer(f"❌ Errore: {e}")


# ===================== Callback cambia categoria =====================
@router.callback_query(F.data.startswith("chcat_"))
async def cb_cambia_cat(cb: CallbackQuery):
    sid = int(cb.data.split("_")[1])
    uid = cb.from_user.id
    gid = await db.get_active_group(uid)
    if not gid:
        await cb.answer("Errore: nessun gruppo attivo")
        return
    cats = await db.get_categorie(gid)
    buttons = []
    row = []
    for c in cats:
        row.append(InlineKeyboardButton(text=c["nome"], callback_data=f"setcat_{sid}_{c['nome']}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await cb.message.edit_reply_markup(reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("setcat_"))
async def cb_set_cat(cb: CallbackQuery):
    parts = cb.data.split("_", 2)
    sid, cat = int(parts[1]), parts[2]
    uid = cb.from_user.id
    gid = await db.get_active_group(uid)
    if gid:
        await db.modifica_spesa(sid, gid, categoria=cat)
        await cb.message.edit_text(cb.message.text + f"\n\n✏️ Categoria aggiornata: *{cat}*")
    await cb.answer("Categoria aggiornata!")


# ===================== Startup / Shutdown =====================
async def on_startup():
    await db.init_db()
    # Carica dataset iniziale se ml_data è vuoto
    count = await db.get_ml_data_count()
    if count == 0:
        csv_path = os.path.join(os.path.dirname(__file__), "dataset_sample.csv")
        if os.path.exists(csv_path):
            records = []
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv_mod.DictReader(f)
                for row in reader:
                    records.append((row["descrizione"], row["categoria"]))
            if records:
                await db.insert_ml_data_batch(records)
                logger.info(f"Dataset iniziale caricato: {len(records)} record")
    # Prova training iniziale
    data = await db.get_ml_data()
    if len(data) >= 5:
        ml.train([d["descrizione"] for d in data], [d["categoria"] for d in data])
    logger.info("Bot avviato!")


async def on_shutdown():
    await db.close_db()
    logger.info("Bot fermato.")


async def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
