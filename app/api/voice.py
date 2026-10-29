import os
import re
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
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
            lang=req.voice_id or "en",
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
    """Synthesizes voiceovers for every scene clip in the script, stitches master audio, and enforces free quota."""
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

    clip_filenames = []
    lang = req.voice_id or script.voice_id or "en"
    format = req.format or "mp3"

    try:
        for clip in script.clips:
            text = clip.spoken_dialogue or ""
            if not text.strip():
                continue
            res = await VoiceService.synthesize_scene_clip(
                script_id=script_id,
                clip_id=clip.id,
                spoken_dialogue=text,
                lang=lang,
                format=format
            )
            clip.audio_url = res["audio_url"]
            clip.audio_duration = res["duration"]
            clip_filenames.append(res["filename"])

        if clip_filenames:
            master_res = await VoiceService.merge_script_clips(
                script_id=script_id,
                clip_filenames=clip_filenames,
                format=format
            )
            script.full_audio_url = master_res["master_audio_url"]
            script.voice_id = lang

        # Decrement free quota (increment used count by 1 per full script voiceover)
        if not is_unlimited:
            current_user.voiceover_generations_used = used + 1

        db.commit()
        db.refresh(script)
        return script
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Full script voiceover failed: {str(e)}")

@router.get("/audio/{filename}")
def serve_audio_file(filename: str):
    """Streams audio file directly to browser <audio> elements."""
    # Prevent directory traversal
    safe_filename = os.path.basename(filename)
    file_path = STORAGE_DIR / safe_filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")
    media_type = "audio/mpeg" if safe_filename.endswith(".mp3") else "audio/wav"
    return FileResponse(file_path, media_type=media_type)

@router.get("/scripts/{script_id}/download-master")
def download_master_audio(
    script_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Direct one-click download for master script audio."""
    script = db.query(Script).filter(
        Script.id == script_id,
        Script.user_id == current_user.id
    ).first()

    if not script or not script.full_audio_url:
        raise HTTPException(status_code=404, detail="Master audio not generated yet")

    filename = os.path.basename(script.full_audio_url)
    file_path = STORAGE_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Audio file missing from storage")

    safe_title = re.sub(r"[^a-zA-Z0-9_\- ]", "", script.title).replace(" ", "_")
    download_filename = f"{safe_title}_voiceover.mp3"

    return FileResponse(
        file_path,
        media_type="audio/mpeg",
        filename=download_filename,
        headers={"Content-Disposition": f'attachment; filename="{download_filename}"'}
    )
