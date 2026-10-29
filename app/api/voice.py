import os
import re
import asyncio
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.auth import get_current_user
from app.models.models import User, Script, ScriptClip, ScriptAudioCache
from app.schemas.schemas import (
    VoiceOption,
    VoiceQuotaOut,
    SynthesizeClipRequest,
    SynthesizeScriptRequest,
    ScriptOut,
    ScriptClipOut
)
from app.services.voice_service import VoiceService, STORAGE_DIR

router = APIRouter(prefix="/voice", tags=["Voice & TTS"])

def get_audio_bytes_from_storage_or_db(filename: str, db: Session) -> Optional[bytes]:
    """Retrieves audio bytes from disk cache or persistent DB cache (survives container restarts)."""
    safe_filename = os.path.basename(filename)
    file_path = STORAGE_DIR / safe_filename
    if file_path.exists():
        try:
            with open(file_path, "rb") as f:
                data = f.read()
                if data:
                    return data
        except Exception:
            pass

    # Fallback to persistent database cache
    try:
        cached = db.query(ScriptAudioCache).filter(ScriptAudioCache.filename == safe_filename).first()
        if cached and cached.audio_data:
            # Re-seed ephemeral disk cache for fast FileResponse serving
            try:
                STORAGE_DIR.mkdir(parents=True, exist_ok=True)
                with open(file_path, "wb") as f:
                    f.write(cached.audio_data)
            except Exception:
                pass
            return cached.audio_data
    except Exception as e:
        pass

    return None

def save_audio_bytes(filename: str, data: bytes, db: Session):
    """Saves audio bytes to both local disk and persistent database cache."""
    if not data:
        return
    safe_filename = os.path.basename(filename)
    file_path = STORAGE_DIR / safe_filename

    # Save to disk
    try:
        STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(data)
    except Exception:
        pass

    # Save to DB cache
    try:
        existing = db.query(ScriptAudioCache).filter(ScriptAudioCache.filename == safe_filename).first()
        if existing:
            existing.audio_data = data
        else:
            db.add(ScriptAudioCache(filename=safe_filename, audio_data=data))
        db.commit()
    except Exception:
        db.rollback()

@router.get("/quota", response_model=VoiceQuotaOut)
def get_user_voice_quota(current_user: User = Depends(get_current_user)):
    """Returns the creator's voiceover generation quota and remaining free uses."""
    tier = getattr(current_user, "subscription_tier", "free") or "free"
    used = getattr(current_user, "voiceover_generations_used", 0) or 0
    limit = getattr(current_user, "voiceover_generations_limit", 5) or 5
    is_unlimited = tier.lower() in ("pro", "studio", "agency")
    remaining = 9999 if is_unlimited else max(0, limit - used)

    return VoiceQuotaOut(
        subscription_tier=tier,
        voiceover_generations_used=used,
        voiceover_generations_limit=limit,
        remaining=remaining,
        is_unlimited=is_unlimited
    )

@router.get("/voices", response_model=List[VoiceOption])
def list_available_voices():
    """Returns list of studio Kokoro and Meta MMS multi-language voice engines."""
    return VoiceService.get_voices()

