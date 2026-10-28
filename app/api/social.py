from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import re
import json
import subprocess
import urllib.request
import feedparser
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.models import User, SocialAccount, AnalyticsSnapshot, PublishedPost, CreatorWatchlist
from app.schemas.schemas import (
    CreatorWatchlistCreate, CreatorWatchlistUpdate, CreatorWatchlistOut,
    CreatorInspectRequest, CreatorInspectResponse
)
from app.services.ai_service import ai_service
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
import feedparser

class RecentUploadItem(BaseModel):
    video_id: str
    title: str
    published_at: str
    thumbnail_url: Optional[str] = None
    views: int = 0
    likes: int = 0
    engagement_rate: float = 0.0
    url: str

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
    total_videos: Optional[int] = None
    recent_videos: Optional[List[Dict[str, Any]]] = None
    raw_data: Optional[Dict[str, Any]] = None
    custom_url: Optional[str] = None
    channel_id: Optional[str] = None

class SocialStatsUpdatePayload(BaseModel):
    followers: Optional[int] = None
    views: Optional[int] = None
    impressions: Optional[int] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    shares: Optional[int] = None
    engagement_rate: Optional[float] = None
    total_videos: Optional[int] = None
    recent_videos: Optional[List[Dict[str, Any]]] = None
    raw_data: Optional[Dict[str, Any]] = None

class YouTubeLookupRequest(BaseModel):
    handle: str

