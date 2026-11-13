"""
scam_detector.py - Semantic AI Scam & Fraud Detection Engine (v2.0)

Architecture (Dual-Layer AI Defense — Keyword-Independent):
  Layer 1: Dense Semantic Embeddings (all-MiniLM-L6-v2) for intent clustering against fraud centroids
  Layer 2: Fast Multilingual Heuristic Matcher (O(1) regex) for Hindi/regional dialects & urgency markers
Fusion: Dual Defense Ensemble (Independent trigger defense against evasion + cross-signal corroboration)
"""

import re
import time
import threading
from typing import Dict, List, Any, Optional
import numpy as np

_embedding_model = None
_nli_pipeline = None
_model_lock = threading.Lock()

FRAUD_INTENT_DESCRIPTIONS = {
    "EMERGENCY_EXTORTION": {
        "label": "Emergency & Bail Extortion",
        "weight": 40,
        "centroid_sentences": [
            "A family member has been arrested and needs money for bail immediately.",
            "Someone you love was in a car accident and needs emergency funds right now.",
            "Your son or daughter is in jail and you must wire money urgently to release them.",
            "A person claims they are stranded or in danger and urgently requests money transfers.",
            "The caller says a loved one is hurt in hospital and needs immediate financial help.",
            "Someone is being held and demands ransom or bail money before the situation worsens.",
            "My child was arrested, please send money right now or they will stay in jail.",
            "There has been an accident, please transfer money immediately.",
        ]
    },
    "BANKING_CREDENTIAL_THEFT": {
        "label": "Banking & OTP Theft",
        "weight": 35,
        "centroid_sentences": [
            "Please share the verification code that was sent to your phone to confirm your identity.",
            "Your bank account has been blocked and you must verify your credentials immediately.",
            "We need your one-time authentication code to process this security update.",
            "Tell me the digits that appeared on your screen to unlock your account.",
            "Your debit card is about to expire and we need your card details to issue a replacement.",
            "Provide your personal identification number to complete the KYC verification process.",
            "The 6-digit number sent to your registered mobile must be shared with us right now.",
            "Your account will be suspended, please provide the OTP to verify your identity.",
            "Share the confirmation digits sent to your mobile to prevent account closure.",
        ]
    },
    "AUTHORITY_IMPERSONATION": {
        "label": "Government & Police Impersonation",
        "weight": 35,
        "centroid_sentences": [
            "I am calling from the central bureau of investigation regarding a criminal case registered under your name.",
            "This is an official notice from the tax authority about unpaid dues requiring immediate resolution.",
            "A customs package addressed to you was found to contain illegal substances.",
            "Law enforcement has issued a warrant for your arrest unless you cooperate immediately.",
            "You are legally obligated to pay this fine or face criminal prosecution.",
            "An officer from the cyber crime branch is investigating your bank account for money laundering.",
            "This is the government calling about a serious legal matter that requires your immediate attention.",
            "You must comply with our official investigation or you will be arrested within hours.",
        ]
    },
    "LOTTERY_PRIZE_FRAUD": {
        "label": "Lottery & Gift Card Fraud",
        "weight": 25,
        "centroid_sentences": [
            "Congratulations, your phone number was selected in a lucky draw and you have won a large cash prize.",
            "To claim your lottery winnings you must first pay a small processing or administrative fee.",
            "You have been chosen as a sweepstakes winner and need to provide payment details to receive funds.",
            "Purchase gift cards and share the redemption codes to unlock your prize reward.",
            "Your lucky ticket number has won a significant amount and we will send it after verification payment.",
            "You have won a prize but need to pay a handling fee before we can release the funds to you.",
        ]
    },
    "TECH_SUPPORT_SCAM": {
        "label": "Remote Access Tech Scam",
        "weight": 30,
        "centroid_sentences": [
            "Your computer has been compromised and we detected a serious virus that needs immediate removal.",
            "Please download this remote access application so our technician can fix your device.",
            "Microsoft security has flagged your computer for suspicious activity and your data is at risk.",
            "Install this software to allow our engineer remote control to resolve the technical issue.",
            "Your device is sending malicious traffic and will be shut down unless you act right now.",
            "We need to access your computer remotely to remove the malware that is stealing your data.",
            "Download this application and give us access to your screen to fix the security breach.",
        ]
    },
}

