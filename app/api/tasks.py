from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.models import User, Task
from app.schemas.schemas import TaskCreate, TaskUpdate, TaskOut
from app.api.auth import get_current_user

router = APIRouter(prefix="/tasks", tags=["tasks"])

@router.get("", response_model=List[TaskOut])
def list_tasks(
    is_completed: Optional[bool] = Query(None),
    priority: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(Task).filter(Task.user_id == current_user.id)
    if is_completed is not None:
        query = query.filter(Task.is_completed == is_completed)
    if priority:
        query = query.filter(Task.priority == priority)
    return query.order_by(Task.due_date.asc().nullslast(), Task.id.desc()).all()

@router.post("", response_model=TaskOut)
def create_task(
    task_in: TaskCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    checklist_data = [item.model_dump() for item in (task_in.checklist or [])]
    task = Task(
        user_id=current_user.id,
        title=task_in.title,
        description=task_in.description,
        content_item_id=task_in.content_item_id,
        due_date=task_in.due_date,
        priority=task_in.priority or "Medium",
        is_completed=task_in.is_completed or False,
        checklist=checklist_data
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task

@router.put("/{task_id}", response_model=TaskOut)
def update_task(
    task_id: int,
    task_in: TaskUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == current_user.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    update_dict = task_in.model_dump(exclude_unset=True)
    if "checklist" in update_dict and update_dict["checklist"] is not None:
        update_dict["checklist"] = [item.model_dump() if hasattr(item, "model_dump") else item for item in update_dict["checklist"]]

    for field, val in update_dict.items():
        setattr(task, field, val)

    db.commit()
    db.refresh(task)
    return task

@router.delete("/{task_id}")
def delete_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == current_user.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    db.delete(task)
    db.commit()
    return {"message": "Task deleted"}
