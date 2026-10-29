from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.models import User, UserPreferences, NewsArticle, NewsAIIdea, ContentIdea, CreatorWatchlist
from app.schemas.schemas import NewsArticleOut, NewsAIIdeaOut, ContentIdeaOut, NewsRegionOut
from app.core.config import settings
from app.services.news_service import news_service, REGION_CONFIG
from app.services.ai_service import ai_service
from app.api.auth import get_current_user

router = APIRouter(prefix="/news", tags=["news"])

@router.get("/regions", response_model=List[NewsRegionOut])
def get_news_regions():
    """List all supported geographic news regions with flags and descriptions."""
    return [
        NewsRegionOut(
            code=r["code"],
            label=r["label"],
            flag=r["flag"],
            description=r.get("description")
        )
        for r in REGION_CONFIG.values()
    ]

@router.get("/daily", response_model=List[NewsArticleOut])
async def get_daily_news(
    region: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    force_refresh: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Fetch daily latest news matching creator's Niche, Sub-Niche, and chosen Region."""
    prefs = db.query(UserPreferences).filter(UserPreferences.user_id == current_user.id).first()
    niche = prefs.primary_niche if prefs and prefs.primary_niche else "Technology"
    sub_niche = prefs.sub_niche if prefs and prefs.sub_niche else "Artificial Intelligence & Agents"
    keywords = prefs.search_keywords if prefs else ""
    active_key = (prefs.news_api_key if prefs and prefs.news_api_key else None) or getattr(settings, "NEWS_API_KEY", "")

    # Selected region or fall back to user preference, default to GLOBAL
    active_region = (region or (prefs.news_region if prefs and prefs.news_region else "GLOBAL")).upper()

    try:
        articles = await news_service.get_or_refresh_daily_news(
            db=db,
            niche=niche,
            sub_niche=sub_niche,
            keywords=keywords,
            force_refresh=force_refresh,
            api_key=active_key,
            region=active_region,
            category=category
        )
    except Exception as e:
        # Live fetch failed: serve the most recent cached articles instead of erroring
        print(f"[News] Live fetch failed, serving cache: {e}")
        db.rollback()
        query = db.query(NewsArticle).filter(NewsArticle.niche == niche, NewsArticle.sub_niche == sub_niche)
        if active_region != "ALL":
            query = query.filter(NewsArticle.region == active_region)
        if category and category != "all":
            query = query.filter(NewsArticle.category == category)
        articles = query.order_by(NewsArticle.id.desc()).limit(20).all()

    # Optional in-memory search filter if search parameter was passed
    if search and search.strip():
        q_lower = search.strip().lower()
        articles = [
            a for a in articles
            if q_lower in a.headline.lower() or (a.summary and q_lower in a.summary.lower())
        ]

    return articles

@router.post("/synthesize", response_model=List[NewsAIIdeaOut])
async def synthesize_news_to_ideas(
    article_id: Optional[int] = Query(None),
    creator_id: Optional[int] = Query(None),
    region: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Pipes daily news articles into the user's configured AI provider to generate actionable creator angles and viral hooks."""
    prefs = db.query(UserPreferences).filter(UserPreferences.user_id == current_user.id).first()
    niche = prefs.primary_niche if prefs and prefs.primary_niche else "Technology"
    sub_niche = prefs.sub_niche if prefs and prefs.sub_niche else "Artificial Intelligence & Agents"
    active_region = (region or (prefs.news_region if prefs and prefs.news_region else "GLOBAL")).upper()

    creator = None
    if creator_id:
        creator = db.query(CreatorWatchlist).filter(
            CreatorWatchlist.id == creator_id,
            CreatorWatchlist.user_id == current_user.id
        ).first()

    if article_id is not None:
        target = db.query(NewsArticle).filter(NewsArticle.id == article_id).first()
        if not target:
            raise HTTPException(status_code=404, detail="News article not found")
        articles = [target]
    else:
        query = db.query(NewsArticle).filter(
            NewsArticle.niche == niche,
            NewsArticle.sub_niche == sub_niche
        )
        if active_region != "ALL":
            query = query.filter(NewsArticle.region == active_region)
        articles = query.order_by(NewsArticle.id.desc()).limit(5).all()

        if not articles:
            # Fetch fresh news first
            articles = await news_service.get_or_refresh_daily_news(
                db=db,
                niche=niche,
                sub_niche=sub_niche,
                keywords=prefs.search_keywords if prefs else "",
                region=active_region
            )

    try:
        ai_ideas = await ai_service.synthesize_news_into_ideas(
            db=db,
            articles=articles,
            creator=creator,
            prefs=prefs,
            force_regenerate=(article_id is not None or creator_id is not None),
            region=active_region
        )
        return ai_ideas
    except (PermissionError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))

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
        tags=["trending", "news-driven", (article.region or "global").lower(), article.sub_niche.lower().replace(" ", "-") if article.sub_niche else "tech"],
        status="Active",
        notes=notes_content
    )
    db.add(idea)
    angle.is_saved_to_ideas = True
    db.commit()
    db.refresh(idea)
    return idea