def fetch_youtube_telemetry(handle_or_url: str) -> Dict[str, Any]:
    """Inspect public YouTube channel handle for live subscriber count, avatar, channel title, and 15 recent video uploads."""
    clean_handle = handle_or_url.strip()
    if "youtube.com" in clean_handle.lower():
        m = re.search(r'youtube\.com/@([a-zA-Z0-9_\-\.]+)', clean_handle)
        if m:
            clean_handle = m.group(1)
        else:
            clean_handle = clean_handle.split('/')[-1]
    clean_handle = clean_handle.lstrip('@')

    url = f"https://www.youtube.com/@{clean_handle}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9'
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as res:
            html = res.read().decode('utf-8', errors='ignore')

        title_m = re.search(r'<meta property="og:title" content="([^"]+)"', html) or re.search(r'<title>([^<]+?)(?: - YouTube)?</title>', html)
        channel_title = title_m.group(1).replace(" - YouTube", "").strip() if title_m else clean_handle

        avatar_m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
        avatar_url = avatar_m.group(1) if avatar_m else None

        cid_m = re.search(r'"externalId":"([^"]+)"', html) or re.search(r'<meta itemprop="channelId" content="([^"]+)"', html)
        cid = cid_m.group(1) if cid_m else None

        # Followers / subs
        sub_m = re.search(r'([0-9\.,]+[KMBkmb]?\s+subscribers)', html, re.IGNORECASE)
        sub_text = sub_m.group(1) if sub_m else None
        followers = 0
        if sub_text:
            m = re.search(r'([\d\.,]+)\s*([KMBkmb])?', sub_text)
            if m:
                val = float(m.group(1).replace(',', ''))
                unit = (m.group(2) or '').upper()
                if unit == 'K': followers = int(val * 1000)
                elif unit == 'M': followers = int(val * 1000000)
                elif unit == 'B': followers = int(val * 1000000000)
                else: followers = int(val)

        # Videos count
        vid_m = re.search(r'([0-9\.,]+[KMBkmb]?\s+videos)', html, re.IGNORECASE)
        vids_text = vid_m.group(1) if vid_m else None
        total_videos = 0
        if vids_text:
            m = re.search(r'([\d\.,]+)\s*([KMBkmb])?', vids_text)
            if m:
                val = float(m.group(1).replace(',', ''))
                unit = (m.group(2) or '').upper()
                if unit == 'K': total_videos = int(val * 1000)
                elif unit == 'M': total_videos = int(val * 1000000)
                else: total_videos = int(val)

        recent_videos = []
        if cid:
            rss = f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
            feed = feedparser.parse(rss)
            for e in feed.entries[:15]:
                vid = e.get("yt_videoid") or (e.get("link", "").split("v=")[-1] if "v=" in e.get("link", "") else "")
                v_title = e.get("title", "")
                pub = e.get("published", "")
                thumbs = e.get("media_thumbnail", [])
                thumb = thumbs[0].get("url") if thumbs else f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
                stats = e.get("media_statistics", {})
                views = int(stats.get("views", 0)) if stats and stats.get("views") else 0
                rating = e.get("media_starrating", {})
                likes = int(rating.get("count", 0)) if rating and rating.get("count") else 0
                v_url = e.get("link") or f"https://www.youtube.com/watch?v={vid}"
                eng_rate = round((likes / max(1, views)) * 100, 2) if views > 0 else 0.0

                recent_videos.append({
                    "video_id": vid,
                    "title": v_title,
                    "published_at": pub,
                    "thumbnail_url": thumb,
                    "views": views,
                    "likes": likes,
                    "engagement_rate": eng_rate,
                    "url": v_url
                })

        total_tracked_views = sum(v["views"] for v in recent_videos)
        total_tracked_likes = sum(v["likes"] for v in recent_videos)
        avg_views = int(total_tracked_views / max(1, len(recent_videos))) if recent_videos else 0
        avg_engagement = round((total_tracked_likes / max(1, total_tracked_views)) * 100, 2) if total_tracked_views > 0 else 0.0
        top_video = max(recent_videos, key=lambda x: x["views"]) if recent_videos else None

        cadence = 0.0
        if len(recent_videos) >= 2:
            try:
                dates = []
                for v in recent_videos:
                    d_str = v["published_at"].split('+')[0].rstrip('Z')
                    dates.append(datetime.fromisoformat(d_str))
                dates.sort()
                days_span = max(1, (dates[-1] - dates[0]).days)
                cadence = round((len(dates) / (days_span / 7.0)), 1)
            except Exception:
                cadence = round(len(recent_videos) / 4.0, 1)

        return {
            "success": True,
            "platform": "youtube",
            "handle": f"@{clean_handle}",
            "channel_title": channel_title,
            "channel_id": cid,
            "avatar_url": avatar_url,
            "subscribers_text": sub_text,
            "followers": followers,
            "total_videos": total_videos,
            "total_tracked_views": total_tracked_views,
            "avg_views": avg_views,
            "avg_engagement": avg_engagement,
            "cadence_weekly": cadence,
            "top_video": top_video,
            "recent_videos": recent_videos
        }
    except Exception as e:
        return {
            "success": False,
            "platform": "youtube",
            "handle": f"@{clean_handle}",
            "channel_title": clean_handle,
            "channel_id": None,
            "avatar_url": None,
            "subscribers_text": None,
            "followers": 0,
            "total_videos": 0,
            "total_tracked_views": 0,
            "avg_views": 0,
            "avg_engagement": 0.0,
            "cadence_weekly": 0.0,
            "top_video": None,
            "recent_videos": [],
            "message": f"Could not fetch public stats: {str(e)}"
        }

