import os
from typing import Optional
import io
import time
import numpy as np
import gc
import torch
torch.set_num_threads(1)
import soundfile as sf
import scipy.signal
from fastapi import FastAPI, File, UploadFile, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from transformers import pipeline
import librosa
from faster_whisper import WhisperModel
from scam_detector import analyze_transcript
import db
import sms_service
import telecom_bridge
import json
from fastapi import Request, WebSocket, WebSocketDisconnect

app = FastAPI(title="Voice Clone Shield")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load the industry-standard deepfake audio detection model
# mo-thecreator/Deepfake-audio-detection (robust against real live mic noise & room acoustics)
MODEL_ID = "mo-thecreator/Deepfake-audio-detection"
print(f"Loading robust detection pipeline ({MODEL_ID})...")
classifier = pipeline("audio-classification", model=MODEL_ID)
print("Detector loaded successfully!")

# Load multilingual faster-whisper model (quantized for high-speed CPU / Apple Silicon inference)
print("Loading multilingual faster-whisper model (tiny)...")
whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
print("Multilingual faster-whisper loaded successfully!")

SAFE_WORD = "SUPERNOVA-42"
os.makedirs("debug_recordings", exist_ok=True)
os.makedirs("samples", exist_ok=True)

def ensure_samples():
    import base64
    for name in ["sample_ai_clone", "sample_real_human"]:
        wav_path = os.path.join("samples", f"{name}.wav")
        b64_path = os.path.join("samples", f"{name}.b64")
        if not os.path.exists(wav_path) and os.path.exists(b64_path):
            with open(b64_path, "r") as f:
                decoded = base64.b64decode(f.read().strip())
            with open(wav_path, "wb") as f:
                f.write(decoded)
            print(f"Restored sample: {wav_path}")

ensure_samples()

def process_audio_buffer(file_bytes):
    """Decode audio bytes to 16kHz float32 mono array with normalization."""
    try:
        data, sr = sf.read(io.BytesIO(file_bytes))
    except Exception:
        # Fallback raw PCM / wav parser
        import wave
        with wave.open(io.BytesIO(file_bytes), 'rb') as wf:
            sr = wf.getframerate()
            frames = wf.readframes(wf.getnframes())
            data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0

    if len(data.shape) > 1:
        data = np.mean(data, axis=1) # Mono
    
    # Resample to 16kHz
    if sr != 16000:
        target_samples = int(len(data) * 16000 / sr)
        data = scipy.signal.resample(data, target_samples)
        sr = 16000

    # Remove DC offset & peak normalize
    data = data - np.mean(data)
    peak = np.max(np.abs(data))
    if peak > 1e-4:
        data = data / peak * 0.95 # Normalized to 0.95 peak

    # Trim leading/trailing silence (energy threshold)
    frame_len = int(16000 * 0.05)
    energies = [np.sum(data[i:i+frame_len]**2) for i in range(0, len(data), frame_len)]
    thresh = (np.mean(energies) * 0.1) if energies else 0.0
    start_idx = 0
    end_idx = len(data)
    for i, e in enumerate(energies):
        if e > thresh:
            start_idx = i * frame_len
            break
    for i in range(len(energies)-1, -1, -1):
        if energies[i] > thresh:
            end_idx = min(len(data), (i + 1) * frame_len)
            break
    
    trimmed = data[start_idx:end_idx]
    if len(trimmed) > 16000 * 0.5: # At least 0.5s of speech
        data = trimmed

    return data.astype(np.float32), sr