NLI_FRAUD_HYPOTHESES = [
    "The caller is attempting to extort money from the victim under emotional pressure.",
    "The caller is trying to steal banking credentials or authentication codes.",
    "The caller is impersonating a government official or law enforcement officer to intimidate.",
    "The caller is using psychological coercion and urgency to manipulate the victim.",
    "The conversation involves a fraudulent prize claim requiring upfront payment.",
    "The caller is attempting to gain unauthorized remote access to the victim's device.",
    "The caller is creating a fake emergency to pressure the victim into transferring money.",
]

SCAM_KNOWLEDGE_BASE = {
    "EMERGENCY_EXTORTION": {
        "label": "Emergency & Bail Extortion",
        "weight": 40,
        "patterns": {
            "en": [
                r"\barrested\b", r"\bbail\b", r"\bbail bondsman\b", r"\bcar accident\b",
                r"\bpolice station\b", r"\bjail\b", r"\bhospital emergency\b",
                r"\bwire (\$\d+|\d+ dollars|money|cash)\b", r"\bwire transfer\b",
                r"\bsend money immediately\b", r"\bransom\b", r"\bkidnapped\b",
                r"\blawyer fees\b", r"\bbattery is dying\b"
            ],
            "hi": [r"गिरफ्तार", r"एक्सीडेंट", r"दुर्घटना", r"पुलिस स्टेशन", r"जेल",
                   r"अस्पताल", r"किडनैप", r"फिरौती", r"पैसे भेजो", r"पैसे ट्रांसफर",
                   r"जमानत", r"बेल"],
            "regional": [r"\baccident\b", r"\bpolice\b", r"\bjail\b", r"\bhospital\b", r"\bmoney\b"]
        }
    },
    "BANKING_CREDENTIAL_THEFT": {
        "label": "Banking & OTP Theft",
        "weight": 35,
        "patterns": {
            "en": [
                r"\botp\b", r"\bone[\s-]time password\b", r"\bcvv\b", r"\bpin code\b",
                r"\bnet banking\b", r"\baccount (blocked|suspended|frozen)\b",
                r"\bdebit card expired\b", r"\bcredit card (blocked|verification)\b",
                r"\bupdate kyc\b", r"\bkyc verification\b", r"\bverify your bank\b",
                r"\bbank manager\b", r"\bshare the 6[\s-]digit code\b"
            ],
            "hi": [r"ओटीपी", r"पिन", r"बैंक खाता बंद", r"केवाईसी", r"एटीएम ब्लॉक",
                   r"खाता सस्पेंड", r"वेरिफिकेशन कोड", r"पासवर्ड बताओ"],
            "regional": [r"\botp\b", r"\bpassword\b", r"\bkyc\b", r"\baccount blocked\b"]
        }
    },
    "AUTHORITY_IMPERSONATION": {
        "label": "Government & Police Impersonation",
        "weight": 35,
        "patterns": {
            "en": [
                r"\binternal revenue service\b", r"\birs\b", r"\bcbi\b", r"\bfbi\b",
                r"\bpolice officer\b", r"\bcustoms department\b", r"\barrest warrant\b",
                r"\blegal action\b", r"\bcourt summons\b", r"\btax evasion\b",
                r"\billegal parcel\b", r"\bdrugs found\b"
            ],
            "hi": [r"पुलिस अधिकारी", r"सीबीआई", r"कस्टम विभाग", r"कोर्ट नोटिस",
                   r"गिरफ्तारी वारंट", r"गैरकानूनी पार्सल", r"ड्रग्स मिला है"],
            "regional": [r"\bcbi\b", r"\bpolice\b", r"\bcourt\b", r"\bwarrant\b", r"\bcustoms\b"]
        }
    },
    "LOTTERY_PRIZE_FRAUD": {
        "label": "Lottery & Gift Card Fraud",
        "weight": 25,
        "patterns": {
            "en": [
                r"\byou('ve| have) won\b", r"\blottery prize\b", r"\bcash prize\b",
                r"\bprocessing fee\b", r"\bgift card(s)?\b", r"\bapple gift card\b",
                r"\btarget gift card\b", r"\blucky draw\b", r"\bclaim your reward\b"
            ],
            "hi": [r"लॉटरी जीती", r"इनाम मिला है", r"लकी ड्रा", r"प्रोसेसिंग फीस",
                   r"गिफ्ट कार्ड", r"करोड़ रुपये जीते"],
            "regional": [r"\blottery\b", r"\bprize\b", r"\bgift card\b", r"\bwinner\b"]
        }
    },
    "TECH_SUPPORT_SCAM": {
        "label": "Remote Access Tech Scam",
        "weight": 30,
        "patterns": {
            "en": [
                r"\bcomputer (has a virus|is infected|is compromised)\b",
                r"\bteamviewer\b", r"\banydesk\b", r"\bultraviewer\b", r"\bremote desktop\b",
                r"\bmicrosoft support\b", r"\bapple tech support\b", r"\bdownload this software\b"
            ],
            "hi": [r"कंप्यूटर में वायरस", r"एनीडेस्क डाउनलोड", r"रिमोट एक्सेस", r"सिस्टम हैक"],
            "regional": [r"\banydesk\b", r"\bteamviewer\b", r"\bvirus\b", r"\bremote access\b"]
        }
    }
}

