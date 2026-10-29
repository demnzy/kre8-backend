import os
import re
import urllib.parse
import httpx
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger("kre8.voice_service")

# Storage directory for synthesized audio
STORAGE_DIR = Path(__file__).resolve().parent.parent.parent / "storage" / "audio"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

NU_VOICE_URL = os.getenv("NU_VOICE_URL", "https://voice.nu-age.name.ng").rstrip("/")

AVAILABLE_VOICES = [
    {
        "id": "af_heart",
        "name": "Heart (Natural & Warm)",
        "language": "en",
        "language_name": "English",
        "gender": "Female",
        "engine": "Kokoro-82M",
        "sample_rate": 24000
    },
    {
        "id": "am_adam",
        "name": "Adam (Deep & Confident)",
        "language": "en",
        "language_name": "English",
        "gender": "Male",
        "engine": "Kokoro-82M",
        "sample_rate": 24000
    },
    {
        "id": "af_bella",
        "name": "Bella (Expressive & Dynamic)",
        "language": "en",
        "language_name": "English",
        "gender": "Female",
        "engine": "Kokoro-82M",
        "sample_rate": 24000
    },
    {
        "id": "am_michael",
        "name": "Michael (Authoritative & Smooth)",
        "language": "en",
        "language_name": "English",
        "gender": "Male",
        "engine": "Kokoro-82M",
        "sample_rate": 24000
    },
    {
        "id": "bf_alice",
        "name": "Alice (British Conversational)",
        "language": "en",
        "language_name": "English (UK)",
        "gender": "Female",
        "engine": "Kokoro-82M",
        "sample_rate": 24000
    },
    {
        "id": "bm_george",
        "name": "George (British Storyteller)",
        "language": "en",
        "language_name": "English (UK)",
        "gender": "Male",
        "engine": "Kokoro-82M",
        "sample_rate": 24000
    },
    {
        "id": "ha",
        "name": "Amina (Hausa Natural)",
        "language": "ha",
        "language_name": "Hausa",
        "gender": "Female",
        "engine": "Meta MMS",
        "sample_rate": 16000
    },
    {
        "id": "fr",
        "name": "Camille (French Natural)",
        "language": "fr",
        "language_name": "French",
        "gender": "Female",
        "engine": "Meta MMS",
        "sample_rate": 16000
    }
]

def resolve_voice_and_lang(voice_id: str | None) -> tuple[str, str | None]:
    """Resolves language code and optional voice persona for Nu-Voice."""
    if not voice_id:
        return "en", "af_heart"
    v = voice_id.lower().strip()
    if v in ("ha", "hausa"):
        return "ha", None
    if v in ("fr", "french"):
        return "fr", None
    if v in ("en", "english"):
        return "en", "af_heart"
    return "en", v

def clean_spoken_text(text: str) -> str:
    """Removes director cues, bracket tags, and markdown markup for clean human speech."""
    if not text:
        return ""
    # Strip markdown headers # Heading
    cleaned = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Strip bracket cues [B-ROLL: ...], [CTA], [PAUSE]
    cleaned = re.sub(r"\[.*?\]", "", cleaned)
    cleaned = re.sub(r"\(.*?\)", "", cleaned)
    # Strip bold and italics markers **word** -> word
    cleaned = cleaned.replace("**", "").replace("*", "")
    # Normalize whitespace
    cleaned = " ".join(cleaned.split())
    return cleaned.strip()

def estimate_audio_duration(text: str, audio_bytes_len: int) -> float:
    """Estimates audio duration in seconds from spoken text and audio byte size."""
    words = len(text.split())
    # ~2.2 words per second natural cadence
    dur = max(1.5, words / 2.2)
    return round(dur, 2)

