from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.models import User, Script, ScriptClip, ContentItem
from app.schemas.schemas import ScriptCreate, ScriptUpdate, ScriptOut, ScriptClipCreate, ScriptClipOut
from app.api.auth import get_current_user

router = APIRouter(prefix="/scripts", tags=["scripts"])

@router.get("", response_model=List[ScriptOut])
def list_scripts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return db.query(Script).filter(Script.user_id == current_user.id).order_by(Script.updated_at.desc()).all()

@router.post("", response_model=ScriptOut)
def create_script(
    script_in: ScriptCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    script = Script(
        user_id=current_user.id,
        content_item_id=script_in.content_item_id,
        title=script_in.title,
        tone=script_in.tone or "Conversational",
        target_duration_seconds=script_in.target_duration_seconds or 60,
        full_script=script_in.full_script or "",
        generated_hooks=script_in.generated_hooks or [],
        generated_ctas=script_in.generated_ctas or []
    )
    db.add(script)
    db.commit()
    db.refresh(script)

    if script_in.clips:
        for c in script_in.clips:
            clip = ScriptClip(
                script_id=script.id,
                clip_number=c.clip_number,
                spoken_dialogue=c.spoken_dialogue,
                estimated_duration=c.estimated_duration,
                on_screen_text=c.on_screen_text,
                visual_direction=c.visual_direction,
                transition=c.transition or "Cut",
                cta=c.cta
            )
            db.add(clip)
        db.commit()
        db.refresh(script)

    return script

@router.get("/{script_id}", response_model=ScriptOut)
def get_script(
    script_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    script = db.query(Script).filter(Script.id == script_id, Script.user_id == current_user.id).first()
    if not script:
        raise HTTPException(status_code=404, detail="Script not found")
    return script

@router.put("/{script_id}", response_model=ScriptOut)
def update_script(
    script_id: int,
    script_in: ScriptUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    script = db.query(Script).filter(Script.id == script_id, Script.user_id == current_user.id).first()
    if not script:
        raise HTTPException(status_code=404, detail="Script not found")

    update_data = script_in.model_dump(exclude_unset=True)
    clips_data = update_data.pop("clips", None)

    for field, val in update_data.items():
        setattr(script, field, val)

    if clips_data is not None:
        db.query(ScriptClip).filter(ScriptClip.script_id == script.id).delete()
        for c in clips_data:
            clip = ScriptClip(
                script_id=script.id,
                clip_number=c["clip_number"],
                spoken_dialogue=c.get("spoken_dialogue", ""),
                estimated_duration=c.get("estimated_duration", 5),
                on_screen_text=c.get("on_screen_text", ""),
                visual_direction=c.get("visual_direction", ""),
                transition=c.get("transition", "Cut"),
                cta=c.get("cta")
            )
            db.add(clip)

    db.commit()
    db.refresh(script)
    return script

@router.delete("/{script_id}")
def delete_script(
    script_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    script = db.query(Script).filter(Script.id == script_id, Script.user_id == current_user.id).first()
    if not script:
        raise HTTPException(status_code=404, detail="Script not found")

    db.delete(script)
    db.commit()
    return {"message": "Script deleted"}
