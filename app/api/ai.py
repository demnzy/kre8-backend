from typing import List, Dict, Any, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.models import User, UserPreferences, Script, ScriptClip, SocialAccount, AnalyticsSnapshot, ContentItem
from app.schemas.schemas import (
    AIScriptGenRequest,
    AIClipsBreakdownRequest,
    AIPerformanceReviewRequest,
    AIReviseScriptRequest,
    AIReviseScriptResponse,
    AITestConnectionRequest
)
from app.services.ai_service import ai_service
from app.api.auth import get_current_user
from pydantic import BaseModel

router = APIRouter(prefix="/ai", tags=["ai"])

@router.post("/generate-script")
async def generate_script(
    req: AIScriptGenRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    prefs = db.query(UserPreferences).filter(UserPreferences.user_id == current_user.id).first()
    niche = req.niche or (prefs.primary_niche if prefs else "Technology")

    try:
        result = await ai_service.generate_script(
            topic=req.topic,
            niche=niche,
            platform=req.platform or "YouTube",
            format=req.format or "Short Video",
            tone=req.tone or "Engaging",
            duration_sec=req.target_duration_seconds or 60,
            custom_instructions=req.custom_instructions,
            prefs=prefs
        )
        return result
    except (PermissionError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/revise-script", response_model=AIReviseScriptResponse)
async def revise_script(
    req: AIReviseScriptRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Interactively revise an existing script with conversational creator instructions and automatic versioning."""
    prefs = db.query(UserPreferences).filter(UserPreferences.user_id == current_user.id).first()

    script = None
    if req.script_id:
        script = db.query(Script).filter(Script.id == req.script_id, Script.user_id == current_user.id).first()

    # Call multi-provider revision engine
    script_text = req.effective_script or (script.full_script if script else "")
    script_clips = req.effective_clips or ([
        {
            "clip_number": c.clip_number,
            "spoken_dialogue": c.spoken_dialogue,
            "estimated_duration": c.estimated_duration,
            "on_screen_text": c.on_screen_text,
            "visual_direction": c.visual_direction,
            "transition": c.transition
        }
        for c in (script.clips if script and script.clips else [])
    ])

    try:
        result = await ai_service.revise_script(
            current_script=script_text,
            instruction=req.instruction,
            current_clips=script_clips,
            conversation_history=req.conversation_history,
            tone=req.tone or (prefs.preferred_tone if prefs else "Conversational"),
            target_duration_seconds=req.target_duration_seconds or 60,
            prefs=prefs
        )
    except (PermissionError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    saved_versions = []
    version_num = 1
    # Save version snapshot in DB if script exists
    if script:
        existing_versions = script.versions or []
        updated_versions = list(existing_versions)

        # If this is the first revision and no initial draft was snapshotted, snapshot original state as v1
        if not updated_versions:
            updated_versions.append({
                "version": 1,
                "label": "Initial Draft",
                "full_script": script.full_script,
                "clips": [
                    {
                        "clip_number": c.clip_number,
                        "spoken_dialogue": c.spoken_dialogue,
                        "estimated_duration": c.estimated_duration,
                        "on_screen_text": c.on_screen_text,
                        "visual_direction": c.visual_direction,
                        "transition": c.transition
                    }
                    for c in script.clips
                ] if script.clips else script_clips,
                "timestamp": script.created_at.isoformat() if hasattr(script, "created_at") and script.created_at else datetime.utcnow().isoformat()
            })

        # Next version number
        version_num = len(updated_versions) + 1
        revised_text = result.get("revised_script", script_text)
        revised_clips_data = result.get("revised_clips", []) or script_clips

        updated_versions.append({
            "version": version_num,
            "label": req.instruction[:60] if req.instruction else f"Revision {version_num}",
            "full_script": revised_text,
            "clips": revised_clips_data,
            "timestamp": datetime.utcnow().isoformat()
        })

        script.versions = updated_versions
        saved_versions = updated_versions

        # Apply updated text
        script.full_script = revised_text

        # Update clips
        if "revised_clips" in result and result["revised_clips"]:
            db.query(ScriptClip).filter(ScriptClip.script_id == script.id).delete()
            for c in result["revised_clips"]:
                clip = ScriptClip(
                    script_id=script.id,
                    clip_number=c.get("clip_number", 1),
                    spoken_dialogue=c.get("spoken_dialogue", ""),
                    estimated_duration=c.get("estimated_duration", 5),
                    on_screen_text=c.get("on_screen_text", ""),
                    visual_direction=c.get("visual_direction", ""),
                    transition=c.get("transition", "Cut")
                )
                db.add(clip)

        db.commit()
        db.refresh(script)

    return AIReviseScriptResponse(
        revised_script=result.get("revised_script", script_text),
        revised_clips=result.get("revised_clips", []),
        summary_of_changes=result.get("summary_of_changes", "Script revised."),
        assistant_message=result.get("assistant_message", "Script updated!"),
        version_number=version_num,
        used_provider=result.get("used_provider", "gemini"),
        used_model=result.get("used_model", "default"),
        versions=saved_versions
    )

@router.post("/breakdown-clips")
async def breakdown_clips(
    req: AIClipsBreakdownRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    prefs = db.query(UserPreferences).filter(UserPreferences.user_id == current_user.id).first()
    try:
        clips = await ai_service.breakdown_clips(
            script_text=req.script_text,
            target_duration=req.target_duration or 60,
            prefs=prefs
        )
        return {"clips": clips}
    except (PermissionError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/performance-review")
async def review_performance(
    req: AIPerformanceReviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    prefs = db.query(UserPreferences).filter(UserPreferences.user_id == current_user.id).first()
    accounts = db.query(SocialAccount).filter(
        SocialAccount.user_id == current_user.id,
        SocialAccount.is_connected == True
    ).all()
    platform_metrics = []
    total_followers = 0
    total_views = 0
    all_recent_uploads = []
    cadences = []
    avg_views_list = []

    for acc in accounts:
        snap = (
            db.query(AnalyticsSnapshot)
            .filter(AnalyticsSnapshot.social_account_id == acc.id)
            .order_by(AnalyticsSnapshot.date.desc())
            .first()
        )
        if snap:
            total_followers += snap.followers
            total_views += snap.views
            raw = snap.raw_data or acc.raw_details or {}
            vids = raw.get("recent_videos", [])
            if vids:
                all_recent_uploads.extend(vids)
            if raw.get("cadence_weekly"):
                cadences.append(float(raw["cadence_weekly"]))
            if raw.get("avg_views"):
                avg_views_list.append(int(raw["avg_views"]))

            platform_metrics.append({
                "platform": acc.platform,
                "account": acc.account_name,
                "followers": snap.followers,
                "views": snap.views,
                "impressions": snap.impressions,
                "engagement_rate": snap.engagement_rate,
                "total_videos": acc.total_videos_count or len(vids),
                "avg_views": raw.get("avg_views", 0),
                "cadence_weekly": raw.get("cadence_weekly", 0.0),
                "top_video": raw.get("top_video")
            })

    content_items = db.query(ContentItem).filter(ContentItem.user_id == current_user.id).all()
    published_count = sum(1 for c in content_items if c.status == "Published")
    in_prod_count = sum(1 for c in content_items if c.status not in ("Idea", "Published"))

    top_upload = max(all_recent_uploads, key=lambda x: x.get("views", 0)) if all_recent_uploads else None
    overall_avg_views = int(sum(avg_views_list) / len(avg_views_list)) if avg_views_list else (total_views // max(1, len(all_recent_uploads)) if all_recent_uploads else 0)
    overall_cadence = round(sum(cadences) / len(cadences), 1) if cadences else 0.0

    summary = {
        "timeframe": req.timeframe,
        "niche": prefs.primary_niche if prefs else "Technology",
        "sub_niche": prefs.sub_niche if prefs else "",
        "weekly_target": prefs.weekly_post_goal if prefs else 3,
        "total_followers": total_followers,
        "total_views": total_views,
        "connected_platforms": platform_metrics,
        "recent_uploads": all_recent_uploads[:10],
        "top_performing_upload": top_upload,
        "avg_views_per_upload": overall_avg_views,
        "cadence_weekly": overall_cadence,
        "published_videos": published_count,
        "videos_in_production": in_prod_count
    }
    try:
        review = await ai_service.review_performance(metrics_summary=summary, prefs=prefs)
        return review
    except (PermissionError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))

class AIListModelsRequest(BaseModel):
    provider: Optional[str] = "gemini"
    api_key: Optional[str] = None

@router.post("/list-models")
async def list_ai_models(
    req: AIListModelsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Return currently valid models for the selected provider, optionally fetching live from the provider API."""
    prefs = db.query(UserPreferences).filter(UserPreferences.user_id == current_user.id).first()
    provider = req.provider or (prefs.ai_provider if prefs else "gemini")
    return await ai_service.list_models(provider=provider, api_key=req.api_key, prefs=prefs)

class OnboardingSuggestionRequest(BaseModel):
    niche: str

@router.post("/onboarding-suggestions")
async def get_onboarding_suggestions(req: OnboardingSuggestionRequest):
    """Generate dynamic AI suggestions for topics, audience, and tone during creator onboarding."""
    return await ai_service.get_onboarding_suggestions(req.niche)

class AITestPromptRequest(BaseModel):
    prompt: str
    provider: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None

@router.post("/test-connection")
async def test_ai_connection(
    req: Optional[AITestConnectionRequest] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Test round-trip live connectivity, latency, and status for any selected provider."""
    prefs = db.query(UserPreferences).filter(UserPreferences.user_id == current_user.id).first()
    provider = req.provider if req and req.provider else (prefs.ai_provider if prefs else "gemini")
    model = req.model if req and req.model else (prefs.ai_model if prefs else None)
    key = req.api_key if req and req.api_key else None
    return await ai_service.test_connection(provider=provider, model=model, api_key=key, prefs=prefs)

@router.post("/test-prompt")
async def test_ai_prompt(
    req: AITestPromptRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Execute a live test prompt against the active or requested AI provider."""
    prefs = db.query(UserPreferences).filter(UserPreferences.user_id == current_user.id).first()
    return await ai_service.test_prompt(
        prompt=req.prompt,
        provider=req.provider,
        model=req.model,
        api_key=req.api_key,
        prefs=prefs
    )
