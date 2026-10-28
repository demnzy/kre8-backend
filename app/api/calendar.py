from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.models import User, CalendarEvent, ContentItem
from app.schemas.schemas import CalendarEventCreate, CalendarEventUpdate, CalendarEventOut
from app.api.auth import get_current_user

router = APIRouter(prefix="/calendar", tags=["calendar"])

@router.get("", response_model=List[CalendarEventOut])
def list_events(
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(CalendarEvent).filter(CalendarEvent.user_id == current_user.id)
    if start:
        query = query.filter(CalendarEvent.start_time >= start)
    if end:
        query = query.filter(CalendarEvent.start_time <= end)
    return query.order_by(CalendarEvent.start_time.asc()).all()

@router.post("", response_model=CalendarEventOut)
def create_event(
    event_in: CalendarEventCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    event = CalendarEvent(
        user_id=current_user.id,
        title=event_in.title,
        start_time=event_in.start_time,
        end_time=event_in.end_time,
        content_item_id=event_in.content_item_id,
        event_type=event_in.event_type or "Planned",
        platform=event_in.platform or "YouTube",
        reminder_minutes_before=event_in.reminder_minutes_before or 30,
        notes=event_in.notes
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event

@router.put("/{event_id}", response_model=CalendarEventOut)
def update_event(
    event_id: int,
    event_in: CalendarEventUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    event = db.query(CalendarEvent).filter(CalendarEvent.id == event_id, CalendarEvent.user_id == current_user.id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    for field, val in event_in.model_dump(exclude_unset=True).items():
        setattr(event, field, val)

    db.commit()
    db.refresh(event)
    return event

@router.delete("/{event_id}")
def delete_event(
    event_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    event = db.query(CalendarEvent).filter(CalendarEvent.id == event_id, CalendarEvent.user_id == current_user.id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    db.delete(event)
    db.commit()
    return {"message": "Event deleted"}