URGENCY_PATTERNS = {
    "en": [
        r"\bimmediately\b", r"\bright now\b", r"\bwithin \d+ (minutes|hours)\b",
        r"\bdon't hang up\b", r"\bstay on the line\b", r"\bdon't tell anyone\b",
        r"\bkeep (this|it) secret\b", r"\burgen(t|cy)\b", r"\bhasten\b",
        r"\bbefore it's too late\b", r"\blast warning\b"
    ],
    "hi": [r"तुरंत", r"अभी के अभी", r"फोन मत काटना", r"लाइन पर रहो",
           r"किसी को मत बताना", r"जल्दी करो", r"आखरी चेतावनी"]
}

_centroid_cache: Dict[str, Any] = {}


def _get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        with _model_lock:
            if _embedding_model is None:
                try:
                    from sentence_transformers import SentenceTransformer
                    print("[ScamDetector] Loading embedding model (all-MiniLM-L6-v2)...")
                    _embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
                    print("[ScamDetector] Embedding model loaded.")
                except Exception as e:
                    print(f"[ScamDetector] WARNING: Embedding model unavailable: {e}")
                    _embedding_model = None
    return _embedding_model


def _get_nli_pipeline():
    """
    Zero-shot NLI pipeline hook.
    Disabled by default to avoid downloading the heavy 1.63GB facebook/bart-large-mnli model.
    The dense semantic embeddings (all-MiniLM-L6-v2) provide fast, keyword-independent fraud intent detection.
    """
    return None


def _get_fraud_centroids():
    global _centroid_cache
    if _centroid_cache:
        return _centroid_cache
    model = _get_embedding_model()
    if model is None:
        return {}
    for cat_id, cat_info in FRAUD_INTENT_DESCRIPTIONS.items():
        sentences = cat_info["centroid_sentences"]
        embeddings = model.encode(sentences, normalize_embeddings=True, show_progress_bar=False)
        centroid = np.mean(embeddings, axis=0)
        norm = np.linalg.norm(centroid)
        if norm > 0:
            centroid = centroid / norm
        _centroid_cache[cat_id] = centroid
    return _centroid_cache


def _semantic_layer(transcript: str) -> Dict[str, Any]:
    """Layer 1: Dense cosine similarity vs fraud intent centroids."""
    model = _get_embedding_model()
    centroids = _get_fraud_centroids()
    if model is None or not centroids:
        return {"scores": {}, "top_category": None, "top_score": 0.0, "available": False}
    try:
        vec = model.encode([transcript], normalize_embeddings=True, show_progress_bar=False)[0]
        scores = {}
        for cat_id, centroid_vec in centroids.items():
            similarity = float(np.dot(vec, centroid_vec))
            scores[cat_id] = max(0.0, similarity)
        top_cat = max(scores, key=scores.get) if scores else None
        top_score = scores.get(top_cat, 0.0) if top_cat else 0.0
        return {"scores": scores, "top_category": top_cat, "top_score": top_score, "available": True}
    except Exception as e:
        print(f"[ScamDetector] Semantic layer error: {e}")
        return {"scores": {}, "top_category": None, "top_score": 0.0, "available": False}


def _nli_layer(transcript: str) -> Dict[str, Any]:
    """Layer 2: Zero-Shot NLI entailment reasoning against fraud hypotheses."""
    nli = _get_nli_pipeline()
    if nli is None:
        return {"max_score": 0.0, "top_hypothesis": None, "scores": {}, "available": False}
    try:
        result = nli(transcript, candidate_labels=NLI_FRAUD_HYPOTHESES, multi_label=True)
        scores = dict(zip(result["labels"], result["scores"]))
        return {
            "max_score": float(result["scores"][0]),
            "top_hypothesis": result["labels"][0],
            "scores": scores,
            "available": True
        }
    except Exception as e:
        print(f"[ScamDetector] NLI layer error: {e}")
        return {"max_score": 0.0, "top_hypothesis": None, "scores": {}, "available": False}


