from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.models import User, ContentItem, Script
from app.schemas.schemas import ContentItemCreate, ContentItemUpdate, ContentItemOut
from app.api.auth import get_current_user

router = APIRouter(prefix="/content", tags=["content"])

@router.get("", response_model=List[ContentItemOut])
def list_content_items(
    status: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(ContentItem).filter(ContentItem.user_id == current_user.id)
    if status:
        query = query.filter(ContentItem.status == status)
    if platform:
        query = query.filter(ContentItem.platform == platform)
    if priority:
        query = query.filter(ContentItem.priority == priority)
    if search:
        query = query.filter(ContentItem.title.ilike(f"%{search}%"))
    
    return query.order_by(ContentItem.updated_at.desc()).all()

@router.post("", response_model=ContentItemOut)
def create_content_item(
    item_in: ContentItemCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    item = ContentItem(
        user_id=current_user.id,
        **item_in.model_dump()
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item

@router.get("/{item_id}", response_model=ContentItemOut)
def get_content_item(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    item = db.query(ContentItem).filter(ContentItem.id == item_id, ContentItem.user_id == current_user.id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Content item not found")
    return item

@router.put("/{item_id}", response_model=ContentItemOut)
def update_content_item(
    item_id: int,
    item_in: ContentItemUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    item = db.query(ContentItem).filter(ContentItem.id == item_id, ContentItem.user_id == current_user.id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Content item not found")

    for field, val in item_in.model_dump(exclude_unset=True).items():
        setattr(item, field, val)

    db.commit()
    db.refresh(item)
    return item

@router.delete("/{item_id}")
def delete_content_item(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    item = db.query(ContentItem).filter(ContentItem.id == item_id, ContentItem.user_id == current_user.id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Content item not found")

    db.delete(item)
    db.commit()
    return {"message": "Content item deleted"}
