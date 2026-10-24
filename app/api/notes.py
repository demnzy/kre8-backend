from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.models import User, Note
from app.schemas.schemas import NoteCreate, NoteUpdate, NoteOut, AINoteExtractRequest
from app.api.auth import get_current_user

router = APIRouter(prefix="/notes", tags=["notes"])

@router.get("", response_model=List[NoteOut])
def list_notes(
    folder: Optional[str] = Query(None),
    is_pinned: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(Note).filter(Note.user_id == current_user.id)
    if folder:
        query = query.filter(Note.folder == folder)
    if is_pinned is not None:
        query = query.filter(Note.is_pinned == is_pinned)
    if search:
        query = query.filter(Note.title.ilike(f"%{search}%") | Note.content.ilike(f"%{search}%"))
    return query.order_by(Note.is_pinned.desc(), Note.updated_at.desc()).all()

@router.post("", response_model=NoteOut)
def create_note(
    note_in: NoteCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    note = Note(
        user_id=current_user.id,
        title=note_in.title,
        content=note_in.content or "",
        folder=note_in.folder or "General",
        tags=note_in.tags or [],
        is_pinned=note_in.is_pinned or False,
        linked_type=note_in.linked_type,
        linked_id=note_in.linked_id
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return note

@router.put("/{note_id}", response_model=NoteOut)
def update_note(
    note_id: int,
    note_in: NoteUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    note = db.query(Note).filter(Note.id == note_id, Note.user_id == current_user.id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    for field, val in note_in.model_dump(exclude_unset=True).items():
        setattr(note, field, val)

    db.commit()
    db.refresh(note)
    return note

@router.delete("/{note_id}")
def delete_note(
    note_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    note = db.query(Note).filter(Note.id == note_id, Note.user_id == current_user.id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    db.delete(note)
    db.commit()
    return {"message": "Note deleted"}
