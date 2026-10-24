from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.models import User, SocialAccount, AnalyticsSnapshot, PublishedPost, CreatorWatchlist
from app.schemas.schemas import CreatorWatchlistCreate, CreatorWatchlistOut
from app.api.auth import get_current_user

router = APIRouter(prefix="/social", tags=["social"])

@router.get("/accounts")
def list_accounts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    accounts = db.query(SocialAccount).filter(SocialAccount.user_id == current_user.id).all()
    return accounts

from pydantic import BaseModel
import re
import urllib.request

class SocialConnectPayload(BaseModel):
    account_name: Optional[str] = None
    account_id: Optional[str] = None
    avatar_url: Optional[str] = None
    followers: Optional[int] = 0
    views: Optional[int] = 0
    impressions: Optional[int] = 0
    likes: Optional[int] = 0
    comments: Optional[int] = 0
    shares: Optional[int] = 0
    engagement_rate: Optional[float] = 0.0

class SocialStatsUpdatePayload(BaseModel):
    followers: Optional[int] = None
    views: Optional[int] = None
    impressions: Optional[int] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    shares: Optional[int] = None
    engagement_rate: Optional[float] = None

class YouTubeLookupRequest(BaseModel):
    handle: str

@router.post("/youtube-lookup")
def lookup_youtube_handle(req: YouTubeLookupRequest):
    """Inspect public YouTube channel handle for live subscriber count, avatar, and channel title."""
    clean_handle = req.handle.strip().lstrip('@')
    if not clean_handle:
        raise HTTPException(status_code=400, detail="Invalid YouTube handle")

    url = f"https://www.youtube.com/@{clean_handle}"
    request_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    }
    try:
        http_req = urllib.request.Request(url, headers=request_headers)
        with urllib.request.urlopen(http_req, timeout=5) as res:
            html = res.read().decode("utf-8", errors="ignore")

            title_match = re.search(r'<title>([^<]+?)(?: - YouTube)?</title>', html)
            avatar_match = re.search(r'<meta property="og:image" content="([^"]+)"', html)
            
            # Find subscriber count
            sub_match = re.search(r'([0-9\.]+[KMBkmb]?\s+subscribers)', html, re.IGNORECASE)
            sub_str = sub_match.group(1) if sub_match else None
            
            followers = 0
            if sub_str:
                m = re.search(r'([\d\.]+)\s*([KMBkmb])?', sub_str)
                if m:
                    val = float(m.group(1))
                    unit = (m.group(2) or '').upper()
                    if unit == 'K':
                        followers = int(val * 1000)
                    elif unit == 'M':
                        followers = int(val * 1000000)
                    elif unit == 'B':
                        followers = int(val * 1000000000)
                    else:
                        followers = int(val)

            return {
                "success": True,
                "handle": f"@{clean_handle}",
                "channel_title": title_match.group(1).strip() if title_match else clean_handle,
                "subscribers_text": sub_str,
                "followers": followers,
                "avatar_url": avatar_match.group(1) if avatar_match else None
            }
    except Exception as e:
        return {
            "success": False,
            "handle": f"@{clean_handle}",
            "channel_title": clean_handle,
            "subscribers_text": None,
            "followers": 0,
            "avatar_url": None,
            "message": f"Could not fetch public stats: {str(e)}"
        }

