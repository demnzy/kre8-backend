from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.models import User, UserPreferences
from app.schemas.schemas import AIScriptGenRequest, AIClipsBreakdownRequest, AIPerformanceReviewRequest
from app.services.ai_service import ai_service
from app.api.auth import get_current_user

router = APIRouter(prefix="/ai", tags=["ai"])

@router.post("/generate-script")
async def generate_script(
    req: AIScriptGenRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    prefs = db.query(UserPreferences).filter(UserPreferences.user_id == current_user.id).first()
    niche = req.niche or (prefs.primary_niche if prefs else "Technology")
    api_key = prefs.gemini_api_key if prefs else None

    try:
        result = await ai_service.generate_script(
            topic=req.topic,
            niche=niche,
            platform=req.platform or "YouTube",
            format=req.format or "Short Video",
            tone=req.tone or "Engaging",
            duration_sec=req.target_duration_seconds or 60,
            api_key=api_key
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/breakdown-clips")
async def breakdown_clips(
    req: AIClipsBreakdownRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    prefs = db.query(UserPreferences).filter(UserPreferences.user_id == current_user.id).first()
    api_key = prefs.gemini_api_key if prefs else None

    clips = await ai_service.breakdown_clips(
        script_text=req.script_text,
        target_duration=req.target_duration or 60,
        api_key=api_key
    )
    return {"clips": clips}

@router.post("/performance-review")
async def review_performance(
    req: AIPerformanceReviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    prefs = db.query(UserPreferences).filter(UserPreferences.user_id == current_user.id).first()
    api_key = prefs.gemini_api_key if prefs else None

    summary = {
        "timeframe": req.timeframe,
        "weekly_target": prefs.weekly_post_goal if prefs else 3
    }
    review = await ai_service.review_performance(metrics_summary=summary, api_key=api_key)
    return review

from pydantic import BaseModel
class OnboardingSuggestionRequest(BaseModel):
    niche: str

@router.post("/onboarding-suggestions")
async def get_onboarding_suggestions(req: OnboardingSuggestionRequest):
    """Generate dynamic AI suggestions for topics, audience, and tone during creator onboarding."""
    return await ai_service.get_onboarding_suggestions(req.niche)

class AITestConnectionRequest(BaseModel):
    api_key: Optional[str] = None

class AITestPromptRequest(BaseModel):
    prompt: str
    api_key: Optional[str] = None

@router.post("/test-connection")
async def test_ai_connection(
    req: Optional[AITestConnectionRequest] = None,
    db: Session = Depends(get_db)
):
    """Test round-trip live Gemini engine connectivity, latency, and status."""
    key = req.api_key if req else None
    return await ai_service.test_connection(api_key=key)

@router.post("/test-prompt")
async def test_ai_prompt(
    req: AITestPromptRequest,
    db: Session = Depends(get_db)
):
    """Execute a live test prompt directly against Google Gemini."""
    return await ai_service.test_prompt(prompt=req.prompt, api_key=req.api_key)

