from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from jose import jwt, JWTError
from app.core.database import get_db
from app.core.config import settings
from app.core.security import verify_password, get_password_hash, create_access_token
from app.models.models import User, UserPreferences
from app.schemas.schemas import UserRegister, UserLogin, Token

router = APIRouter(prefix="/auth", tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    # If no token provided, return default creator user (for zero-friction local development)
    default_user = db.query(User).first()
    if not token:
        if not default_user:
            default_user = User(
                email="creator@kre8.local",
                hashed_password=get_password_hash("creator123"),
                display_name="Creator"
            )
            db.add(default_user)
            db.commit()
            db.refresh(default_user)
            prefs = UserPreferences(user_id=default_user.id)
            db.add(prefs)
            db.commit()
        return default_user

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user

@router.post("/register", response_model=Token)
def register(user_in: UserRegister, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == user_in.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    user = User(
        email=user_in.email,
        hashed_password=get_password_hash(user_in.password),
        display_name=user_in.display_name or "Creator"
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    combined_sub_niche = user_in.sub_niche or "General"
    if user_in.sub_niches and len(user_in.sub_niches) > 0:
        combined_sub_niche = ", ".join(user_in.sub_niches)

    prefs = UserPreferences(
        user_id=user.id,
        primary_niche=user_in.primary_niche or "Technology",
        sub_niche=combined_sub_niche,
        search_keywords=user_in.search_keywords or f"{user_in.primary_niche}, {combined_sub_niche}",
        target_audience=user_in.target_audience or "General Audience",
        preferred_tone=user_in.preferred_tone or "Informative & Engaging",
        preferred_platforms=user_in.preferred_platforms or ["YouTube", "LinkedIn", "TikTok", "X"],
        weekly_post_goal=user_in.weekly_post_goal or 3
    )
    db.add(prefs)
    
    # Initialize initial input-driven consistency goal matching cadence target
    from app.models.models import Goal
    initial_goal = Goal(
        user_id=user.id,
        title=f"Publish {prefs.weekly_post_goal} {prefs.primary_niche} Posts Weekly",
        goal_type="Weekly Posts",
        target_value=prefs.weekly_post_goal,
        current_value=0,
        unit="posts"
    )
    db.add(initial_goal)
    db.commit()

    access_token = create_access_token(subject=user.id)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name
        }
    }

@router.post("/login", response_model=Token)
def login(user_in: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == user_in.email).first()
    if not user or not verify_password(user_in.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect email or password")

    access_token = create_access_token(subject=user.id)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name
        }
    }

@router.get("/me")
def me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    prefs = db.query(UserPreferences).filter(UserPreferences.user_id == current_user.id).first()
    return {
        "id": current_user.id,
        "email": current_user.email,
        "display_name": current_user.display_name,
        "avatar_url": current_user.avatar_url,
        "preferences": prefs
    }
