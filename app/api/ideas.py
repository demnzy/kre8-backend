from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.models import User, ContentIdea, ContentItem, Script, NewsArticle, CreatorWatchlist, UserPreferences
from app.schemas.schemas import ContentIdeaCreate, ContentIdeaUpdate, ContentIdeaOut, ContentItemOut, ScriptOut, IdeasSynthesizeRequest
from app.services.ai_service import ai_service
from app.api.auth import get_current_user

router = APIRouter(prefix="/ideas", tags=["ideas"])

@router.get("", response_model=List[ContentIdeaOut])
def list_ideas(
    status: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
    is_favorite: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(ContentIdea).filter(ContentIdea.user_id == current_user.id)
    if status:
        query = query.filter(ContentIdea.status == status)
    if platform:
        query = query.filter(ContentIdea.intended_platform == platform)
    if is_favorite is not None:
        query = query.filter(ContentIdea.is_favorite == is_favorite)
    if search:
        query = query.filter(ContentIdea.title.ilike(f"%{search}%"))

    return query.order_by(ContentIdea.created_at.desc()).all()

@router.post("", response_model=ContentIdeaOut)
def create_idea(
    idea_in: ContentIdeaCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    idea = ContentIdea(
        user_id=current_user.id,
        **idea_in.model_dump()
    )
    db.add(idea)
    db.commit()
    db.refresh(idea)
    return idea

@router.put("/{idea_id}", response_model=ContentIdeaOut)
def update_idea(
    idea_id: int,
    idea_in: ContentIdeaUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    idea = db.query(ContentIdea).filter(ContentIdea.id == idea_id, ContentIdea.user_id == current_user.id).first()
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")

    for field, val in idea_in.model_dump(exclude_unset=True).items():
        setattr(idea, field, val)

    db.commit()
    db.refresh(idea)
    return idea

@router.delete("/{idea_id}")
def delete_idea(
    idea_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    idea = db.query(ContentIdea).filter(ContentIdea.id == idea_id, ContentIdea.user_id == current_user.id).first()
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")

    db.delete(idea)
    db.commit()
    return {"message": "Idea deleted"}

@router.post("/{idea_id}/convert-to-content", response_model=ContentItemOut)
def convert_idea_to_content(
    idea_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    idea = db.query(ContentIdea).filter(ContentIdea.id == idea_id, ContentIdea.user_id == current_user.id).first()
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")

    item = ContentItem(
        user_id=current_user.id,
        title=idea.title,
        description=f"{idea.description or ''}\n\nNotes: {idea.notes or ''}",
        category=idea.category,
        platform=idea.intended_platform,
        status="Idea",
        priority=idea.priority
    )
    db.add(item)
    idea.status = "Converted"
    db.commit()
    db.refresh(item)
    return item

@router.post("/synthesize", response_model=List[ContentIdeaOut])
async def synthesize_ideas(
    req: IdeasSynthesizeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Synthesize high-impact content ideas from breaking news, a creator's watchlist style, or custom prompts."""
    prefs = db.query(UserPreferences).filter(UserPreferences.user_id == current_user.id).first()
    user_niche = (prefs.sub_niche if prefs and prefs.sub_niche else (prefs.primary_niche if prefs and prefs.primary_niche else "Technology"))

    news_article = None
    if req.news_article_id:
        news_article = db.query(NewsArticle).filter(NewsArticle.id == req.news_article_id).first()

    creator = None
    if req.creator_watchlist_id:
        creator = db.query(CreatorWatchlist).filter(
            CreatorWatchlist.id == req.creator_watchlist_id,
            CreatorWatchlist.user_id == current_user.id
        ).first()

    try:
        raw_ideas = await ai_service.synthesize_ideas_cross_pillar(
            user_niche=user_niche,
            source_type=req.source_type,
            news_article=news_article,
            creator=creator,
            topic_prompt=req.topic_prompt,
            count=req.count or 3,
            prefs=prefs
        )

        saved_ideas = []
        for item in raw_ideas:
            hooks = item.get("hook_formulas", [])
            points = item.get("talking_points", [])
            pacing = item.get("pacing_note", "")

            notes_sections = []
            if pacing:
                notes_sections.append(f"Pacing & Style:\n{pacing}")
            if hooks:
                notes_sections.append("Hook Formulas:\n" + "\n".join([f"• {h}" for h in hooks]))
            if points:
                notes_sections.append("Talking Points:\n" + "\n".join([f"- {p}" for p in points]))

            source_insp = None
            tags = list(item.get("tags", []))
            if news_article:
                source_insp = f"News: {news_article.headline}"
                tags.append("news-driven")
            if creator:
                source_insp = f"Inspired by {creator.creator_name} ({creator.handle})" if not source_insp else f"{source_insp} + {creator.creator_name} style"
                tags.append("watchlist-inspired")
                tags.append(creator.handle.lower().lstrip('@'))

            idea = ContentIdea(
                user_id=current_user.id,
                title=item.get("title", "Untitled Angle"),
                description=item.get("description", ""),
                category=item.get("category", user_niche),
                intended_platform=item.get("intended_platform", "YouTube"),
                source_inspiration=source_insp,
                priority=item.get("priority", "High"),
                tags=list(set(tags)),
                status="Active",
                notes="\n\n".join(notes_sections) if notes_sections else None
            )
            db.add(idea)
            saved_ideas.append(idea)

        db.commit()
        for s in saved_ideas:
            db.refresh(s)
        return saved_ideas
    except (PermissionError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
