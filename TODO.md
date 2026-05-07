# TODO — Telegram Expense Bot

## File da creare
- [x] schema.sql — Schema PostgreSQL completo con indici
- [x] requirements.txt — Dipendenze complete
- [x] .env.example — Template variabili d'ambiente
- [x] db.py — Connessione PostgreSQL, CRUD operazioni async
- [x] ml.py — Training TF-IDF + LinearSVC, predict con confidence score
- [x] ocr_nlp.py — Pipeline EasyOCR + spaCy + parsing testo libero
- [x] export.py — Generazione PDF (reportlab) e CSV (pandas)
- [x] psd2.py — Integrazione Tink OAuth e parsing transazioni
- [x] budgets.py — Logica limiti mensili e avvisi
- [x] gruppi.py — Gestione gruppi famiglia e inviti
- [x] main.py — Entry point bot, handler comandi aiogram
- [x] dataset_sample.csv — Dataset training ML iniziale (~200 esempi IT)
- [x] README.md — Setup completo, deploy su Render, configurazione Tink
- [x] .env — File configurazione con token reale

## Verifiche
- [x] Revisione coerenza import tra moduli
- [x] Revisione gestione errori e logging
- [x] Revisione README finale

## Stato: ✅ COMPLETATO
Tutti i file sono stati creati e sono pronti per l'uso.
Per avviare: `pip install -r requirements.txt && python -m spacy download it_core_news_sm && python main.py`
