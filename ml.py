"""
ml.py — Training TF-IDF + LinearSVC e predict con confidence score.
Fallback su Groq API (llama-3.1-8b-instant) se confidence < soglia.
"""
import os, logging, json
import numpy as np
from typing import Optional, Tuple
import joblib

logger = logging.getLogger(__name__)

# Percorsi modello
MODEL_PATH = os.getenv("ML_MODEL_PATH", "ml_model.joblib")
VECTORIZER_PATH = os.getenv("ML_VECTORIZER_PATH", "ml_vectorizer.joblib")
CONFIDENCE_THRESHOLD = float(os.getenv("ML_CONFIDENCE_THRESHOLD", "0.7"))

# Modello e vectorizer globali
_model = None
_vectorizer = None


def _load_model():
    """Carica modello e vectorizer da disco se esistono."""
    global _model, _vectorizer
    try:
        if os.path.exists(MODEL_PATH) and os.path.exists(VECTORIZER_PATH):
            _model = joblib.load(MODEL_PATH)
            _vectorizer = joblib.load(VECTORIZER_PATH)
            logger.info("Modello ML caricato da disco")
            return True
    except Exception as e:
        logger.error(f"Errore caricamento modello: {e}")
    return False


def train(descrizioni: list, categorie: list) -> dict:
    """
    Addestra il modello TF-IDF + LinearSVC.
    Ritorna statistiche del training.
    """
    global _model, _vectorizer
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.svm import LinearSVC
    from sklearn.model_selection import cross_val_score

    if len(descrizioni) < 5:
        return {"errore": "Servono almeno 5 esempi per il training"}

    # Conta le classi uniche
    classi_uniche = list(set(categorie))
    if len(classi_uniche) < 2:
        return {"errore": "Servono almeno 2 categorie diverse"}

    # TF-IDF Vectorizer ottimizzato per italiano
    _vectorizer = TfidfVectorizer(
        max_features=5000,
        ngram_range=(1, 2),       # unigrammi e bigrammi
        min_df=1,
        max_df=0.95,
        sublinear_tf=True,
        strip_accents='unicode'
    )

    X = _vectorizer.fit_transform(descrizioni)

    # LinearSVC con calibrazione
    _model = LinearSVC(
        C=1.0,
        max_iter=10000,
        class_weight='balanced'   # gestisce classi sbilanciate
    )
    _model.fit(X, categorie)

    # Cross-validation se ci sono abbastanza dati
    stats = {
        "num_esempi": len(descrizioni),
        "num_categorie": len(classi_uniche),
        "categorie": classi_uniche
    }

    if len(descrizioni) >= 10:
        try:
            cv_folds = min(5, min(categorie.count(c) for c in classi_uniche))
            if cv_folds >= 2:
                scores = cross_val_score(_model, X, categorie, cv=cv_folds, scoring='accuracy')
                stats["accuracy_media"] = round(float(np.mean(scores)), 3)
                stats["accuracy_std"] = round(float(np.std(scores)), 3)
        except Exception as e:
            logger.warning(f"Cross-validation non riuscita: {e}")

    # Salva su disco
    joblib.dump(_model, MODEL_PATH)
    joblib.dump(_vectorizer, VECTORIZER_PATH)
    logger.info(f"Modello addestrato e salvato: {stats}")

    return stats


def predict(descrizione: str) -> Tuple[Optional[str], float]:
    """
    Predice la categoria per una descrizione.
    Ritorna (categoria, confidence).
    Se il modello non è disponibile, ritorna (None, 0.0).
    """
    global _model, _vectorizer

    # Prova a caricare se non in memoria
    if _model is None or _vectorizer is None:
        if not _load_model():
            return None, 0.0

    try:
        X = _vectorizer.transform([descrizione])
        # Calcola decision function per la confidence
        decision = _model.decision_function(X)

        if len(_model.classes_) == 2:
            # Caso binario: sigmoid sulla decision function
            confidence = float(1 / (1 + np.exp(-abs(decision[0]))))
        else:
            # Caso multi-classe: softmax-like sulle decision values
            scores = decision[0]
            exp_scores = np.exp(scores - np.max(scores))
            probs = exp_scores / exp_scores.sum()
            best_idx = np.argmax(probs)
            confidence = float(probs[best_idx])

        categoria = _model.predict(X)[0]
        logger.info(f"ML predict: '{descrizione}' -> {categoria} (conf={confidence:.2f})")
        return categoria, confidence

    except Exception as e:
        logger.error(f"Errore predizione ML: {e}")
        return None, 0.0


