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
from app.models.models import User, Script, ScriptClip
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
        clip.audio_url = result["audio_url"]
        clip.audio_duration = result["duration"]
        db.commit()
        db.refresh(clip)
        return clip
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Voice synthesis failed: {str(e)}")

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
        # Concurrent synthesis for fast execution without timeouts
        async def _synth_single_clip(clip_item):
            text = clip_item.spoken_dialogue or ""
            if not text.strip():
                return None
            res = await VoiceService.synthesize_scene_clip(
                script_id=script_id,
                clip_id=clip_item.id,
                spoken_dialogue=text,
                voice_id=voice_id,
                format=format
            )
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
            script.full_audio_url = master_res["master_audio_url"]
            script.voice_id = voice_id

        # Decrement free quota (increment used count by 1 per full script voiceover)
        if not is_unlimited:
            current_user.voiceover_generations_used = used + 1

        db.commit()
        db.refresh(script)
        return script
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Full script voiceover failed: {str(e)}")

@router.get("/audio/{filename}")
async def serve_audio_file(filename: str, db: Session = Depends(get_db)):
    """Streams audio file directly to browser <audio> elements with self-healing fallback."""
    # Prevent directory traversal
    safe_filename = os.path.basename(filename)
    file_path = STORAGE_DIR / safe_filename
    media_type = "audio/mpeg" if safe_filename.endswith(".mp3") else "audio/wav"

    if file_path.exists():
        return FileResponse(file_path, media_type=media_type, headers={"Accept-Ranges": "bytes"})

    # Self-healing: if server restarted or container disk was recreated
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
                try:
                    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
                    with open(file_path, "wb") as f:
                        f.write(audio_bytes)
                except Exception:
                    pass
                return Response(content=audio_bytes, media_type=media_type, headers={"Accept-Ranges": "bytes"})
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Audio regeneration failed: {str(e)}")

    master_match = re.match(r"^script_(\d+)_master\.(mp3|wav)$", safe_filename)
    if master_match:
        script_id = int(master_match.group(1))
        audio_format = master_match.group(2)
        script = db.query(Script).filter(Script.id == script_id).first()
        if script and script.clips:
            # Check if all scene clips already exist on disk for instant assembly
            all_on_disk = True
            combined = bytearray()
            for c in script.clips:
                if c.spoken_dialogue and c.spoken_dialogue.strip():
                    c_path = STORAGE_DIR / f"clip_{script_id}_{c.id}.{audio_format}"
                    if c_path.exists():
                        with open(c_path, "rb") as f:
                            combined.extend(f.read())
                    else:
                        all_on_disk = False
                        break
            if all_on_disk and combined:
                try:
                    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
                    with open(file_path, "wb") as f:
                        f.write(combined)
                except Exception:
                    pass
                return Response(content=bytes(combined), media_type=media_type, headers={"Accept-Ranges": "bytes"})

            # Parallel fallback via asyncio.gather if clips are not on disk
            lang = getattr(script, "voice_id", "en") or "en"
            try:
                async def _get_clip_bytes(clip):
                    if not clip.spoken_dialogue or not clip.spoken_dialogue.strip():
                        return b""
                    c_path = STORAGE_DIR / f"clip_{script_id}_{clip.id}.{audio_format}"
                    if c_path.exists():
                        with open(c_path, "rb") as f:
                            return f.read()
                    data = await VoiceService.synthesize_speech(clip.spoken_dialogue, voice_id=lang, format=audio_format)
                    try:
                        with open(c_path, "wb") as f:
                            f.write(data)
                    except Exception:
                        pass
                    return data

                clip_data_list = await asyncio.gather(*[_get_clip_bytes(c) for c in script.clips])
                combined = bytearray()
                for d in clip_data_list:
                    combined.extend(d)

                if combined:
                    try:
                        STORAGE_DIR.mkdir(parents=True, exist_ok=True)
                        with open(file_path, "wb") as f:
                            f.write(combined)
                    except Exception:
                        pass
                    return Response(content=bytes(combined), media_type=media_type, headers={"Accept-Ranges": "bytes"})
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Master audio regeneration failed: {str(e)}")

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

    # 1. Check if master file exists on disk (.mp3 or .wav)
    for ext, mtype in [("mp3", "audio/mpeg"), ("wav", "audio/wav")]:
        file_path = STORAGE_DIR / f"script_{script_id}_master.{ext}"
        if file_path.exists():
            download_name = f"{safe_title}_voiceover.{ext}"
            return FileResponse(
                file_path,
                media_type=mtype,
                filename=download_name,
                headers={"Content-Disposition": f'attachment; filename="{download_name}"'}
            )

    # 2. Check if all scene clip files already exist on disk (instant merge without network delay)
    if script.clips:
        for ext, mtype in [("mp3", "audio/mpeg"), ("wav", "audio/wav")]:
            assembled = bytearray()
            all_found = True
            for c in script.clips:
                if c.spoken_dialogue and c.spoken_dialogue.strip():
                    c_path = STORAGE_DIR / f"clip_{script_id}_{c.id}.{ext}"
                    if c_path.exists():
                        with open(c_path, "rb") as f:
                            assembled.extend(f.read())
                    else:
                        all_found = False
                        break
            if all_found and assembled:
                master_file = STORAGE_DIR / f"script_{script_id}_master.{ext}"
                try:
                    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
                    with open(master_file, "wb") as f:
                        f.write(assembled)
                except Exception:
                    pass
                download_name = f"{safe_title}_voiceover.{ext}"
                return FileResponse(
                    master_file,
                    media_type=mtype,
                    filename=download_name,
                    headers={"Content-Disposition": f'attachment; filename="{download_name}"'}
                )

        # 3. Concurrent synthesis fallback if clips need to be generated
        lang = getattr(script, "voice_id", "en") or "en"
        fmt = "mp3"
        mtype = "audio/mpeg"

        async def _fetch_or_synth(clip):
            if not clip.spoken_dialogue or not clip.spoken_dialogue.strip():
                return b""
            c_path = STORAGE_DIR / f"clip_{script_id}_{clip.id}.{fmt}"
            if c_path.exists():
                with open(c_path, "rb") as f:
                    return f.read()
            audio_bytes = await VoiceService.synthesize_speech(clip.spoken_dialogue, voice_id=lang, format=fmt)
            try:
                STORAGE_DIR.mkdir(parents=True, exist_ok=True)
                with open(c_path, "wb") as f:
                    f.write(audio_bytes)
            except Exception:
                pass
            return audio_bytes

        try:
            results = await asyncio.gather(*[_fetch_or_synth(c) for c in script.clips])
            combined = bytearray()
            for r in results:
                combined.extend(r)

            if combined:
                master_file = STORAGE_DIR / f"script_{script_id}_master.{fmt}"
                try:
                    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
                    with open(master_file, "wb") as f:
                        f.write(combined)
                except Exception:
                    pass
                download_name = f"{safe_title}_voiceover.{fmt}"
                return Response(
                    content=bytes(combined),
                    media_type=mtype,
                    headers={"Content-Disposition": f'attachment; filename="{download_name}"'}
                )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Audio download generation failed: {str(e)}")

    raise HTTPException(status_code=404, detail="Master audio not generated yet")