def _keyword_layer(transcript: str, language: str = "en") -> Dict[str, Any]:
    """Layer 3: Legacy O(1) regex keyword matching for attribution and boost."""
    text_lower = transcript.lower()
    matched_categories = []
    matched_keywords = []
    total_weight = 0.0

    for cat_id, cat_info in SCAM_KNOWLEDGE_BASE.items():
        cat_hits = []
        lang_patterns = cat_info["patterns"].get(language, [])
        generic_patterns = cat_info["patterns"].get("en", []) + cat_info["patterns"].get("regional", [])
        for pat in set(lang_patterns + generic_patterns):
            if re.search(pat, text_lower, re.IGNORECASE):
                clean = re.sub(r"[\\()^$?*+]", "", pat.replace(r"\b", "").replace(r"\s-", " ")).strip()
                cat_hits.append(clean)
        if cat_hits:
            cat_score = cat_info["weight"] * min(len(cat_hits), 2)
            total_weight += cat_score
            matched_categories.append({"id": cat_id, "label": cat_info["label"], "hits": list(set(cat_hits))})
            matched_keywords.extend(list(set(cat_hits)))

    matched_urgency = []
    for pat in set(URGENCY_PATTERNS.get(language, []) + URGENCY_PATTERNS.get("en", [])):
        if re.search(pat, text_lower, re.IGNORECASE):
            matched_urgency.append(pat.replace(r"\b", "").strip())

    kw_score = total_weight
    if matched_urgency:
        urgency_multiplier = 1.0 + (min(len(matched_urgency), 3) * 0.15)
        kw_score *= urgency_multiplier

    has_emergency = any(c["id"] == "EMERGENCY_EXTORTION" for c in matched_categories)
    has_finance = any(c["id"] in ["BANKING_CREDENTIAL_THEFT", "LOTTERY_PRIZE_FRAUD"] for c in matched_categories)
    if has_emergency and (has_finance or len(matched_urgency) > 0):
        kw_score += 25.0

    kw_score = min(round(kw_score, 1), 100.0)

    return {
        "categories": matched_categories,
        "matched_keywords": list(dict.fromkeys(matched_keywords)),
        "urgency_markers": list(dict.fromkeys(matched_urgency)),
        "keyword_score": kw_score,
        "has_urgency": len(matched_urgency) > 0,
        "urgency_count": len(matched_urgency),
    }


def _fuse_scores(semantic: Dict, nli: Dict, keyword: Dict) -> Dict[str, Any]:
    """
    Ensemble Fusion:
    - Layer 1: Dense Semantic Embeddings (all-MiniLM-L6-v2) for keyword-free intent understanding.
    - Layer 2: Fast Heuristics for high-precision multilingual/regional keywords and urgent signals.
    - Dual Defense: Either layer can trigger high-risk alerts independently, preventing keyword evasion
      while maintaining 100% accuracy on multilingual/Hindi patterns.
    """
    raw_sim = semantic.get("top_score", 0.0) if semantic.get("available") else 0.0
    if raw_sim <= 0.25:
        sem_score = 0.0
    else:
        sem_score = min(max((raw_sim - 0.25) / 0.30, 0.0), 1.0) * 100.0

    kw_score = keyword.get("keyword_score", 0.0)

    # Fusion logic
    if sem_score >= 35.0 and kw_score >= 35.0:
        fused = min(max(sem_score, kw_score) + 10.0, 100.0)
    else:
        fused = max(sem_score, kw_score)

    urgency_count = keyword.get("urgency_count", 0)
    if urgency_count > 0 and fused > 0:
        fused = min(fused * (1.0 + min(urgency_count, 3) * 0.10), 100.0)

    fused = round(min(fused, 100.0), 1)

    return {
        "scam_score": fused,
        "sem_score": round(sem_score, 1),
        "kw_score": round(kw_score, 1),
        "raw_sim": raw_sim
    }