def extract_librosa_forensics(audio_data, sr=16000):
    """
    Extract multi-signal acoustic forensics using librosa:
    - 13 Mel-Frequency Cepstral Coefficients (MFCCs)
    - Spectral centroid (timbre brightness)
    - Spectral flatness (synthesizer noise vs tone ratio)
    - Spectral rolloff (high-frequency energy drop-off)
    - Fundamental frequency (F0) & pitch modulation stability
    - Mel-spectrogram normalized preview for visualization
    """
    try:
        # MFCCs (13 coefficients)
        mfccs = librosa.feature.mfcc(y=audio_data, sr=sr, n_mfcc=13)
        mfcc_summary = [round(float(x), 2) for x in np.mean(mfccs, axis=1)]

        # Spectral Centroid
        centroid = librosa.feature.spectral_centroid(y=audio_data, sr=sr)
        mean_centroid = round(float(np.mean(centroid)), 1)

        # Spectral Flatness
        flatness = librosa.feature.spectral_flatness(y=audio_data)
        mean_flatness = round(float(np.mean(flatness)), 4)

        # Spectral Rolloff (85% energy frequency)
        rolloff = librosa.feature.spectral_rolloff(y=audio_data, sr=sr, roll_percent=0.85)
        mean_rolloff = round(float(np.mean(rolloff)), 1)

        # Fundamental Frequency F0 / Pitch estimation (speed-optimized for cloud CPU)
        pitch_slice = audio_data[:sr * 3]
        pitches, magnitudes = librosa.piptrack(y=pitch_slice, sr=sr, hop_length=1024)
        valid_pitches = pitches[magnitudes > np.median(magnitudes)]
        mean_pitch = round(float(np.mean(valid_pitches)), 1) if len(valid_pitches) > 0 else 0.0
        pitch_jitter = round(float(np.std(valid_pitches)), 1) if len(valid_pitches) > 0 else 0.0

        # Mel Spectrogram Preview (32 frequency bands x up to 60 time slices)
        mel_spec = librosa.feature.melspectrogram(y=audio_data, sr=sr, n_mels=32, hop_length=int(sr * 0.04))
        mel_db = librosa.power_to_db(mel_spec, ref=np.max)
        mel_norm = np.clip((mel_db + 80.0) / 80.0, 0.0, 1.0)
        step = max(1, mel_norm.shape[1] // 60)
        spec_preview = [[round(float(v), 3) for v in col] for col in mel_norm[:, ::step].T]

        return {
            "mfcc_summary": mfcc_summary,
            "spectral_centroid_hz": mean_centroid,
            "spectral_flatness": mean_flatness,
            "spectral_rolloff_hz": mean_rolloff,
            "pitch_f0_hz": mean_pitch,
            "pitch_jitter_std": pitch_jitter,
            "spectrogram_preview": spec_preview
        }
    except Exception as e:
        print(f"Librosa extraction error: {e}")
        return {
            "mfcc_summary": [],
            "spectral_centroid_hz": 0.0,
            "spectral_flatness": 0.0,
            "spectral_rolloff_hz": 0.0,
            "pitch_f0_hz": 0.0,
            "pitch_jitter_std": 0.0,
            "spectrogram_preview": []
        }

def transcribe_audio_snippet(audio_data, sr=16000):
    """Transcribe audio with multilingual auto-detection and check for spoken emergency safewords."""
    try:
        # Multilingual auto-detection (detects en, hi, bn, ta, te, es, fr, etc.)
        segments, info = whisper_model.transcribe(audio_data, beam_size=1, vad_filter=True)
        text = " ".join([seg.text.strip() for seg in segments]).strip()
        
        # Check if the designated safe-word or keyword was spoken
        cleaned_text = text.lower()
        safeword_detected = (
            "supernova" in cleaned_text or 
            SAFE_WORD.lower() in cleaned_text
        )
        
        return {
            "transcript": text if text else "(No spoken words detected)",
            "language": info.language,
            "language_confidence": round(float(info.language_probability) * 100, 1),
            "safeword_spoken": safeword_detected
        }
    except Exception as e:
        print(f"Whisper transcription error: {e}")
        return {
            "transcript": "(Transcription unavailable)",
            "language": "en",
            "language_confidence": 0.0,
            "safeword_spoken": False
        }

@app.post("/api/analyze")
async def analyze_audio(file: Optional[UploadFile] = File(None), audio: Optional[UploadFile] = File(None)):
    target_file = file or audio
    if not target_file:
        return JSONResponse(status_code=400, content={"error": "No audio file provided. Send form data with 'file' or 'audio'."})
    start_time = time.time()
    contents = await target_file.read()
    
    # Save a copy for debug inspection
    debug_path = os.path.join("debug_recordings", f"rec_{int(time.time()*1000)}.wav")
    
    try:
        audio_data, sr = process_audio_buffer(contents)
        sf.write(debug_path, audio_data, sr)
    except Exception as e:
        print(f"Decode error on {target_file.filename}: {e}")
        return JSONResponse(status_code=400, content={"error": f"Audio processing error: {str(e)}"})
    
    duration = round(len(audio_data) / sr, 2)
    sample_slice = audio_data[:16000 * 5]
    
    # 1. Neural Spoof Classifier (mo-thecreator)
    predictions = classifier({"raw": sample_slice, "sampling_rate": 16000})
    print(f"Raw Model Predictions: {predictions}")
    
    scores = {p['label'].lower(): p['score'] for p in predictions}
    fake_score = scores.get('fake', 0.0)
    real_score = scores.get('real', 0.0)
    
    is_fake = fake_score > 0.5
    confidence = fake_score if is_fake else real_score
    
    # 2. Librosa Acoustic Forensics (MFCC, Centroid, Flatness, F0 Pitch)
    forensics = extract_librosa_forensics(sample_slice, sr)
    
    # 3. Multilingual faster-whisper Speech-to-Text & Spoken Safeword Intercept
    speech = transcribe_audio_snippet(sample_slice, sr)
    
    # 4. NLP Multilingual Scam & Extortion Intent Analysis
    scam_analysis = analyze_transcript(speech["transcript"], language=speech.get("language", "en"))
    
    # 5. Composite Security Assessment
    if is_fake and scam_analysis["is_scam"]:
        composite_verdict = "CRITICAL_AI_SCAM"
    elif is_fake:
        composite_verdict = "DEEPFAKE_VOICE"
    elif scam_analysis["is_scam"]:
        composite_verdict = "HUMAN_FRAUD_CALL"
    else:
        composite_verdict = "AUTHENTIC_SAFE"

    # 6. Persist to SQLite Audit Log
    call_id = None
    try:
        call_id = db.log_call(
            verdict="DEEPFAKE_CLONE" if is_fake else "AUTHENTIC_HUMAN",
            composite_verdict=composite_verdict,
            threat_score=round(fake_score * 100, 1),
            scam_score=float(scam_analysis.get("scam_score", 0.0)),
            risk_level=str(scam_analysis.get("risk_level", "SAFE")),
            primary_category=scam_analysis.get("primary_category") or scam_analysis.get("detected_category") or "Normal Audio",
            detected_language=speech.get("language", "en"),
            transcript=speech.get("transcript", ""),
            matched_keywords=scam_analysis.get("matched_keywords", []),
            urgency_markers=scam_analysis.get("urgency_markers", []),
            duration=duration,
            acoustic_data={
                "pitch_f0_hz": forensics["pitch_f0_hz"],
                "spectral_centroid_hz": forensics["spectral_centroid_hz"],
                "spectral_flatness": forensics["spectral_flatness"]
            },
            caller_label=f"Call Scan ({target_file.filename or 'Live Audio'})"
        )
    except Exception as dbe:
        print(f"DB logging warning: {dbe}")

    # 7. Automated Twilio SMS Threat Alert (Fraud / Extortion / AI Cloned Scams)
    sms_alert = None
    if scam_analysis.get("is_scam") or composite_verdict in ["CRITICAL_AI_SCAM", "HUMAN_FRAUD_CALL"]:
        try:
            sms_alert = sms_service.send_scam_alert_sms(
                call_id=str(call_id or "live-stream"),
                scam_analysis=scam_analysis,
                is_fake_voice=is_fake
            )
        except Exception as smse:
            print(f"SMS alert warning: {smse}")

    hf_cutoff = float(np.mean(np.abs(np.diff(sample_slice))))
    latency_ms = round((time.time() - start_time) * 1000)

    print(f"Composite Verdict: {composite_verdict} | Scam Score: {scam_analysis['scam_score']}% | Fake Score: {fake_score*100:.1f}%")

    return {
        "status": "success",
        "call_id": call_id,
        "verdict": "DEEPFAKE_CLONE" if is_fake else "AUTHENTIC_HUMAN",
        "composite_verdict": composite_verdict,
        "sms_alert": sms_alert,
        "is_fake": is_fake,
        "threat_score": round(fake_score * 100, 1),
        "confidence": round(confidence * 100, 1),
        "duration": duration,
        "latency_ms": latency_ms,
        "transcript": speech["transcript"],
        "speech_analysis": speech,
        "scam_analysis": scam_analysis,
        "acoustic_forensics": {
            "spectral_centroid_hz": forensics["spectral_centroid_hz"],
            "spectral_flatness": forensics["spectral_flatness"],
            "spectral_rolloff_hz": forensics["spectral_rolloff_hz"],
            "pitch_f0_hz": forensics["pitch_f0_hz"],
            "pitch_jitter_std": forensics["pitch_jitter_std"],
            "mfcc_summary": forensics["mfcc_summary"]
        },
        "acoustic_metrics": {
            "hf_jitter": round(hf_cutoff * 1000, 2),
            "sample_rate": sr,
            "samples_analyzed": len(sample_slice)
        },
        "spectrogram_preview": forensics["spectrogram_preview"]
    }

@app.get("/api/scam/calls")
async def get_scam_calls(limit: int = 50, flagged_only: bool = False):
    """Retrieve logged call records from SQLite audit log."""
    return db.get_recent_calls(limit=limit, filter_flagged_only=flagged_only)

@app.get("/api/scam/analytics")
async def get_scam_analytics():
    """Retrieve aggregate statistics on scanned calls, deepfakes, and fraud categories."""
    return db.get_analytics()

@app.post("/api/scam/clear-history")
async def clear_scam_history():
    """Clear call audit log."""
    db.clear_all_calls()
    return {"status": "cleared", "message": "Call audit logs wiped."}

@app.post("/api/scam/analyze-text")
async def analyze_text_endpoint(payload: dict):
    """Endpoint for direct NLP text fraud analysis across languages."""
    text = payload.get("text", "")
    language = payload.get("language", "en")
    return analyze_transcript(text, language=language)

@app.post("/api/verify-safeword")
async def verify_safeword(answer: str = Form(...)):
    is_match = answer.strip().upper() == SAFE_WORD
    return {
        "verified": is_match,
        "message": "Protocol Verified: Caller identity confirmed." if is_match else "Access Denied: Incorrect family safe-word. Call terminated."
    }

# ── Twilio SMS Security Alert Endpoints ──
@app.get("/api/sms/config")
async def get_sms_configuration():
    """Retrieve Twilio SMS configuration state (tokens are safely masked)."""
    return sms_service.get_sms_config()

@app.post("/api/sms/config")
async def update_sms_configuration(payload: dict):
    """Update runtime Twilio credentials or emergency contact phone number."""
    updated = sms_service.update_sms_config(
        account_sid=payload.get("account_sid"),
        auth_token=payload.get("auth_token"),
        from_number=payload.get("from_number"),
        emergency_contact=payload.get("emergency_contact"),
        enabled=payload.get("enabled")
    )
    return {"status": "success", "config": updated}

@app.post("/api/sms/test")
async def test_sms_alert(payload: Optional[dict] = None):
    """Sends a verification SMS to confirm Twilio integration and phone routing."""
    target_phone = (payload or {}).get("phone")
    result = sms_service.send_test_sms(target_phone=target_phone)
    return result

@app.get("/api/sms/logs")
async def get_sms_alert_logs(limit: int = 25):
    """Retrieve recent automated SMS alert dispatch records."""
    return sms_service.get_dispatch_logs(limit=limit)



# ── Telecom 3-Way Live Call Bridge (Twilio Voice Streams) ──
active_web_clients = set()

async def broadcast_live_event(event_data: dict):
    for ws in list(active_web_clients):
        try:
            await ws.send_json(event_data)
        except Exception:
            active_web_clients.discard(ws)

@app.websocket("/ws/live-feed")
async def live_feed_ws(websocket: WebSocket):
    await websocket.accept()
    active_web_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_web_clients.discard(websocket)

@app.post("/api/voice/incoming")
async def handle_incoming_voice_call(request: Request):
    """
    Twilio hits this webhook when someone calls your virtual number.
    Returns TwiML that silently forks audio to /api/voice/stream while bridging to your phone.
    """
    form = await request.form()
    caller = form.get("From", "Unknown Caller")
    base_url = str(request.base_url)
    return telecom_bridge.generate_twiml_bridge_response(base_url, caller_number=caller)

@app.post("/api/voice/status")
async def handle_voice_status(request: Request):
    form = await request.form()
    call_sid = form.get("CallSid")
    call_status = form.get("CallStatus")
    print(f"[Telecom Bridge] Call {call_sid} status update: {call_status}")
    return {"status": "received"}

@app.get("/api/voice/config")
async def get_voice_telecom_config(request: Request):
    cfg = telecom_bridge.get_telecom_config()
    base_url = str(request.base_url).rstrip("/")
    cfg["webhook_url"] = f"{base_url}/api/voice/incoming"
    clean_host = base_url.split("://")[-1] if "://" in base_url else base_url
    cfg["stream_url"] = f"wss://{clean_host}/api/voice/stream"
    return cfg

@app.post("/api/voice/config")
async def update_voice_telecom_config(payload: dict):
    updated = telecom_bridge.update_telecom_config(
        forwarding_phone=payload.get("forwarding_phone"),
        twilio_phone=payload.get("twilio_phone"),
        whisper_alert_enabled=payload.get("whisper_alert_enabled")
    )
    return {"status": "success", "config": updated}

@app.websocket("/api/voice/stream")
async def handle_twilio_voice_stream(websocket: WebSocket):
    """
    Bi-directional media stream connection directly from Twilio.
    Passively monitors incoming audio over WebSockets in real time.
    """
    await websocket.accept()
    session = None
    try:
        while True:
            message = await websocket.receive_text()
            data = json.loads(message)
            event = data.get("event")

            if event == "start":
                start_info = data.get("start", {})
                stream_sid = data.get("streamSid")
                call_sid = start_info.get("callSid")
                custom_params = start_info.get("customParameters", {})
                caller = custom_params.get("caller", "Unknown")
                session = telecom_bridge.TelecomStreamSession(stream_sid, call_sid, caller)
                print(f"[Telecom Stream] Started session: {stream_sid} for caller {caller}")
                await broadcast_live_event({
                    "type": "telecom_call_started",
                    "caller": caller,
                    "call_sid": call_sid
                })

            elif event == "media":
                if session and session.is_active:
                    payload = data.get("media", {}).get("payload")
                    if payload:
                        session.append_payload(payload)

                        # Process speech every 3.5 seconds
                        if session.should_process_chunk():
                            pcm_chunk = session.extract_pcm_chunk()
                            if pcm_chunk is not None and len(pcm_chunk) > 8000:
                                # 1. Neural classification
                                preds = classifier({"raw": pcm_chunk, "sampling_rate": 16000})
                                scores = {p["label"].lower(): p["score"] for p in preds}
                                fake_score = scores.get("fake", 0.0)
                                is_fake = fake_score > 0.5

                                # 2. Acoustic Forensics
                                forensics = extract_librosa_forensics(pcm_chunk, 16000)

                                # 3. Faster-Whisper Transcription
                                speech = transcribe_audio_snippet(pcm_chunk, 16000)

                                # 4. NLP Scam & Extortion Screening
                                scam_analysis = analyze_transcript(speech["transcript"], language=speech.get("language", "en"))

                                # 5. Composite Verdict
                                if is_fake and scam_analysis["is_scam"]:
                                    composite_verdict = "CRITICAL_AI_SCAM"
                                elif is_fake:
                                    composite_verdict = "DEEPFAKE_VOICE"
                                elif scam_analysis["is_scam"]:
                                    composite_verdict = "HUMAN_FRAUD_CALL"
                                else:
                                    composite_verdict = "AUTHENTIC_SAFE"

                                # 6. Database Persistence
                                call_id = None
                                try:
                                    call_id = db.log_call(
                                        verdict="DEEPFAKE_CLONE" if is_fake else "AUTHENTIC_HUMAN",
                                        composite_verdict=composite_verdict,
                                        threat_score=round(fake_score * 100, 1),
                                        scam_score=float(scam_analysis.get("scam_score", 0.0)),
                                        risk_level=str(scam_analysis.get("risk_level", "SAFE")),
                                        primary_category=scam_analysis.get("primary_category") or "Live Telecom Call",
                                        detected_language=speech.get("language", "en"),
                                        transcript=speech.get("transcript", ""),
                                        matched_keywords=scam_analysis.get("matched_keywords", []),
                                        urgency_markers=scam_analysis.get("urgency_markers", []),
                                        duration=3.5,
                                        acoustic_data={
                                            "pitch_f0_hz": forensics["pitch_f0_hz"],
                                            "spectral_centroid_hz": forensics["spectral_centroid_hz"],
                                            "spectral_flatness": forensics["spectral_flatness"]
                                        },
                                        caller_label=f"Telecom Call ({session.caller_phone})"
                                    )
                                except Exception as dbe:
                                    print(f"Telecom DB log warning: {dbe}")

                                # 7. Automated SMS Alert if active threat
                                if scam_analysis.get("is_scam") or is_fake:
                                    try:
                                        sms_service.send_scam_alert_sms(
                                            call_id=str(call_id or session.call_sid),
                                            scam_analysis=scam_analysis,
                                            is_fake_voice=is_fake
                                        )
                                    except Exception as smse:
                                        print(f"Telecom SMS error: {smse}")

                                # 8. Broadcast live telemetry to connected UI dashboards
                                await broadcast_live_event({
                                    "type": "telecom_chunk_analyzed",
                                    "caller": session.caller_phone,
                                    "is_fake": is_fake,
                                    "threat_score": round(fake_score * 100, 1),
                                    "transcript": speech.get("transcript", ""),
                                    "composite_verdict": composite_verdict,
                                    "risk_level": scam_analysis.get("risk_level", "SAFE"),
                                    "call_id": call_id
                                })

            elif event == "stop":
                print(f"[Telecom Stream] Session stopped for {session.stream_sid if session else unknown}")
                await broadcast_live_event({
                    "type": "telecom_call_ended",
                    "caller": session.caller_phone if session else "Unknown"
                })
                break

    except WebSocketDisconnect:
        print("[Telecom Stream] WebSocket disconnected by Twilio")
    except Exception as e:
        print(f"[Telecom Stream] Error: {e}")


@app.get("/api/samples/{sample_name}")
async def get_sample(sample_name: str):
    from fastapi.responses import FileResponse
    path = os.path.join("samples", sample_name)
    if os.path.exists(path):
        return FileResponse(path, media_type="audio/wav")
    return JSONResponse(status_code=404, content={"error": "Not found"})

os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    with open("static/index.html", "r") as f:
        return f.read()

@app.get("/privacy", response_class=HTMLResponse)
async def serve_privacy():
    with open("static/privacy.html", "r") as f:
        return f.read()

@app.get("/terms", response_class=HTMLResponse)
async def serve_terms():
    with open("static/terms.html", "r") as f:
        return f.read()

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 7860))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
