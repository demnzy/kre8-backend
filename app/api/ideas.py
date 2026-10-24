from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.models import User, ContentIdea, ContentItem, Script
from app.schemas.schemas import ContentIdeaCreate, ContentIdeaUpdate, ContentIdeaOut, ContentItemOut, ScriptOut
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
