from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.models import User, Goal
from app.schemas.schemas import GoalCreate, GoalUpdate, GoalOut
from app.api.auth import get_current_user

router = APIRouter(prefix="/goals", tags=["goals"])

@router.get("", response_model=List[GoalOut])
def list_goals(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return db.query(Goal).filter(Goal.user_id == current_user.id).order_by(Goal.id.asc()).all()

@router.post("", response_model=GoalOut)
def create_goal(
    goal_in: GoalCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    goal = Goal(
        user_id=current_user.id,
        title=goal_in.title,
        goal_type=goal_in.goal_type,
        target_value=goal_in.target_value,
        current_value=goal_in.current_value or 0.0,
        unit=goal_in.unit or "posts",
        deadline=goal_in.deadline
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal

@router.put("/{goal_id}", response_model=GoalOut)
def update_goal(
    goal_id: int,
    goal_in: GoalUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    goal = db.query(Goal).filter(Goal.id == goal_id, Goal.user_id == current_user.id).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")

    for field, val in goal_in.model_dump(exclude_unset=True).items():
        setattr(goal, field, val)

    if "is_achieved" not in goal_in.model_dump(exclude_unset=True):
        goal.is_achieved = bool(goal.current_value >= goal.target_value)

    db.commit()
    db.refresh(goal)
    return goal

@router.delete("/{goal_id}")
def delete_goal(
    goal_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    goal = db.query(Goal).filter(Goal.id == goal_id, Goal.user_id == current_user.id).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")

    db.delete(goal)
    db.commit()
    return {"message": "Goal deleted"}
