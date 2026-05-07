# 🧾 Telegram Expense Bot

Bot Telegram avanzato per il tracking delle spese personali e familiari.
100% gratuito — nessun servizio a pagamento.

## ✨ Funzionalità

- **Aggiungi spesa** — Testo libero, comando strutturato, o foto scontrino
- **OCR scontrini** — EasyOCR con supporto italiano nativo
- **NLP parsing** — spaCy per estrazione automatica importo/descrizione/data
- **ML auto-categorizzazione** — TF-IDF + LinearSVC con fallback Groq API
- **Panoramica** — Grafici torta, barre budget, proiezioni fine mese
- **Budget mensili** — Limiti per categoria con avvisi automatici a soglie 50/75/90/100%
- **Gruppi famiglia** — Condivisione spese tramite link invito
- **Export PDF/CSV** — Report mensili con tabelle e grafici
- **Import PSD2** — Transazioni bancarie via Tink API sandbox

## 🛠️ Stack Tecnologico

| Layer | Tecnologia |
|-------|-----------|
| Bot framework | aiogram 3.x |
| Database | PostgreSQL + asyncpg |
| OCR | EasyOCR (locale) |
| NLP | spaCy it_core_news_sm |
| ML | scikit-learn (TF-IDF + LinearSVC) |
| LLM fallback | Groq API (llama-3.1-8b-instant, free) |
| Grafici | Matplotlib |
| PDF | reportlab |
| CSV | pandas |
| PSD2 | Tink API sandbox |

## 📋 Prerequisiti

- Python 3.10+
- PostgreSQL (locale o servizio gratuito: Render, Supabase, Neon)
- Account Telegram (per creare il bot)
- Account Groq (opzionale, per fallback ML)
- Account Tink (opzionale, per import PSD2)

## 🚀 Setup Locale

### 1. Clona e installa dipendenze

```bash
git clone <repo-url>
cd telegram-expense-bot
pip install -r requirements.txt
python -m spacy download it_core_news_sm
```

### 2. Configura variabili d'ambiente

```bash
cp .env.example .env
# Modifica .env con i tuoi valori
```

**Variabili obbligatorie:**

| Variabile | Dove ottenerla |
|-----------|---------------|
| `TELEGRAM_BOT_TOKEN` | [@BotFather](https://t.me/BotFather) su Telegram |
| `DATABASE_URL` | Il tuo PostgreSQL (es. `postgresql://user:pass@localhost:5432/expense_bot`) |

**Variabili opzionali:**

| Variabile | Dove ottenerla |
|-----------|---------------|
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) |
| `TINK_CLIENT_ID` | [tink.com/developers](https://tink.com/developers) |
| `TINK_CLIENT_SECRET` | [tink.com/developers](https://tink.com/developers) |

### 3. Crea il database

```bash
createdb expense_bot
psql expense_bot < schema.sql
```

Oppure il bot crea automaticamente le tabelle al primo avvio.

### 4. Avvia il bot

```bash
python main.py
```

## 🤖 Comandi Bot

| Comando | Descrizione |
|---------|------------|
| `/start` | Benvenuto e setup iniziale |
| `/aggiungi 25.50 pizza` | Aggiungi spesa |
| `/panoramica` | Riepilogo mensile con grafici |
| `/categoria` | Lista/aggiungi/rinomina/elimina categorie |
| `/modifica ID campo valore` | Modifica una spesa |
| `/budget Cibo 300` | Imposta budget mensile |
| `/invita` | Genera link invito gruppo |
| `/gruppo` | Lista gruppi / cambia attivo |
| `/addestra_ml` | Addestra modello categorizzazione |
| `/esporta pdf` o `/esporta csv` | Export mensile |
| `/esporta pdf 2024-03` | Export mese specifico |
| `/importa_psd2` | Importa transazioni bancarie |
| `/help` | Guida completa |

**Input naturale:** Puoi anche inviare direttamente un messaggio di testo
(es. _"ho speso 30€ al supermercato"_) o una foto di uno scontrino.

## 🧠 Come funziona l'ML

1. Il dataset iniziale (`dataset_sample.csv`, ~200 esempi) viene caricato al primo avvio
2. Ogni nuova spesa viene salvata in `ml_data` per arricchire il training
3. `/addestra_ml` ri-addestra il modello TF-IDF + LinearSVC
4. Per ogni nuova spesa:
   - Se confidence ML ≥ 0.7 → usa categoria ML (🤖)
   - Se confidence < 0.7 → fallback Groq API (🧠)
   - Se Groq non disponibile → categoria "Altro" (📋)
5. L'utente può sempre correggere la categoria con il pulsante inline

## 🏗️ Deploy su Render.com

### 1. Crea un nuovo Web Service

- Repository: il tuo repo GitHub
- Runtime: Python 3
- Build command: `pip install -r requirements.txt && python -m spacy download it_core_news_sm`
- Start command: `python main.py`

### 2. Database PostgreSQL

- Crea un PostgreSQL su Render (free tier: 256MB, 90 giorni)
- Copia la Internal Database URL in `DATABASE_URL`

### 3. Variabili d'ambiente

Aggiungi tutte le variabili del `.env` nelle Environment Variables di Render.

### 4. Cron Job (opzionale)

Per il re-training mensile automatico, crea un Cron Job su Render:
- Command: `python -c "import asyncio; from main import on_startup; asyncio.run(on_startup())"`
- Schedule: `0 2 1 * *` (ogni 1° del mese alle 2:00)

## 🏦 Configurazione Tink PSD2

1. Registrati su [console.tink.com](https://console.tink.com)
2. Crea un'app in modalità Sandbox
3. Copia `CLIENT_ID` e `CLIENT_SECRET` nel `.env`
4. Usa `/importa_psd2` nel bot per collegare un conto di test

## 📁 Struttura Progetto

```
telegram-expense-bot/
├── main.py              # Entry point, handler comandi aiogram
├── db.py                # Connessione PostgreSQL, CRUD async
├── ml.py                # Training TF-IDF + LinearSVC, predict + Groq fallback
├── ocr_nlp.py           # Pipeline EasyOCR + spaCy
├── export.py            # Generazione PDF e CSV
├── psd2.py              # Integrazione Tink OAuth
├── budgets.py           # Logica budget e avvisi
├── gruppi.py            # Gestione gruppi famiglia
├── schema.sql           # Schema PostgreSQL
├── requirements.txt     # Dipendenze Python
├── .env.example         # Template configurazione
├── dataset_sample.csv   # Dataset training iniziale
├── TODO.md              # Task tracker
└── README.md            # Questa documentazione
```

## ⚠️ Note

- EasyOCR al primo avvio scarica i modelli (~100MB). Pazienta.
- Il modello spaCy `it_core_news_sm` va scaricato separatamente.
- Su Render free tier il bot potrebbe andare in sleep dopo 15 min di inattività.
- Il database PostgreSQL gratuito su Render scade dopo 90 giorni — considera Supabase o Neon per alternative permanenti.

## 📄 Licenza

MIT — Usa liberamente per progetti personali e familiari.