@router.post("/connect/{platform}")
def connect_account(
    platform: str,
    payload: Optional[SocialConnectPayload] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Connect an account for YouTube, LinkedIn, TikTok, Instagram, or X with real creator stats."""
    existing = db.query(SocialAccount).filter(
        SocialAccount.user_id == current_user.id,
        SocialAccount.platform == platform.lower()
    ).first()

    name = (payload.account_name if payload and payload.account_name else None) or f"@{current_user.display_name.lower()}_{platform.lower()}"
    avatar = payload.avatar_url if payload else None

    followers = (payload.followers if payload and payload.followers is not None else 0)
    views = (payload.views if payload and payload.views is not None else 0)
    impressions = (payload.impressions if payload and payload.impressions is not None else views * 2)
    likes = (payload.likes if payload and payload.likes is not None else 0)
    comments = (payload.comments if payload and payload.comments is not None else 0)
    shares = (payload.shares if payload and payload.shares is not None else 0)
    engagement_rate = (payload.engagement_rate if payload and payload.engagement_rate is not None else 0.0)

    if not existing:
        existing = SocialAccount(
            user_id=current_user.id,
            platform=platform.lower(),
            account_name=name,
            account_id=payload.account_id if payload and payload.account_id else f"{platform.lower()}_act_{current_user.id}",
            avatar_url=avatar,
            is_connected=True,
            last_synced_at=datetime.utcnow()
        )
        db.add(existing)
        db.commit()
        db.refresh(existing)

        snap = AnalyticsSnapshot(
            social_account_id=existing.id,
            followers=followers,
            views=views,
            impressions=impressions,
            likes=likes,
            comments=comments,
            shares=shares,
            engagement_rate=engagement_rate
        )
        db.add(snap)
        db.commit()
    else:
        existing.is_connected = True
        existing.account_name = name
        if avatar:
            existing.avatar_url = avatar
        existing.last_synced_at = datetime.utcnow()
        db.commit()

        # Update or record new snapshot with new baseline numbers
        latest_snap = db.query(AnalyticsSnapshot).filter(
            AnalyticsSnapshot.social_account_id == existing.id
        ).order_by(AnalyticsSnapshot.date.desc()).first()

        if latest_snap and (latest_snap.date.date() == datetime.utcnow().date()):
            if followers: latest_snap.followers = followers
            if views: latest_snap.views = views
            if impressions: latest_snap.impressions = impressions
            if likes: latest_snap.likes = likes
            if comments: latest_snap.comments = comments
            if shares: latest_snap.shares = shares
            if engagement_rate: latest_snap.engagement_rate = engagement_rate
            db.commit()
        else:
            snap = AnalyticsSnapshot(
                social_account_id=existing.id,
                followers=followers,
                views=views,
                impressions=impressions,
                likes=likes,
                comments=comments,
                shares=shares,
                engagement_rate=engagement_rate
            )
            db.add(snap)
            db.commit()

    return {"message": f"{platform.capitalize()} connected successfully", "account": existing}

@router.put("/accounts/{account_id}/stats")
def update_account_stats(
    account_id: int,
    payload: SocialStatsUpdatePayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Manually update or sync statistics for a connected channel."""
    account = db.query(SocialAccount).filter(
        SocialAccount.id == account_id,
        SocialAccount.user_id == current_user.id
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Social account not found")

    snap = db.query(AnalyticsSnapshot).filter(
        AnalyticsSnapshot.social_account_id == account.id
    ).order_by(AnalyticsSnapshot.date.desc()).first()

    if not snap or (snap.date.date() != datetime.utcnow().date()):
        snap = AnalyticsSnapshot(
            social_account_id=account.id,
            followers=snap.followers if snap else 0,
            views=snap.views if snap else 0,
            impressions=snap.impressions if snap else 0,
            likes=snap.likes if snap else 0,
            comments=snap.comments if snap else 0,
            shares=snap.shares if snap else 0,
            engagement_rate=snap.engagement_rate if snap else 0.0
        )
        db.add(snap)

    if payload.followers is not None:
        snap.followers = payload.followers
    if payload.views is not None:
        snap.views = payload.views
    if payload.impressions is not None:
        snap.impressions = payload.impressions
    if payload.likes is not None:
        snap.likes = payload.likes
    if payload.comments is not None:
        snap.comments = payload.comments
    if payload.shares is not None:
        snap.shares = payload.shares
    if payload.engagement_rate is not None:
        snap.engagement_rate = payload.engagement_rate

    account.last_synced_at = datetime.utcnow()
    db.commit()
    return {"message": "Channel stats updated successfully", "snapshot": {
        "followers": snap.followers,
        "views": snap.views,
        "impressions": snap.impressions,
        "engagement_rate": snap.engagement_rate
    }}

@router.post("/disconnect/{account_id}")
def disconnect_account(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    account = db.query(SocialAccount).filter(
        SocialAccount.id == account_id,
        SocialAccount.user_id == current_user.id
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    account.is_connected = False
    db.commit()
    return {"message": "Account disconnected"}

@router.get("/analytics/summary")
def get_analytics_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Aggregate analytics across all connected social accounts."""
    accounts = db.query(SocialAccount).filter(
        SocialAccount.user_id == current_user.id,
        SocialAccount.is_connected == True
    ).all()

    total_followers = 0
    total_views = 0
    total_impressions = 0
    total_likes = 0
    total_comments = 0
    total_shares = 0
    platform_breakdown = []

    for acc in accounts:
        latest_snap = (
            db.query(AnalyticsSnapshot)
            .filter(AnalyticsSnapshot.social_account_id == acc.id)
            .order_by(AnalyticsSnapshot.date.desc())
            .first()
        )
        if latest_snap:
            total_followers += latest_snap.followers
            total_views += latest_snap.views
            total_impressions += latest_snap.impressions
            total_likes += latest_snap.likes
            total_comments += latest_snap.comments
            total_shares += latest_snap.shares
            platform_breakdown.append({
                "platform": acc.platform,
                "account_name": acc.account_name,
                "followers": latest_snap.followers,
                "views": latest_snap.views,
                "engagement_rate": latest_snap.engagement_rate
            })

    total_interactions = total_likes + total_comments + total_shares
    avg_engagement = round((total_interactions / max(1, total_views)) * 100, 2) if total_views > 0 else 0.0

    return {
        "total_followers": total_followers,
        "total_views": total_views,
        "total_impressions": total_impressions,
        "total_interactions": total_interactions,
        "engagement_rate": avg_engagement,
        "connected_accounts_count": len(accounts),
        "platforms": platform_breakdown
    }

# Creator Watchlist
@router.get("/watchlist", response_model=List[CreatorWatchlistOut])
def list_watchlist(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return db.query(CreatorWatchlist).filter(CreatorWatchlist.user_id == current_user.id).all()

@router.post("/watchlist", response_model=CreatorWatchlistOut)
def add_watchlist(
    entry_in: CreatorWatchlistCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    entry = CreatorWatchlist(
        user_id=current_user.id,
        creator_name=entry_in.creator_name,
        handle=entry_in.handle,
        platform=entry_in.platform or "YouTube",
        profile_url=entry_in.profile_url,
        topic_niche=entry_in.topic_niche,
        personal_notes=entry_in.personal_notes,
        original_angles=entry_in.original_angles
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry

@router.delete("/watchlist/{entry_id}")
def delete_watchlist(
    entry_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    entry = db.query(CreatorWatchlist).filter(
        CreatorWatchlist.id == entry_id,
        CreatorWatchlist.user_id == current_user.id
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")

    db.delete(entry)
    db.commit()
    return {"message": "Watchlist entry deleted"}