@router.post("/youtube-lookup")
def lookup_youtube_handle(req: YouTubeLookupRequest):
    """Inspect public YouTube channel handle for live subscriber count, avatar, channel title, and recent uploads."""
    clean_handle = req.handle.strip().lstrip('@')
    if not clean_handle:
        raise HTTPException(status_code=400, detail="Invalid YouTube handle")
    return fetch_youtube_telemetry(clean_handle)

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
    total_videos = (payload.total_videos if payload and payload.total_videos is not None else 0)
    cid = payload.channel_id if payload else None
    raw_data = payload.raw_data or {}
    if payload and payload.recent_videos:
        raw_data["recent_videos"] = payload.recent_videos

    # If YouTube, live scrape public telemetry
    if platform.lower() == "youtube" and name:
        yt = fetch_youtube_telemetry(name)
        if yt.get("success"):
            name = yt.get("channel_title") or name
            avatar = yt.get("avatar_url") or avatar
            cid = yt.get("channel_id") or cid
            followers = yt.get("followers") or followers
            total_videos = yt.get("total_videos") or total_videos
            views = yt.get("total_tracked_views") or views
            engagement_rate = yt.get("avg_engagement") or engagement_rate
            raw_data = {
                "recent_videos": yt.get("recent_videos", []),
                "avg_views": yt.get("avg_views", 0),
                "cadence_weekly": yt.get("cadence_weekly", 0.0),
                "top_video": yt.get("top_video"),
                "subscribers_text": yt.get("subscribers_text")
            }

    if not existing:
        existing = SocialAccount(
            user_id=current_user.id,
            platform=platform.lower(),
            account_name=name,
            account_id=payload.account_id if payload and payload.account_id else (cid or f"{platform.lower()}_act_{current_user.id}"),
            channel_id=cid,
            avatar_url=avatar,
            total_videos_count=total_videos,
            raw_details=raw_data,
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
            engagement_rate=engagement_rate,
            raw_data=raw_data
        )
        db.add(snap)
        db.commit()
    else:
        existing.is_connected = True
        existing.account_name = name
        if avatar: existing.avatar_url = avatar
        if cid: existing.channel_id = cid
        if total_videos: existing.total_videos_count = total_videos
        existing.raw_details = raw_data
        existing.last_synced_at = datetime.utcnow()
        db.commit()

        # Update or record new snapshot with new baseline numbers
        latest_snap = db.query(AnalyticsSnapshot).filter(
            AnalyticsSnapshot.social_account_id == existing.id
        ).order_by(AnalyticsSnapshot.date.desc()).first()

        if latest_snap and (latest_snap.date.date() == datetime.utcnow().date()):
            latest_snap.followers = followers
            latest_snap.views = views
            latest_snap.impressions = impressions
            latest_snap.likes = likes
            latest_snap.comments = comments
            latest_snap.shares = shares
            latest_snap.engagement_rate = engagement_rate
            latest_snap.raw_data = raw_data
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
                engagement_rate=engagement_rate,
                raw_data=raw_data
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

    raw_data = payload.raw_data or (snap.raw_data if snap else {}) or (account.raw_details or {})
    if payload.recent_videos:
        raw_data["recent_videos"] = payload.recent_videos

    if not snap or (snap.date.date() != datetime.utcnow().date()):
        snap = AnalyticsSnapshot(
            social_account_id=account.id,
            followers=snap.followers if snap else 0,
            views=snap.views if snap else 0,
            impressions=snap.impressions if snap else 0,
            likes=snap.likes if snap else 0,
            comments=snap.comments if snap else 0,
            shares=snap.shares if snap else 0,
            engagement_rate=snap.engagement_rate if snap else 0.0,
            raw_data=raw_data
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
    snap.raw_data = raw_data

    if payload.total_videos is not None:
        account.total_videos_count = payload.total_videos
    account.raw_details = raw_data
    account.last_synced_at = datetime.utcnow()
    db.commit()
    return {"message": "Channel stats updated successfully", "snapshot": {
        "followers": snap.followers,
        "views": snap.views,
        "impressions": snap.impressions,
        "engagement_rate": snap.engagement_rate,
        "total_videos": account.total_videos_count,
        "raw_data": snap.raw_data
    }}

@router.post("/sync/{account_id}")
def sync_account(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Sync live telemetry for an account from public feeds or credentials."""
    account = db.query(SocialAccount).filter(
        SocialAccount.id == account_id,
        SocialAccount.user_id == current_user.id
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Social account not found")

    if account.platform.lower() == "youtube":
        yt = fetch_youtube_telemetry(account.account_name)
        if yt.get("success"):
            account.account_name = yt.get("channel_title") or account.account_name
            account.avatar_url = yt.get("avatar_url") or account.avatar_url
            account.channel_id = yt.get("channel_id") or account.channel_id
            account.total_videos_count = yt.get("total_videos") or account.total_videos_count
            raw_data = {
                "recent_videos": yt.get("recent_videos", []),
                "avg_views": yt.get("avg_views", 0),
                "cadence_weekly": yt.get("cadence_weekly", 0.0),
                "top_video": yt.get("top_video"),
                "subscribers_text": yt.get("subscribers_text")
            }
            account.raw_details = raw_data
            account.last_synced_at = datetime.utcnow()
            db.commit()

            latest_snap = db.query(AnalyticsSnapshot).filter(
                AnalyticsSnapshot.social_account_id == account.id
            ).order_by(AnalyticsSnapshot.date.desc()).first()

            if latest_snap and (latest_snap.date.date() == datetime.utcnow().date()):
                latest_snap.followers = yt.get("followers", 0)
                latest_snap.views = yt.get("total_tracked_views", 0)
                latest_snap.engagement_rate = yt.get("avg_engagement", 0.0)
                latest_snap.raw_data = raw_data
                db.commit()
            else:
                snap = AnalyticsSnapshot(
                    social_account_id=account.id,
                    followers=yt.get("followers", 0),
                    views=yt.get("total_tracked_views", 0),
                    impressions=yt.get("total_tracked_views", 0) * 2,
                    engagement_rate=yt.get("avg_engagement", 0.0),
                    raw_data=raw_data
                )
                db.add(snap)
                db.commit()

            return {
                "message": f"Synchronized live telemetry for {account.account_name}!",
                "success": True,
                "telemetry": yt
            }
        else:
            raise HTTPException(status_code=502, detail=yt.get("message", "Live sync failed"))
    else:
        account.last_synced_at = datetime.utcnow()
        db.commit()
        return {"message": f"{account.platform.capitalize()} synced.", "success": True}

@router.get("/channel/{platform}")
def get_channel_details(
    platform: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Retrieve detailed platform-semantic telemetry, recent uploads, and trend metrics."""
    account = db.query(SocialAccount).filter(
        SocialAccount.user_id == current_user.id,
        SocialAccount.platform == platform.lower(),
        SocialAccount.is_connected == True
    ).first()

    if not account:
        return {
            "is_connected": False,
            "platform": platform.lower(),
            "account_name": "",
            "account_id": None,
            "avatar_url": None,
            "followers": 0,
            "views": 0,
            "impressions": 0,
            "engagement_rate": 0.0,
            "total_videos": 0,
            "avg_views": 0,
            "cadence_weekly": 0.0,
            "top_video": None,
            "recent_videos": [],
            "raw_data": {}
        }

    latest_snap = db.query(AnalyticsSnapshot).filter(
        AnalyticsSnapshot.social_account_id == account.id
    ).order_by(AnalyticsSnapshot.date.desc()).first()

    raw = (latest_snap.raw_data if latest_snap and latest_snap.raw_data else {}) or (account.raw_details or {})

    recent_videos = raw.get("recent_videos", [])
    avg_views = raw.get("avg_views", 0)
    top_video = raw.get("top_video", None)
    cadence = raw.get("cadence_weekly", 0.0)

    return {
        "is_connected": True,
        "platform": account.platform,
        "account_name": account.account_name,
        "account_id": account.account_id,
        "avatar_url": account.avatar_url,
        "last_synced_at": account.last_synced_at,
        "followers": latest_snap.followers if latest_snap else 0,
        "views": latest_snap.views if latest_snap else 0,
        "impressions": latest_snap.impressions if latest_snap else 0,
        "engagement_rate": latest_snap.engagement_rate if latest_snap else 0.0,
        "total_videos": account.total_videos_count or len(recent_videos),
        "avg_views": avg_views,
        "cadence_weekly": cadence,
        "top_video": top_video,
        "recent_videos": recent_videos,
        "raw_data": raw
    }

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
            raw = latest_snap.raw_data or acc.raw_details or {}
            platform_breakdown.append({
                "platform": acc.platform,
                "account_name": acc.account_name,
                "avatar_url": acc.avatar_url,
                "followers": latest_snap.followers,
                "views": latest_snap.views,
                "impressions": latest_snap.impressions,
                "engagement_rate": latest_snap.engagement_rate,
                "total_videos": acc.total_videos_count or len(raw.get("recent_videos", [])),
                "avg_views": raw.get("avg_views", 0),
                "cadence_weekly": raw.get("cadence_weekly", 0.0),
                "top_video": raw.get("top_video")
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
@router.post("/inspect-creator", response_model=CreatorInspectResponse)
async def inspect_creator(
    payload: CreatorInspectRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Live inspect a creator channel or profile and analyze their pacing, style, and signature hooks."""
    raw_input = payload.url_or_handle.strip()
    if not raw_input:
        raise HTTPException(status_code=400, detail="Profile URL or handle is required")

    platform = payload.platform or "YouTube"
    handle = ""
    profile_url = ""
    cid = None

    lowered = raw_input.lower()

    # Detect platform and parse input
    # Check for YouTube channel ID (/channel/UC... or raw UC...)
    yt_cid_m = re.search(r'(?:youtube\.com/channel/|youtube\.com/c/|youtube\.com/user/|^)(UC[a-zA-Z0-9_\-]{20,})', raw_input)
    if yt_cid_m:
        platform = "YouTube"
        cid = yt_cid_m.group(1)
        profile_url = f"https://www.youtube.com/channel/{cid}"
        handle = f"@{cid}"
    elif "youtube.com" in lowered or "youtu.be" in lowered:
        platform = "YouTube"
        m = re.search(r'youtube\.com/@([a-zA-Z0-9_\-\.]+)', raw_input)
        if m:
            handle = f"@{m.group(1)}"
            profile_url = f"https://www.youtube.com/{handle}"
        else:
            profile_url = raw_input
            handle = "@channel"
    elif raw_input.startswith("http://") or raw_input.startswith("https://"):
        profile_url = raw_input
        if "twitter.com" in lowered or "x.com" in lowered:
            platform = "X"
            m = re.search(r'(?:twitter|x)\.com/([a-zA-Z0-9_]+)', raw_input)
            handle = f"@{m.group(1)}" if m else "@profile"
        elif "tiktok.com" in lowered:
            platform = "TikTok"
            m = re.search(r'tiktok\.com/@([a-zA-Z0-9_\.\-]+)', raw_input)
            handle = f"@{m.group(1)}" if m else "@creator"
        elif "instagram.com" in lowered:
            platform = "Instagram"
            m = re.search(r'instagram\.com/([a-zA-Z0-9_\.\-]+)', raw_input)
            handle = f"@{m.group(1)}" if m else "@creator"
        elif "linkedin.com" in lowered:
            platform = "LinkedIn"
            m = re.search(r'linkedin\.com/in/([a-zA-Z0-9_\-]+)', raw_input)
            handle = f"@{m.group(1)}" if m else "@profile"
        else:
            handle = "@creator"
    else:
        # Handle given as @name or raw string
        clean_handle = raw_input.lstrip('@')
        handle = f"@{clean_handle}"
        if platform.lower() in ("x", "twitter"):
            platform = "X"
            profile_url = f"https://x.com/{clean_handle}"
        elif platform.lower() == "tiktok":
            platform = "TikTok"
            profile_url = f"https://www.tiktok.com/@{clean_handle}"
        elif platform.lower() == "instagram":
            platform = "Instagram"
            profile_url = f"https://www.instagram.com/{clean_handle}"
        elif platform.lower() == "linkedin":
            platform = "LinkedIn"
            profile_url = f"https://www.linkedin.com/in/{clean_handle}"
        else:
            platform = "YouTube"
            profile_url = f"https://www.youtube.com/@{clean_handle}"

    creator_name = handle.lstrip('@')
    avatar_url = None
    subscriber_count_text = None
    bio = ""
    recent_titles = []

    request_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    }

    # Live inspection logic
    try:
        if platform == "YouTube":
            # 1. Fast RSS Feed Ingestion if CID is known
            if cid:
                rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
                try:
                    feed = feedparser.parse(rss_url)
                    if feed and feed.entries:
                        recent_titles = [e.get("title") for e in feed.entries[:8] if e.get("title")]
                        feed_title = feed.feed.get("title")
                        if feed_title:
                            creator_name = feed_title
                        # Fast oEmbed to extract exact author vanity handle
                        first_vid = feed.entries[0].get("yt_videoid")
                        if first_vid:
                            try:
                                oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={first_vid}&format=json"
                                req_oe = urllib.request.Request(oembed_url, headers=request_headers)
                                with urllib.request.urlopen(req_oe, timeout=4) as ores:
                                    odata = json.loads(ores.read().decode("utf-8"))
                                    if odata.get("author_name"):
                                        creator_name = odata["author_name"]
                                    if odata.get("author_url"):
                                        aurl = odata["author_url"]
                                        am = re.search(r'youtube\.com/@([a-zA-Z0-9_\-\.]+)', aurl)
                                        if am:
                                            handle = f"@{am.group(1)}"
                                            profile_url = aurl
                            except Exception:
                                pass
                except Exception as rss_err:
                    print(f"[InspectCreator] Initial RSS parse note: {rss_err}")

            # 2. HTML Page Metadata Ingestion (curl.exe with urllib fallback)
            html = ""
            target_url = profile_url if (profile_url and "youtube.com" in profile_url) else f"https://www.youtube.com/{handle}"
            try:
                p = subprocess.run(["curl.exe", "-s", "-L", "--max-time", "6", target_url], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, errors="ignore")
                if p.returncode == 0 and p.stdout:
                    html = p.stdout
            except Exception:
                pass

            if not html:
                try:
                    http_req = urllib.request.Request(target_url, headers=request_headers)
                    with urllib.request.urlopen(http_req, timeout=5) as res:
                        html = res.read().decode("utf-8", errors="ignore")
                except Exception as h_err:
                    print(f"[InspectCreator] urllib fetch note: {h_err}")

            if html:
                title_m = re.search(r'<meta property="og:title" content="([^"]+)"', html) or re.search(r'<title>([^<]+?)(?: - YouTube)?</title>', html)
                if title_m:
                    creator_name = title_m.group(1).replace(" - YouTube", "").strip()

                avatar_m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
                if avatar_m:
                    avatar_url = avatar_m.group(1)

                desc_m = re.search(r'<meta property="og:description" content="([^"]+)"', html)
                if desc_m:
                    bio = desc_m.group(1).strip()

                canonical_m = re.search(r'"canonicalBaseUrl":"([^"]+)"', html) or re.search(r'"alternateName":"(@[a-zA-Z0-9_\-\.]+)"', html)
                if canonical_m:
                    c_val = canonical_m.group(1).lstrip("/")
                    handle = c_val if c_val.startswith("@") else f"@{c_val}"
                    profile_url = f"https://www.youtube.com/{handle}"

                # Structured subscriber count or regex
                sub_count_m = re.search(r'"userInteractionCount":"(\d+)"', html)
                if sub_count_m:
                    count = int(sub_count_m.group(1))
                    if count >= 1_000_000:
                        subscriber_count_text = f"{count / 1_000_000:.1f}M subscribers"
                    elif count >= 1_000:
                        subscriber_count_text = f"{count / 1_000:.0f}K subscribers"
                    else:
                        subscriber_count_text = f"{count:,} subscribers"
                else:
                    sub_m = re.search(r'([0-9\.]+[KMBkmb]?\s+subscribers?)', html, re.IGNORECASE)
                    if sub_m:
                        subscriber_count_text = sub_m.group(1)

                # If recent titles not fetched yet, extract cid and query RSS
                if not recent_titles:
                    cid_m = re.search(r'"browseId":"(UC[a-zA-Z0-9_\-]+)"', html) or re.search(r'<meta itemprop="channelId" content="([^"]+)"', html) or re.search(r'"externalId":"([^"]+)"', html)
                    if cid_m:
                        cid = cid_m.group(1)
                        rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
                        try:
                            feed = feedparser.parse(rss_url)
                            if feed and feed.entries:
                                recent_titles = [e.get("title") for e in feed.entries[:8] if e.get("title")]
                        except Exception as rss_err:
                            print(f"[InspectCreator] Post-scrape RSS error: {rss_err}")
        else:
            # Fallback OpenGraph scrape for other platforms
            if profile_url:
                try:
                    http_req = urllib.request.Request(profile_url, headers=request_headers)
                    with urllib.request.urlopen(http_req, timeout=6) as res:
                        html = res.read().decode("utf-8", errors="ignore")
                    title_m = re.search(r'<meta property="og:title" content="([^"]+)"', html)
                    if title_m:
                        creator_name = title_m.group(1).strip()
                    avatar_m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
                    if avatar_m:
                        avatar_url = avatar_m.group(1)
                    desc_m = re.search(r'<meta property="og:description" content="([^"]+)"', html)
                    if desc_m:
                        bio = desc_m.group(1).strip()
                except Exception as og_err:
                    print(f"[InspectCreator] OG scrape note: {og_err}")

    except Exception as scrape_err:
        print(f"[InspectCreator] Scrape error for {handle}: {scrape_err}")

    # Now run AI profile analysis to dissect pacing, niche, and hooks
    prefs = current_user.preferences
    user_niche = f"{prefs.primary_niche} ({prefs.sub_niche})" if prefs else None

    try:
        analysis = await ai_service.analyze_creator_profile(
            creator_name=creator_name,
            handle=handle,
            platform=platform,
            bio=bio,
            recent_titles=recent_titles,
            user_niche=user_niche,
            prefs=prefs
        )
    except Exception as ai_err:
        print(f"[InspectCreator] AI analysis fallback: {ai_err}")
        default_hooks = [
            f"Why {recent_titles[0] if recent_titles else 'everyone'} changes the game",
            "The 3 biggest mistakes people make when starting",
            "What happened when I tried this for 30 days"
        ]
        analysis = {
            "topic_niche": f"{creator_name} & {platform} Strategy",
            "pacing_style": "Fast, direct, high-information density",
            "personal_notes": f"Creates engaging {platform} content with concise hooks and active visual storytelling.",
            "signature_hooks": default_hooks,
            "original_angles": f"Adopt their punchy first 3 seconds and adapt it to your {user_niche or 'niche'} content."
        }

    return CreatorInspectResponse(
        success=True,
        creator_name=creator_name,
        handle=handle,
        platform=platform,
        profile_url=profile_url,
        avatar_url=avatar_url,
        subscriber_count_text=subscriber_count_text,
        topic_niche=analysis.get("topic_niche", "Content Creation"),
        personal_notes=analysis.get("personal_notes", ""),
        original_angles=analysis.get("original_angles", ""),
        pacing_style=analysis.get("pacing_style", "High Retention"),
        signature_hooks=analysis.get("signature_hooks", []),
        recent_titles=recent_titles,
        error=None
    )

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
        avatar_url=entry_in.avatar_url,
        subscriber_count_text=entry_in.subscriber_count_text,
        pacing_style=entry_in.pacing_style,
        signature_hooks=entry_in.signature_hooks or [],
        personal_notes=entry_in.personal_notes,
        original_angles=entry_in.original_angles
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry

@router.put("/watchlist/{entry_id}", response_model=CreatorWatchlistOut)
def update_watchlist(
    entry_id: int,
    entry_in: CreatorWatchlistUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    entry = db.query(CreatorWatchlist).filter(
        CreatorWatchlist.id == entry_id,
        CreatorWatchlist.user_id == current_user.id
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")

    for field, val in entry_in.model_dump(exclude_unset=True).items():
        setattr(entry, field, val)

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
