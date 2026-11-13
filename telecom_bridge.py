"""
telecom_bridge.py - Real-Time 3-Way Telecom Call Intercept & AI Voice Firewall
Integrates Twilio Media Streams with Voice Clone Shield AI Pipeline.
Enables simultaneous live conversation between caller and user while the AI
passively monitors incoming audio over WebSockets in real time.
"""

import os
import io
import time
import json
import base64
import audioop
import numpy as np
import scipy.signal
from typing import Dict, Any, Optional, Callable

from fastapi import WebSocket, WebSocketDisconnect
from fastapi.responses import Response

# Cache forwarding phone number
_TELECOM_CONFIG = {
    "forwarding_phone": os.getenv("EMERGENCY_CONTACT_PHONE", os.getenv("FORWARDING_PHONE", "")),
    "twilio_phone": os.getenv("TWILIO_PHONE_NUMBER", ""),
    "whisper_alert_enabled": os.getenv("WHISPER_ALERT_ENABLED", "true").lower() in ["1", "true", "yes"]
}

def get_telecom_config() -> Dict[str, Any]:
    return {
        "forwarding_phone": _TELECOM_CONFIG["forwarding_phone"],
        "twilio_phone": _TELECOM_CONFIG["twilio_phone"],
        "whisper_alert_enabled": _TELECOM_CONFIG["whisper_alert_enabled"]
    }

def update_telecom_config(forwarding_phone: Optional[str] = None, twilio_phone: Optional[str] = None, whisper_alert_enabled: Optional[bool] = None) -> Dict[str, Any]:
    if forwarding_phone is not None:
        _TELECOM_CONFIG["forwarding_phone"] = forwarding_phone.strip()
    if twilio_phone is not None:
        _TELECOM_CONFIG["twilio_phone"] = twilio_phone.strip()
    if whisper_alert_enabled is not None:
        _TELECOM_CONFIG["whisper_alert_enabled"] = bool(whisper_alert_enabled)
    return get_telecom_config()

def generate_twiml_bridge_response(base_url: str, caller_number: str = "Unknown") -> Response:
    """
    Generates TwiML XML instructing Twilio to:
    1. Start a non-blocking WebSocket audio stream (<Start><Stream>) to our server.
    2. Concurrently dial the user real mobile number (<Dial>) with answerOnBridge=true.
    """
    forwarding_num = _TELECOM_CONFIG["forwarding_phone"]
    
    # Clean up WebSocket URL scheme (http -> ws, https -> wss)
    clean_base = str(base_url).rstrip("/")
    if clean_base.startswith("https://"):
        wss_url = "wss://" + clean_base[8:]
    elif clean_base.startswith("http://"):
        wss_url = "ws://" + clean_base[7:]
    else:
        wss_url = f"wss://{clean_base}"

    stream_endpoint = f"{wss_url}/api/voice/stream"

    if not forwarding_num:
        # If no forwarding phone is set, give a voice prompt explaining setup
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">Voice Clone Shield is active, but no forwarding phone number has been configured. Please configure your destination number in the dashboard.</Say>
    <Hangup/>
</Response>
"""
        return Response(content=twiml, media_type="application/xml")

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <!-- 1. Silently fork caller audio to AI stream -->
    <Start>
        <Stream url="{stream_endpoint}" track="inbound_track">
            <Parameter name="caller" value="{caller_number}" />
        </Stream>
    </Start>
    <!-- 2. Simultaneously bridge call to user phone -->
    <Dial answerOnBridge="true" callerId="{caller_number}">
        <Number>{forwarding_num}</Number>
    </Dial>
</Response>
"""
    return Response(content=twiml, media_type="application/xml")

class TelecomStreamSession:
    """
    Manages state for an active Twilio live telecom call stream.
    Decodes 8kHz mu-law audio, accumulates 3.5s speech chunks, and feeds into pipeline.
    """
    def __init__(self, stream_sid: str, call_sid: str, caller_phone: str):
        self.stream_sid = stream_sid
        self.call_sid = call_sid
        self.caller_phone = caller_phone
        self.raw_mulaw_bytes = bytearray()
        self.start_time = time.time()
        self.chunk_index = 0
        self.is_active = True

    def append_payload(self, b64_payload: str):
        try:
            chunk = base64.b64decode(b64_payload)
            self.raw_mulaw_bytes.extend(chunk)
        except Exception as e:
            print(f"[Telecom Stream] Error decoding payload: {e}")

    def should_process_chunk(self) -> bool:
        # 8,000 samples/sec * 1 byte/sample (mu-law) = 8,000 bytes/sec
        # Process every 3.5 seconds = 28,000 bytes
        return len(self.raw_mulaw_bytes) >= 28000

    def extract_pcm_chunk(self) -> Optional[np.ndarray]:
        if not self.should_process_chunk():
            return None
        
        chunk_bytes = bytes(self.raw_mulaw_bytes)
        self.raw_mulaw_bytes.clear()
        
        try:
            # 1. Convert 8-bit mu-law to 16-bit linear PCM (8000 Hz)
            pcm16 = audioop.ulaw2lin(chunk_bytes, 2)
            # 2. Convert to numpy float32 in [-1.0, 1.0]
            arr8k = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
            # 3. Resample 8kHz to 16kHz for Wav2Vec2 and Faster-Whisper
            arr16k = scipy.signal.resample_poly(arr8k, 2, 1).astype(np.float32)
            self.chunk_index += 1
            return arr16k
        except Exception as e:
            print(f"[Telecom Stream] Error converting audio: {e}")
            return None