@router.post("/scripts/{script_id}/synthesize-clip/{clip_id}", response_model=ScriptClipOut)
async def synthesize_scene_clip(
    script_id: int,
    clip_id: int,
    req: SynthesizeClipRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Synthesizes human voiceover audio for a single scene clip using Nu-Voice."""
    clip = db.query(ScriptClip).join(Script).filter(
        ScriptClip.id == clip_id,
        Script.id == script_id,
        Script.user_id == current_user.id
    ).first()

    if not clip:
        raise HTTPException(status_code=404, detail="Scene clip not found")

    tier = getattr(current_user, "subscription_tier", "free") or "free"
    used = getattr(current_user, "voiceover_generations_used", 0) or 0
    limit = getattr(current_user, "voiceover_generations_limit", 5) or 5
    is_unlimited = tier.lower() in ("pro", "studio", "agency")

    if not is_unlimited and used >= limit:
        raise HTTPException(
            status_code=403,
            detail=f"Free voiceover limit reached ({limit}/{limit}). Upgrade to Creator Pro for unlimited studio voiceovers."
        )

    text_to_speak = req.spoken_dialogue or clip.spoken_dialogue or ""
    if not text_to_speak.strip():
        raise HTTPException(status_code=400, detail="Spoken dialogue cannot be empty.")

    try:
        result = await VoiceService.synthesize_scene_clip(
            script_id=script_id,
            clip_id=clip.id,
            spoken_dialogue=text_to_speak,
            voice_id=req.voice_id or "af_heart",
            format=req.format or "mp3"
        )
        if result.get("audio_bytes"):
            save_audio_bytes(result["filename"], result["audio_bytes"], db)
        clip.audio_url = result["audio_url"]
        clip.audio_duration = result["duration"]
        db.commit()
        db.refresh(clip)
        return clip
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Voice synthesis failed: {str(e) or repr(e)}")

@router.post("/scripts/{script_id}/synthesize-all", response_model=ScriptOut)
async def synthesize_full_script_audio(
    script_id: int,
    req: SynthesizeScriptRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Synthesizes voiceovers concurrently across all script scenes, stitches master audio, and enforces free quota."""
    script = db.query(Script).filter(
        Script.id == script_id,
        Script.user_id == current_user.id
    ).first()

    if not script:
        raise HTTPException(status_code=404, detail="Script not found")

    if not script.clips or len(script.clips) == 0:
        raise HTTPException(status_code=400, detail="Script contains no scene clips to synthesize.")

    tier = getattr(current_user, "subscription_tier", "free") or "free"
    used = getattr(current_user, "voiceover_generations_used", 0) or 0
    limit = getattr(current_user, "voiceover_generations_limit", 5) or 5
    is_unlimited = tier.lower() in ("pro", "studio", "agency")

    if not is_unlimited and used >= limit:
        raise HTTPException(
            status_code=403,
            detail=f"Free voiceover limit reached ({limit}/{limit}). Upgrade to Creator Pro for unlimited studio voiceovers."
        )

    voice_id = req.voice_id or script.voice_id or "af_heart"
    format = req.format or "mp3"

    try:
        # Limit concurrency to 2 to prevent overloading the voice engine on CPU
        sem = asyncio.Semaphore(2)

        async def _synth_single_clip(clip_item):
            text = clip_item.spoken_dialogue or ""
            if not text.strip():
                return None
            async with sem:
                res = await VoiceService.synthesize_scene_clip(
                    script_id=script_id,
                    clip_id=clip_item.id,
                    spoken_dialogue=text,
                    voice_id=voice_id,
                    format=format
                )
            if res.get("audio_bytes"):
                save_audio_bytes(res["filename"], res["audio_bytes"], db)
            clip_item.audio_url = res["audio_url"]
            clip_item.audio_duration = res["duration"]
            return res["filename"]

        results = await asyncio.gather(*[_synth_single_clip(c) for c in script.clips])
        clip_filenames = [fn for fn in results if fn]

        if clip_filenames:
            master_res = await VoiceService.merge_script_clips(
                script_id=script_id,
                clip_filenames=clip_filenames,
                format=format
            )
            if master_res.get("combined_bytes"):
                save_audio_bytes(master_res["master_filename"], master_res["combined_bytes"], db)
            script.full_audio_url = master_res["master_audio_url"]
            script.voice_id = voice_id

        # Decrement free quota (increment used count by 1 per full script voiceover)
        if not is_unlimited:
            current_user.voiceover_generations_used = used + 1

        db.commit()
        db.refresh(script)
        return script
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Full script voiceover failed: {str(e) or repr(e)}")

@router.get("/audio/{filename}")
async def serve_audio_file(filename: str, db: Session = Depends(get_db)):
    """Streams audio file directly to browser <audio> elements with database cache fallback."""
    safe_filename = os.path.basename(filename)
    media_type = "audio/mpeg" if safe_filename.endswith(".mp3") else "audio/wav"

    # 1. Fast path: check disk cache or persistent db cache
    cached_bytes = get_audio_bytes_from_storage_or_db(safe_filename, db)
    if cached_bytes:
        return Response(content=cached_bytes, media_type=media_type, headers={"Accept-Ranges": "bytes"})

    # 2. Self-healing clip generation if not found in db or disk
    clip_match = re.match(r"^clip_(\d+)_(\d+)\.(mp3|wav)$", safe_filename)
    if clip_match:
        script_id = int(clip_match.group(1))
        clip_id = int(clip_match.group(2))
        audio_format = clip_match.group(3)
        clip = db.query(ScriptClip).filter(ScriptClip.id == clip_id).first()
        if clip and clip.spoken_dialogue:
            script = db.query(Script).filter(Script.id == script_id).first()
            lang = getattr(script, "voice_id", "en") or "en"
            try:
                audio_bytes = await VoiceService.synthesize_speech(clip.spoken_dialogue, voice_id=lang, format=audio_format)
                if audio_bytes:
                    save_audio_bytes(safe_filename, audio_bytes, db)
                    return Response(content=audio_bytes, media_type=media_type, headers={"Accept-Ranges": "bytes"})
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Audio regeneration failed: {str(e) or repr(e)}")

    # 3. Self-healing master audio merge
    master_match = re.match(r"^script_(\d+)_master\.(mp3|wav)$", safe_filename)
    if master_match:
        script_id = int(master_match.group(1))
        audio_format = master_match.group(2)
        script = db.query(Script).filter(Script.id == script_id).first()
        if script and script.clips:
            # Check if all scene clips exist in cache
            all_found = True
            combined = bytearray()
            for c in script.clips:
                if c.spoken_dialogue and c.spoken_dialogue.strip():
                    c_data = get_audio_bytes_from_storage_or_db(f"clip_{script_id}_{c.id}.{audio_format}", db)
                    if c_data:
                        combined.extend(c_data)
                    else:
                        all_found = False
                        break
            if all_found and combined:
                save_audio_bytes(safe_filename, bytes(combined), db)
                return Response(content=bytes(combined), media_type=media_type, headers={"Accept-Ranges": "bytes"})

            # Fallback: synthesize missing clips with semaphore limit
            lang = getattr(script, "voice_id", "en") or "en"
            sem = asyncio.Semaphore(2)
            try:
                async def _get_clip_bytes(clip):
                    if not clip.spoken_dialogue or not clip.spoken_dialogue.strip():
                        return b""
                    c_name = f"clip_{script_id}_{clip.id}.{audio_format}"
                    cached = get_audio_bytes_from_storage_or_db(c_name, db)
                    if cached:
                        return cached
                    async with sem:
                        data = await VoiceService.synthesize_speech(clip.spoken_dialogue, voice_id=lang, format=audio_format)
                    if data:
                        save_audio_bytes(c_name, data, db)
                    return data

                clip_data_list = await asyncio.gather(*[_get_clip_bytes(c) for c in script.clips])
                combined = bytearray()
                for d in clip_data_list:
                    combined.extend(d)

                if combined:
                    save_audio_bytes(safe_filename, bytes(combined), db)
                    return Response(content=bytes(combined), media_type=media_type, headers={"Accept-Ranges": "bytes"})
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Master audio regeneration failed: {str(e) or repr(e)}")

    raise HTTPException(status_code=404, detail="Audio file not found")

@router.get("/scripts/{script_id}/download-master")
async def download_master_audio(
    script_id: int,
    db: Session = Depends(get_db)
):
    """Direct one-click download for master script audio."""
    script = db.query(Script).filter(Script.id == script_id).first()

    if not script:
        raise HTTPException(status_code=404, detail="Script not found")

    safe_title = re.sub(r"[^a-zA-Z0-9_\- ]", "", script.title).replace(" ", "_")
    if not safe_title:
        safe_title = f"script_{script_id}"

    # If full_audio_url is an external link (CDN), redirect directly
    if script.full_audio_url and (script.full_audio_url.startswith("http://") or script.full_audio_url.startswith("https://")):
        return RedirectResponse(url=script.full_audio_url, status_code=307)

    # 1. Check if master file exists in storage or persistent db cache (.mp3 or .wav)
    for ext, mtype in [("mp3", "audio/mpeg"), ("wav", "audio/wav")]:
        master_fname = f"script_{script_id}_master.{ext}"
        master_bytes = get_audio_bytes_from_storage_or_db(master_fname, db)
        if master_bytes:
            download_name = f"{safe_title}_voiceover.{ext}"
            return Response(
                content=master_bytes,
                media_type=mtype,
                headers={"Content-Disposition": f'attachment; filename="{download_name}"'}
            )

    # 2. Check if all scene clip files already exist in storage/DB (instant merge without network delay)
    if script.clips:
        for ext, mtype in [("mp3", "audio/mpeg"), ("wav", "audio/wav")]:
            assembled = bytearray()
            all_found = True
            for c in script.clips:
                if c.spoken_dialogue and c.spoken_dialogue.strip():
                    c_bytes = get_audio_bytes_from_storage_or_db(f"clip_{script_id}_{c.id}.{ext}", db)
                    if c_bytes:
                        assembled.extend(c_bytes)
                    else:
                        all_found = False
                        break
            if all_found and assembled:
                master_fname = f"script_{script_id}_master.{ext}"
                save_audio_bytes(master_fname, bytes(assembled), db)
                download_name = f"{safe_title}_voiceover.{ext}"
                return Response(
                    content=bytes(assembled),
                    media_type=mtype,
                    headers={"Content-Disposition": f'attachment; filename="{download_name}"'}
                )

        # 3. Fallback: synthesize missing clips with Semaphore(2) concurrency control
        lang = getattr(script, "voice_id", "en") or "en"
        fmt = "mp3"
        mtype = "audio/mpeg"
        sem = asyncio.Semaphore(2)

        async def _fetch_or_synth(clip):
            if not clip.spoken_dialogue or not clip.spoken_dialogue.strip():
                return b""
            c_name = f"clip_{script_id}_{clip.id}.{fmt}"
            cached = get_audio_bytes_from_storage_or_db(c_name, db)
            if cached:
                return cached
            async with sem:
                audio_bytes = await VoiceService.synthesize_speech(clip.spoken_dialogue, voice_id=lang, format=fmt)
            if audio_bytes:
                save_audio_bytes(c_name, audio_bytes, db)
            return audio_bytes

        try:
            results = await asyncio.gather(*[_fetch_or_synth(c) for c in script.clips])
            combined = bytearray()
            for r in results:
                combined.extend(r)

            if combined:
                master_fname = f"script_{script_id}_master.{fmt}"
                save_audio_bytes(master_fname, bytes(combined), db)
                download_name = f"{safe_title}_voiceover.{fmt}"
                return Response(
                    content=bytes(combined),
                    media_type=mtype,
                    headers={"Content-Disposition": f'attachment; filename="{download_name}"'}
                )
        except Exception as e:
            err_msg = str(e) or repr(e)
            raise HTTPException(status_code=500, detail=f"Audio download generation failed: {err_msg}")

    raise HTTPException(status_code=404, detail="Master audio not generated yet")