async def predict_with_fallback(descrizione: str, categorie_disponibili: list = None) -> Tuple[str, str]:
    """
    Predice categoria con fallback su Groq API.
    Ritorna (categoria, metodo) dove metodo è 'ml' o 'groq' o 'default'.
    """
    # Prova ML locale
    categoria, confidence = predict(descrizione)
    if categoria and confidence >= CONFIDENCE_THRESHOLD:
        return categoria, "ml"

    # Fallback Groq API
    categoria_groq = await _groq_categorize(descrizione, categorie_disponibili)
    if categoria_groq:
        return categoria_groq, "groq"

    # Fallback finale
    return categoria or "Altro", "default"


async def _groq_categorize(descrizione: str, categorie: list = None) -> Optional[str]:
    """Usa Groq API per categorizzare una spesa."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        logger.warning("GROQ_API_KEY non configurata, skip fallback")
        return None

    if not categorie:
        categorie = ["Cibo", "Trasporti", "Casa", "Salute", "Intrattenimento", "Altro"]

    try:
        from groq import AsyncGroq
        client = AsyncGroq(api_key=api_key)

        prompt = (
            f"Categorizza questa spesa in UNA delle seguenti categorie: {', '.join(categorie)}.\n"
            f"Spesa: \"{descrizione}\"\n"
            f"Rispondi SOLO con il nome della categoria, nient'altro."
        )

        response = await client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=20
        )

        risultato = response.choices[0].message.content.strip()

        # Verifica che sia una categoria valida
        for cat in categorie:
            if cat.lower() == risultato.lower():
                logger.info(f"Groq categorizzazione: '{descrizione}' -> {cat}")
                return cat

        # Matching parziale
        for cat in categorie:
            if cat.lower() in risultato.lower() or risultato.lower() in cat.lower():
                logger.info(f"Groq categorizzazione (parziale): '{descrizione}' -> {cat}")
                return cat

        logger.warning(f"Groq risposta non valida: '{risultato}'")
        return None

    except Exception as e:
        logger.error(f"Errore Groq API: {e}")
        return None


async def groq_parse_spesa(testo: str) -> Optional[dict]:
    """
    Usa Groq API per parsare testo libero in JSON strutturato.
    Fallback se spaCy non riesce a estrarre i dati.
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return None

    try:
        from groq import AsyncGroq
        client = AsyncGroq(api_key=api_key)

        prompt = (
            "Estrai da questo testo italiano le informazioni sulla spesa.\n"
            f"Testo: \"{testo}\"\n"
            "Rispondi SOLO con un JSON valido con questi campi:\n"
            '{"importo": numero, "descrizione": "stringa", "data": "YYYY-MM-DD o null"}\n'
            "Se non trovi l'importo, usa null. La data è opzionale."
        )

        response = await client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=100
        )

        content = response.choices[0].message.content.strip()
        # Cerca JSON nel testo
        start = content.find('{')
        end = content.rfind('}') + 1
        if start >= 0 and end > start:
            return json.loads(content[start:end])
        return None

    except Exception as e:
        logger.error(f"Errore Groq parse: {e}")
        return None


def is_model_loaded() -> bool:
    """Verifica se il modello è caricato in memoria."""
    return _model is not None and _vectorizer is not None


def get_model_info() -> dict:
    """Restituisce info sul modello corrente."""
    if not is_model_loaded():
        if not _load_model():
            return {"stato": "non_addestrato"}
    return {
        "stato": "pronto",
        "num_features": _vectorizer.max_features if _vectorizer else 0,
        "num_classi": len(_model.classes_) if _model else 0,
        "classi": list(_model.classes_) if _model else [],
        "soglia_confidence": CONFIDENCE_THRESHOLD
    }
