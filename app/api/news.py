from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.models import User, UserPreferences, NewsArticle, NewsAIIdea, ContentIdea
from app.schemas.schemas import NewsArticleOut, NewsAIIdeaOut, ContentIdeaOut
from app.services.news_service import news_service
from app.services.ai_service import ai_service
from app.api.auth import get_current_user

router = APIRouter(prefix="/news", tags=["news"])

@router.get("/daily", response_model=List[NewsArticleOut])
async def get_daily_news(
    force_refresh: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Fetch daily latest news matching creator's Niche and Sub-Niche."""
    prefs = db.query(UserPreferences).filter(UserPreferences.user_id == current_user.id).first()
    niche = prefs.primary_niche if prefs and prefs.primary_niche else "Technology"
    sub_niche = prefs.sub_niche if prefs and prefs.sub_niche else "Artificial Intelligence & Agents"
    keywords = prefs.search_keywords if prefs else ""

    articles = await news_service.get_or_refresh_daily_news(
        db=db,
        niche=niche,
        sub_niche=sub_niche,
        keywords=keywords,
        force_refresh=force_refresh,
        api_key=prefs.news_api_key if prefs else None
    )
    return articles

@router.post("/synthesize", response_model=List[NewsAIIdeaOut])
async def synthesize_news_to_ideas(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Pipes the daily news articles into Gemini to generate actionable creator angles and viral hooks."""
    prefs = db.query(UserPreferences).filter(UserPreferences.user_id == current_user.id).first()
    niche = prefs.primary_niche if prefs and prefs.primary_niche else "Technology"
    sub_niche = prefs.sub_niche if prefs and prefs.sub_niche else "Artificial Intelligence & Agents"

    articles = db.query(NewsArticle).filter(
        NewsArticle.niche == niche,
        NewsArticle.sub_niche == sub_niche
    ).order_by(NewsArticle.id.desc()).limit(5).all()

    if not articles:
        # Fetch fresh news first
        articles = await news_service.get_or_refresh_daily_news(
            db=db, niche=niche, sub_niche=sub_niche, keywords=prefs.search_keywords if prefs else ""
        )

    ai_ideas = await ai_service.synthesize_news_into_ideas(db=db, articles=articles, prefs=prefs)
    return ai_ideas

@router.post("/save-angle-as-idea/{angle_id}", response_model=ContentIdeaOut)
def save_angle_to_ideas_bank(
    angle_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """1-Click action: Saves a generated AI news angle into the creator's Ideas Bank."""
    angle = db.query(NewsAIIdea).filter(NewsAIIdea.id == angle_id).first()
    if not angle:
        raise HTTPException(status_code=404, detail="AI Idea Angle not found")

    article = angle.news_article
    hooks_text = "\n".join([f"• {h}" for h in (angle.viral_hooks or [])])
    points_text = "\n".join([f"- {p}" for p in (angle.talking_points or [])])
    
    notes_content = f"Why it matters:\n{angle.why_it_matters}\n\nViral Hooks:\n{hooks_text}\n\nTalking Points:\n{points_text}"

    idea = ContentIdea(
        user_id=current_user.id,
        title=angle.topic_angle,
        description=angle.why_it_matters,
        category=article.sub_niche or article.niche or "Trending News",
        intended_platform="YouTube",
        source_inspiration=f"News: {article.headline} ({article.source_name}) - {article.source_url}",
        priority="High",
        tags=["trending", "news-driven", article.sub_niche.lower().replace(" ", "-") if article.sub_niche else "tech"],
        status="Active",
        notes=notes_content
    )
    db.add(idea)
    angle.is_saved_to_ideas = True
    db.commit()
    db.refresh(idea)
    return idea