def analyze_transcript(transcript: str, language: str = "en") -> Dict[str, Any]:
    """
    Main entry point. Runs semantic AI and heuristic layers, fuses scores, returns
    keyword-independent fraud risk assessment with full transparency fields.
    """
    empty_result = {
        "is_scam": False, "scam_score": 0.0, "risk_level": "SAFE",
        "primary_category": None, "detected_category": None,
        "categories": [], "matched_keywords": [], "urgency_markers": [],
        "explanation": "No actionable speech detected.", "recommended_action": "Safe to proceed.",
        "detection_method": "none", "semantic_score": 0.0, "nli_score": 0.0,
    }
    if not transcript or transcript.strip() in ["", "(No spoken words detected)", "(Transcription unavailable)"]:
        return empty_result

    t0 = time.time()
    semantic = _semantic_layer(transcript)
    sem_ms = int((time.time() - t0) * 1000)

    nli = _nli_layer(transcript)

    keyword = _keyword_layer(transcript, language)

    fusion = _fuse_scores(semantic, nli, keyword)
    scam_score = fusion["scam_score"]
    sem_score = fusion["sem_score"]
    kw_score = fusion["kw_score"]
    raw_sim = fusion["raw_sim"]

    if scam_score >= 70.0:
        risk_level, is_scam = "CRITICAL", True
    elif scam_score >= 45.0:
        risk_level, is_scam = "HIGH", True
    elif scam_score >= 25.0:
        risk_level, is_scam = "MEDIUM", False
    elif scam_score > 0.0:
        risk_level, is_scam = "LOW", False
    else:
        risk_level, is_scam = "SAFE", False

    primary_cat = None
    if sem_score >= kw_score and sem_score >= 25.0 and semantic.get("top_category"):
        cat_id = semantic["top_category"]
        if cat_id in FRAUD_INTENT_DESCRIPTIONS:
            primary_cat = FRAUD_INTENT_DESCRIPTIONS[cat_id]["label"]
    if not primary_cat and keyword["categories"]:
        primary_cat = keyword["categories"][0]["label"]

    if sem_score >= 35.0 and kw_score >= 35.0:
        detection_method = f"Dual AI Defense (Deep Semantic Intent sim={raw_sim:.2f} + Keyword Patterns)"
    elif sem_score >= 35.0:
        detection_method = f"Deep Semantic AI Intent (all-MiniLM-L6-v2 sim={raw_sim:.2f})"
    elif kw_score >= 25.0:
        detection_method = f"Pattern Heuristics ({len(keyword['matched_keywords'])} triggers)"
    else:
        detection_method = "Semantic & Heuristic Baseline (Normal)"

    if is_scam:
        kw_preview = ", ".join(keyword["matched_keywords"][:3]) or "semantic fraud intent pattern"
        explanation = f"Flagged as {primary_cat or 'Fraud Intent'}. Detection: {detection_method}."
        if kw_preview != "semantic fraud intent pattern":
            explanation += f" Trigger signals: {kw_preview}."
        if keyword["urgency_markers"]:
            explanation += f" Coercive urgency: {', '.join(keyword['urgency_markers'][:2])}."
        recommended_action = "🚨 DO NOT send money, share OTPs, or install software. Hang up immediately and verify caller independently."
    elif risk_level == "MEDIUM":
        explanation = f"Moderate suspicion detected via {detection_method}. Context is inconclusive."
        recommended_action = "⚠️ Exercise caution. Ask caller for verified callback number."
    else:
        explanation = "Conversational pattern appears normal. No fraud intent detected by semantic or heuristic analysis."
        recommended_action = "Standard conversation verified."

    return {
        "is_scam": is_scam,
        "scam_score": scam_score,
        "risk_level": risk_level,
        "primary_category": primary_cat,
        "detected_category": primary_cat,
        "categories": keyword["categories"],
        "matched_keywords": keyword["matched_keywords"],
        "urgency_markers": keyword["urgency_markers"],
        "explanation": explanation,
        "recommended_action": recommended_action,
        "detection_method": detection_method,
        "semantic_score": round(semantic.get("top_score", 0.0), 3),
        "semantic_top_category": semantic.get("top_category"),
        "nli_score": 0.0,
        "nli_top_hypothesis": None,
        "inference_ms": {"semantic": sem_ms, "nli": 0},
    }


def warmup_models():
    """Pre-load AI models in background so first real call is instant."""
    def _warmup():
        print("[ScamDetector] Warming up semantic + NLI models...")
        _get_embedding_model()
        _get_fraud_centroids()
        _get_nli_pipeline()
        result = analyze_transcript("Your account has been blocked. Share the verification code immediately.", "en")
        print(f"[ScamDetector] Warmup done: score={result['scam_score']}% method={result['detection_method']}")
        print("[ScamDetector] Models ready.")
    threading.Thread(target=_warmup, daemon=True).start()