class VoiceService:
    @classmethod
    def get_voices(cls) -> List[Dict[str, Any]]:
        return AVAILABLE_VOICES

    @classmethod
    async def synthesize_speech(cls, text: str, voice_id: str = "af_heart", format: str = "mp3") -> bytes:
        clean_text = clean_spoken_text(text)
        if not clean_text:
            raise ValueError("No readable spoken dialogue found to synthesize.")

        lang, voice_param = resolve_voice_and_lang(voice_id)
        encoded_text = urllib.parse.quote(clean_text)
        endpoint = f"{NU_VOICE_URL}/v1/tts/stream?text={encoded_text}&lang={lang}&format={format}"
        if voice_param:
            endpoint += f"&voice={voice_param}"

        logger.info(f"Synthesizing voiceover via Nu-Voice: lang={lang}, voice={voice_param}, chars={len(clean_text)}")
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(endpoint)
            if resp.status_code != 200:
                raise RuntimeError(f"Nu-Voice error [{resp.status_code}]: {resp.text}")
            audio_bytes = resp.content
            if not audio_bytes:
                raise RuntimeError("Nu-Voice returned empty audio payload.")
            return audio_bytes

    @classmethod
    def synthesize_speech_sync(cls, text: str, voice_id: str = "af_heart", format: str = "mp3") -> bytes:
        clean_text = clean_spoken_text(text)
        if not clean_text:
            raise ValueError("No readable spoken dialogue found to synthesize.")

        lang, voice_param = resolve_voice_and_lang(voice_id)
        encoded_text = urllib.parse.quote(clean_text)
        endpoint = f"{NU_VOICE_URL}/v1/tts/stream?text={encoded_text}&lang={lang}&format={format}"
        if voice_param:
            endpoint += f"&voice={voice_param}"

        logger.info(f"Sync synthesizing voiceover via Nu-Voice: lang={lang}, voice={voice_param}, chars={len(clean_text)}")
        with httpx.Client(timeout=60.0) as client:
            resp = client.get(endpoint)
            if resp.status_code != 200:
                raise RuntimeError(f"Nu-Voice error [{resp.status_code}]: {resp.text}")
            audio_bytes = resp.content
            if not audio_bytes:
                raise RuntimeError("Nu-Voice returned empty audio payload.")
            return audio_bytes

    @classmethod
    async def synthesize_scene_clip(
        cls,
        script_id: int,
        clip_id: int,
        spoken_dialogue: str,
        voice_id: str = "af_heart",
        format: str = "mp3"
    ) -> Dict[str, Any]:
        """Synthesizes audio for a single scene clip and persists it in local storage."""
        audio_bytes = await cls.synthesize_speech(spoken_dialogue, voice_id=voice_id, format=format)
        filename = f"clip_{script_id}_{clip_id}.{format}"
        file_path = STORAGE_DIR / filename

        with open(file_path, "wb") as f:
            f.write(audio_bytes)

        duration = estimate_audio_duration(spoken_dialogue, len(audio_bytes))
        audio_url = f"/api/voice/audio/{filename}"

        return {
            "filename": filename,
            "file_path": str(file_path),
            "audio_url": audio_url,
            "duration": duration,
            "bytes_size": len(audio_bytes)
        }

    @classmethod
    async def merge_script_clips(
        cls,
        script_id: int,
        clip_filenames: List[str],
        format: str = "mp3"
    ) -> Dict[str, Any]:
        """Merges multiple scene audio clips into a master script audio file."""
        master_filename = f"script_{script_id}_master.{format}"
        master_path = STORAGE_DIR / master_filename

        combined_bytes = bytearray()
        for cname in clip_filenames:
            cpath = STORAGE_DIR / cname
            if cpath.exists():
                with open(cpath, "rb") as f:
                    combined_bytes.extend(f.read())

        with open(master_path, "wb") as f:
            f.write(combined_bytes)

        return {
            "master_filename": master_filename,
            "master_path": str(master_path),
            "master_audio_url": f"/api/voice/audio/{master_filename}",
            "bytes_size": len(combined_bytes)
        }

