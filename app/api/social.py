from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import re
import json
import subprocess
import urllib.request
import feedparser
import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.config import settings
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

class PlatformLookupRequest(BaseModel):
    handle: str

def fetch_x_public_fallback(clean_handle: str, fallback_msg: Optional[str] = None) -> Dict[str, Any]:
    """Attempt public scrape for X profile when bearer token is missing or unauthorized."""
    url = f"https://x.com/{clean_handle}"
    avatar_url = None
    display_name = clean_handle
    followers = 0
    try:
        p = subprocess.run(
            ["curl.exe", "-s", "-L", "--max-time", "10", url],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            errors="ignore"
        )
        if p.returncode == 0 and p.stdout:
            html = p.stdout
            title_m = re.search(r'<meta property="og:title" content="([^"]+)"', html)
            if title_m:
                display_name = title_m.group(1).replace(" on X", "").replace(" on Twitter", "").strip()
            avatar_m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
            if avatar_m:
                avatar_url = avatar_m.group(1)
            desc_m = re.search(r'<meta property="og:description" content="([^"]+)"', html)
            if desc_m:
                sub_m = re.search(r'([\d\.,]+[KMBkmb]?)\s+Followers', desc_m.group(1), re.IGNORECASE)
                if sub_m:
                    num_str = sub_m.group(1).replace(',', '')
                    if num_str[-1].upper() == 'K': followers = int(float(num_str[:-1]) * 1000)
                    elif num_str[-1].upper() == 'M': followers = int(float(num_str[:-1]) * 1000000)
                    else: followers = int(float(num_str))
    except Exception:
        pass

    msg = fallback_msg or "Automated X lookup requires X_BEARER_TOKEN or APIFY_API_KEY in .env. Enter metrics manually below."
    return {
        "success": bool(avatar_url or followers > 0),
        "platform": "x",
        "handle": f"@{clean_handle}",
        "channel_title": display_name,
        "channel_id": clean_handle,
        "avatar_url": avatar_url,
        "followers": followers,
        "total_videos": 0,
        "total_tracked_views": 0,
        "avg_views": 0,
        "avg_engagement": 3.0,
        "cadence_weekly": 0.0,
        "top_video": None,
        "recent_videos": [],
        "message": msg if not (avatar_url or followers > 0) else None
    }

def fetch_apify_x(handle_or_url: str) -> Dict[str, Any]:
    """Inspect X / Twitter profile and recent tweets using Apify actor."""
    clean_handle = handle_or_url.strip()
    if "twitter.com/" in clean_handle.lower() or "x.com/" in clean_handle.lower():
        clean_handle = clean_handle.split('/')[-1].split('?')[0]
    clean_handle = clean_handle.lstrip('@')

    token = (settings.APIFY_API_KEY or "").strip()
    if not token:
        return {
            "success": False,
            "platform": "x",
            "handle": f"@{clean_handle}",
            "message": "Apify token not set. Add APIFY_API_KEY in kre8-backend/.env or enter metrics manually."
        }

    # 1. Fetch user profile via apidojo/twitter-user-scraper
    actor_endpoint = f"https://api.apify.com/v2/acts/apidojo~twitter-user-scraper/run-sync-get-dataset-items?token={token}"
    run_input = {"twitterHandles": [clean_handle]}

    try:
        with httpx.Client(timeout=35.0) as client:
            res = client.post(actor_endpoint, json=run_input)
            items = res.json() if res.status_code in (200, 201) else []

            # If primary actor empty, try query via tweet-scraper
            if not items or not isinstance(items, list):
                alt_endpoint = f"https://api.apify.com/v2/acts/apidojo~tweet-scraper/run-sync-get-dataset-items?token={token}"
                alt_res = client.post(alt_endpoint, json={"searchTerms": [f"from:{clean_handle}"], "maxTweets": 10})
                if alt_res.status_code in (200, 201):
                    items = alt_res.json()

            if not items or not isinstance(items, list):
                return fetch_x_public_fallback(clean_handle, fallback_msg="No X profile data found for this handle via Apify.")

            first = items[0]
            author = first.get("author", {}) or (first if ("followers" in first or "followersCount" in first) else {})
            display_name = author.get("name") or first.get("name") or clean_handle
            avatar = author.get("profilePicture") or author.get("avatar") or first.get("profilePicture")
            followers = int(author.get("followers") or author.get("followersCount") or first.get("followers") or 0)
            following = int(author.get("following") or author.get("followingCount") or first.get("following") or 0)
            tweet_count = int(author.get("statusesCount") or author.get("tweetsCount") or first.get("statusesCount") or 0)

            recent_posts = []
            total_impressions = 0
            total_likes = 0
            for item in items[:10]:
                tw_id = str(item.get("id") or item.get("tweetId") or "")
                text = item.get("text") or item.get("full_text") or ""
                if not text and not tw_id:
                    continue
                likes = int(item.get("likeCount") or item.get("likes") or 0)
                retweets = int(item.get("retweetCount") or item.get("retweets") or 0)
                replies = int(item.get("replyCount") or item.get("replies") or 0)
                views = int(item.get("viewCount") or item.get("views") or (likes * 15))
                total_impressions += views
                total_likes += likes
                created_at = item.get("createdAt") or item.get("created_at") or ""
                recent_posts.append({
                    "video_id": tw_id,
                    "title": text[:70] + ("..." if len(text) > 70 else ""),
                    "published_at": str(created_at),
                    "thumbnail_url": avatar,
                    "views": views,
                    "likes": likes,
                    "retweets": retweets,
                    "replies": replies,
                    "engagement_rate": round(((likes + retweets + replies) / max(1, views)) * 100, 2) if views > 0 else 0.0,
                    "url": item.get("url") or f"https://x.com/{clean_handle}/status/{tw_id}"
                })

            avg_views = int(total_impressions / max(1, len(recent_posts))) if recent_posts else 0
            avg_eng = round((total_likes / max(1, total_impressions)) * 100, 2) if total_impressions > 0 else 3.0

            return {
                "success": True,
                "platform": "x",
                "handle": f"@{clean_handle}",
                "channel_title": display_name,
                "channel_id": str(author.get("id", clean_handle)),
                "avatar_url": avatar,
                "followers": followers,
                "total_videos": tweet_count or len(recent_posts),
                "total_tracked_views": total_impressions,
                "avg_views": avg_views,
                "avg_engagement": avg_eng,
                "cadence_weekly": round(len(recent_posts) / 2.0, 1) if recent_posts else 0.0,
                "top_video": max(recent_posts, key=lambda x: x["views"]) if recent_posts else None,
                "recent_videos": recent_posts,
                "raw_metrics": {
                    "following": following,
                    "posts_count": tweet_count or len(recent_posts),
                    "total_likes": total_likes
                }
            }
    except Exception as e:
        return fetch_x_public_fallback(clean_handle, fallback_msg=f"Apify X lookup note: {str(e)}")

def fetch_x_telemetry(handle_or_url: str) -> Dict[str, Any]:
    """Inspect X / Twitter profile using X API v2 Bearer Token or Apify actor, with public fallback."""
    clean_handle = handle_or_url.strip()
    if "twitter.com/" in clean_handle.lower() or "x.com/" in clean_handle.lower():
        clean_handle = clean_handle.split('/')[-1].split('?')[0]
    clean_handle = clean_handle.lstrip('@')

    if not clean_handle:
        return {"success": False, "platform": "x", "handle": "", "message": "Invalid X handle"}

    token = (settings.X_BEARER_TOKEN or "").strip()
    apify_token = (settings.APIFY_API_KEY or "").strip()

    # If official Bearer token is not set, but Apify is available, use Apify!
    if not token and apify_token:
        return fetch_apify_x(clean_handle)

    if not token:
        return fetch_x_public_fallback(clean_handle)

    headers = {"Authorization": f"Bearer {token}"}
    try:
        with httpx.Client(timeout=12.0) as client:
            user_url = f"https://api.twitter.com/2/users/by/username/{clean_handle}?user.fields=public_metrics,profile_image_url,description,verified"
            u_res = client.get(user_url, headers=headers)
            if u_res.status_code != 200:
                err_data = u_res.json() if "application/json" in u_res.headers.get("content-type", "") else {}
                err_msg = err_data.get("detail") or err_data.get("title") or f"X API error {u_res.status_code}"
                return fetch_x_public_fallback(clean_handle, fallback_msg=f"X API: {err_msg}")

            u_json = u_res.json()
            data = u_json.get("data")
            if not data:
                return fetch_x_public_fallback(clean_handle, fallback_msg="User not found on X")

            user_id = data.get("id")
            display_name = data.get("name", clean_handle)
            avatar_url = data.get("profile_image_url")
            metrics = data.get("public_metrics", {})
            followers = int(metrics.get("followers_count", 0))
            following = int(metrics.get("following_count", 0))
            tweet_count = int(metrics.get("tweet_count", 0))

            tweets_url = f"https://api.twitter.com/2/users/{user_id}/tweets?tweet.fields=public_metrics,created_at&max_results=10"
            t_res = client.get(tweets_url, headers=headers)
            recent_posts = []
            total_likes = 0
            total_impressions = 0
            if t_res.status_code == 200:
                t_json = t_res.json()
                for tw in t_json.get("data", []):
                    pm = tw.get("public_metrics", {})
                    l_count = int(pm.get("like_count", 0))
                    rt_count = int(pm.get("retweet_count", 0))
                    rep_count = int(pm.get("reply_count", 0))
                    imp_count = int(pm.get("impression_count", 0))
                    total_likes += l_count
                    total_impressions += imp_count
                    recent_posts.append({
                        "video_id": tw.get("id", ""),
                        "title": (tw.get("text") or "")[:80] + ("..." if len(tw.get("text", "")) > 80 else ""),
                        "published_at": tw.get("created_at", ""),
                        "thumbnail_url": avatar_url,
                        "views": imp_count,
                        "likes": l_count,
                        "retweets": rt_count,
                        "replies": rep_count,
                        "engagement_rate": round(((l_count + rt_count + rep_count) / max(1, imp_count)) * 100, 2) if imp_count > 0 else 0.0,
                        "url": f"https://x.com/{clean_handle}/status/{tw.get('id')}"
                    })

            avg_eng = round((total_likes / max(1, total_impressions)) * 100, 2) if total_impressions > 0 else 2.5
            return {
                "success": True,
                "platform": "x",
                "handle": f"@{clean_handle}",
                "channel_title": display_name,
                "channel_id": user_id,
                "avatar_url": avatar_url,
                "followers": followers,
                "total_videos": tweet_count,
                "total_tracked_views": total_impressions,
                "avg_views": int(total_impressions / max(1, len(recent_posts))) if recent_posts else 0,
                "avg_engagement": avg_eng,
                "cadence_weekly": round(len(recent_posts) / 2.0, 1) if recent_posts else 0.0,
                "top_video": max(recent_posts, key=lambda x: x["views"]) if recent_posts else None,
                "recent_videos": recent_posts,
                "raw_metrics": {
                    "following": following,
                    "posts_count": tweet_count,
                    "total_likes": total_likes
                }
            }
    except Exception as e:
        return fetch_x_public_fallback(clean_handle, fallback_msg=str(e))

def fetch_apify_tiktok(handle_or_url: str) -> Dict[str, Any]:
    """Inspect TikTok profile using Apify Free Scraper Actor."""
    clean_handle = handle_or_url.strip()
    if "tiktok.com/@" in clean_handle.lower():
        clean_handle = clean_handle.split('@')[-1].split('/')[0].split('?')[0]
    clean_handle = clean_handle.lstrip('@')

    token = (settings.APIFY_API_KEY or "").strip()
    if not token:
        return {
            "success": False,
            "platform": "tiktok",
            "handle": f"@{clean_handle}",
            "message": "Apify token not set. Add APIFY_API_KEY to kre8-backend/.env (free $5/mo credit at apify.com) or enter metrics manually below."
        }

    actor_endpoint = f"https://api.apify.com/v2/acts/clockworks~free-tiktok-scraper/run-sync-get-dataset-items?token={token}"
    run_input = {
        "profiles": [clean_handle],
        "resultsPerPage": 10,
        "shouldDownloadVideos": False
    }

    try:
        with httpx.Client(timeout=35.0) as client:
            res = client.post(actor_endpoint, json=run_input)
            if res.status_code not in (200, 201):
                alt_endpoint = f"https://api.apify.com/v2/acts/apidojo~tiktok-scraper/run-sync-get-dataset-items?token={token}"
                res = client.post(alt_endpoint, json={"usernames": [clean_handle], "maxItems": 10})

            if res.status_code not in (200, 201):
                return {
                    "success": False,
                    "platform": "tiktok",
                    "handle": f"@{clean_handle}",
                    "message": f"Apify error {res.status_code}: Please check your APIFY_API_KEY or handle."
                }

            items = res.json()
            if not items or not isinstance(items, list):
                return {
                    "success": False,
                    "platform": "tiktok",
                    "handle": f"@{clean_handle}",
                    "message": "No TikTok profile data found for this handle."
                }

            first = items[0]
            author = first.get("authorMeta", {}) or first.get("author", {}) or first

            display_name = author.get("nickName") or author.get("name") or author.get("nickname") or clean_handle
            avatar = author.get("avatar") or author.get("avatarThumb") or author.get("avatarMedium")
            followers = int(author.get("fans") or author.get("followers") or author.get("followerCount") or 0)
            total_likes = int(author.get("heart") or author.get("heartCount") or author.get("likes") or 0)
            video_count = int(author.get("video") or author.get("videoCount") or len(items))

            recent_vids = []
            total_views = 0
            for item in items[:10]:
                vid_id = str(item.get("id") or item.get("videoId") or "")
                desc = item.get("text") or item.get("desc") or "TikTok Video"
                play_count = int(item.get("playCount") or item.get("stats", {}).get("playCount") or 0)
                digg_count = int(item.get("diggCount") or item.get("stats", {}).get("diggCount") or 0)
                pub_time = item.get("createTimeISO") or item.get("createTime") or ""
                web_url = item.get("webVideoUrl") or f"https://www.tiktok.com/@{clean_handle}/video/{vid_id}"

                total_views += play_count
                recent_vids.append({
                    "video_id": vid_id,
                    "title": desc[:70] + ("..." if len(desc) > 70 else ""),
                    "published_at": str(pub_time),
                    "thumbnail_url": item.get("video", {}).get("cover") or avatar,
                    "views": play_count,
                    "likes": digg_count,
                    "engagement_rate": round((digg_count / max(1, play_count)) * 100, 2) if play_count > 0 else 0.0,
                    "url": web_url
                })

            avg_views = int(total_views / max(1, len(recent_vids))) if recent_vids else 0
            avg_eng = round((total_likes / max(1, total_views)) * 100, 2) if total_views > 0 else 4.0

            return {
                "success": True,
                "platform": "tiktok",
                "handle": f"@{clean_handle}",
                "channel_title": display_name,
                "channel_id": str(author.get("id", clean_handle)),
                "avatar_url": avatar,
                "followers": followers,
                "total_videos": video_count,
                "total_tracked_views": total_views,
                "avg_views": avg_views,
                "avg_engagement": avg_eng,
                "cadence_weekly": round(len(recent_vids) / 2.0, 1) if recent_vids else 0.0,
                "top_video": max(recent_vids, key=lambda x: x["views"]) if recent_vids else None,
                "recent_videos": recent_vids,
                "raw_metrics": {
                    "total_likes": total_likes,
                    "posts_count": video_count
                }
            }
    except Exception as e:
        return {
            "success": False,
            "platform": "tiktok",
            "handle": f"@{clean_handle}",
            "message": f"Apify lookup failed: {str(e)}"
        }

def fetch_apify_instagram(handle_or_url: str) -> Dict[str, Any]:
    """Inspect Instagram profile using Apify Instagram Scraper Actor."""
    clean_handle = handle_or_url.strip()
    if "instagram.com/" in clean_handle.lower():
        clean_handle = clean_handle.split('/')[-1].split('?')[0]
    clean_handle = clean_handle.lstrip('@')

    token = (settings.APIFY_API_KEY or "").strip()
    if not token:
        return {
            "success": False,
            "platform": "instagram",
            "handle": f"@{clean_handle}",
            "message": "Apify token not set. Add APIFY_API_KEY to kre8-backend/.env (free $5/mo credit at apify.com) or enter metrics manually below."
        }

    actor_endpoint = f"https://api.apify.com/v2/acts/apify~instagram-profile-scraper/run-sync-get-dataset-items?token={token}"
    run_input = {"usernames": [clean_handle]}

    try:
        with httpx.Client(timeout=35.0) as client:
            res = client.post(actor_endpoint, json=run_input)
            if res.status_code not in (200, 201):
                alt_endpoint = f"https://api.apify.com/v2/acts/apidojo~instagram-scraper/run-sync-get-dataset-items?token={token}"
                res = client.post(alt_endpoint, json={"usernames": [clean_handle]})

            if res.status_code not in (200, 201):
                return {
                    "success": False,
                    "platform": "instagram",
                    "handle": f"@{clean_handle}",
                    "message": f"Apify error {res.status_code}: Please check your APIFY_API_KEY."
                }

            items = res.json()
            if not items or not isinstance(items, list):
                return {
                    "success": False,
                    "platform": "instagram",
                    "handle": f"@{clean_handle}",
                    "message": "No Instagram profile data returned."
                }

            prof = items[0]
            display_name = prof.get("fullName") or prof.get("username") or clean_handle
            avatar = prof.get("profilePicUrl") or prof.get("profilePicUrlHD")
            followers = int(prof.get("followersCount") or 0)
            posts_count = int(prof.get("postsCount") or 0)

            latest_posts = prof.get("latestPosts", [])
            recent_vids = []
            total_likes = 0
            for p in latest_posts[:10]:
                p_id = str(p.get("id") or p.get("shortCode") or "")
                caption = (p.get("caption") or "Instagram Post")
                p_likes = int(p.get("likesCount") or 0)
                p_comments = int(p.get("commentsCount") or 0)
                total_likes += p_likes
                recent_vids.append({
                    "video_id": p_id,
                    "title": caption[:70] + ("..." if len(caption) > 70 else ""),
                    "published_at": p.get("timestamp") or "",
                    "thumbnail_url": p.get("displayUrl") or avatar,
                    "views": p_likes * 8,
                    "likes": p_likes,
                    "comments": p_comments,
                    "engagement_rate": round(((p_likes + p_comments) / max(1, followers)) * 100, 2) if followers > 0 else 0.0,
                    "url": p.get("url") or f"https://www.instagram.com/p/{p.get('shortCode', '')}/"
                })

            avg_eng = round((total_likes / max(1, followers * len(recent_vids))) * 100, 2) if followers > 0 and recent_vids else 3.2

            return {
                "success": True,
                "platform": "instagram",
                "handle": f"@{clean_handle}",
                "channel_title": display_name,
                "channel_id": str(prof.get("id", clean_handle)),
                "avatar_url": avatar,
                "followers": followers,
                "total_videos": posts_count,
                "total_tracked_views": total_likes * 8,
                "avg_views": int((total_likes * 8) / max(1, len(recent_vids))) if recent_vids else 0,
                "avg_engagement": avg_eng,
                "cadence_weekly": round(len(recent_vids) / 2.0, 1) if recent_vids else 0.0,
                "top_video": max(recent_vids, key=lambda x: x["likes"]) if recent_vids else None,
                "recent_videos": recent_vids,
                "raw_metrics": {
                    "posts_count": posts_count,
                    "total_likes": total_likes
                }
            }
    except Exception as e:
        return {
            "success": False,
            "platform": "instagram",
            "handle": f"@{clean_handle}",
            "message": f"Apify Instagram lookup failed: {str(e)}"
        }


def fetch_youtube_telemetry(handle_or_url: str) -> Dict[str, Any]:
    """Inspect public YouTube channel handle for live subscriber count, avatar, channel title, and 15 recent video uploads."""
    clean_handle = handle_or_url.strip()
    if "youtube.com" in clean_handle.lower():
        m = re.search(r'youtube\.com/@([a-zA-Z0-9_\-\.]+)', clean_handle)
        if m:
            clean_handle = m.group(1)
        elif "/channel/" in clean_handle:
            clean_handle = clean_handle.split('/channel/')[-1].split('/')[0].split('?')[0]
        else:
            clean_handle = clean_handle.split('/')[-1].split('?')[0]
    clean_handle = clean_handle.lstrip('@')

    if clean_handle.startswith("UC") and len(clean_handle) >= 20:
        url = f"https://www.youtube.com/channel/{clean_handle}"
    else:
        url = f"https://www.youtube.com/@{clean_handle}"

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9'
    }

    try:
        html = ""
        try:
            p = subprocess.run(["curl.exe", "-s", "-L", "--max-time", "15", url], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, errors="ignore")
            if p.returncode == 0 and p.stdout:
                html = p.stdout
        except Exception:
            pass

        if not html:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=12) as res:
                html = res.read().decode('utf-8', errors='ignore')

        title_m = re.search(r'<meta property="og:title" content="([^"]+)"', html) or re.search(r'<title>([^<]+?)(?: - YouTube)?</title>', html)
        channel_title = title_m.group(1).replace(" - YouTube", "").strip() if title_m else clean_handle

        avatar_m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
        avatar_url = avatar_m.group(1) if avatar_m else None

        cid_m = re.search(r'"externalId":"([^"]+)"', html) or re.search(r'"browseId":"(UC[a-zA-Z0-9_\-]+)"', html) or re.search(r'<meta itemprop="channelId" content="([^"]+)"', html)
        cid = cid_m.group(1) if cid_m else (clean_handle if clean_handle.startswith("UC") else None)

        # Followers / subs
        sub_text = None
        followers = 0

        # Pattern 1: userInteractionCount (raw integer)
        uic_m = re.search(r'"userInteractionCount":"(\d+)"', html)
        if uic_m:
            count = int(uic_m.group(1))
            followers = count
            if count >= 1_000_000:
                sub_text = f"{count / 1_000_000:.1f}M subscribers"
            elif count >= 1_000:
                sub_text = f"{count / 1_000:.1f}K subscribers"
            else:
                sub_text = f"{count:,} subscribers"
        else:
            sub_content_m = re.search(r'"content":"([0-9\.]+[KMBkmb]?\s+subscribers?)"', html, re.IGNORECASE)
            if sub_content_m:
                sub_text = sub_content_m.group(1)
            else:
                sub_m = re.search(r'([0-9\.,]+[KMBkmb]?\s+subscribers)', html, re.IGNORECASE)
                if sub_m:
                    sub_text = sub_m.group(1)

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

@router.post("/lookup/{platform}")
def lookup_platform_handle(platform: str, req: PlatformLookupRequest):
    """Inspect any supported platform (YouTube, X, TikTok, Instagram) for live telemetry and recent content."""
    clean_handle = req.handle.strip()
    if not clean_handle:
        raise HTTPException(status_code=400, detail="Invalid handle or URL")
    p = platform.lower()
    if p == "youtube":
        return fetch_youtube_telemetry(clean_handle)
    elif p in ("x", "twitter"):
        return fetch_x_telemetry(clean_handle)
    elif p == "tiktok":
        return fetch_apify_tiktok(clean_handle)
    elif p == "instagram":
        return fetch_apify_instagram(clean_handle)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported platform '{platform}'. Supported: youtube, x, tiktok, instagram.")

@router.post("/connect/{platform}")
def connect_account(
    platform: str,
    payload: Optional[SocialConnectPayload] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Connect an account for YouTube, TikTok, Instagram, or X with real creator stats."""
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

    # Automated live inspection if handle provided and metrics not already fully manual
    plat = platform.lower()
    telemetry = None
    if name and (followers == 0 or not raw_data.get("recent_videos")):
        if plat == "youtube":
            telemetry = fetch_youtube_telemetry(name)
        elif plat in ("x", "twitter"):
            telemetry = fetch_x_telemetry(name)
        elif plat == "tiktok":
            telemetry = fetch_apify_tiktok(name)
        elif plat == "instagram":
            telemetry = fetch_apify_instagram(name)

    if telemetry and telemetry.get("success"):
        name = telemetry.get("channel_title") or name
        avatar = telemetry.get("avatar_url") or avatar
        cid = str(telemetry.get("channel_id") or cid or "")
        followers = telemetry.get("followers") or followers
        total_videos = telemetry.get("total_videos") or total_videos
        views = telemetry.get("total_tracked_views") or views
        engagement_rate = telemetry.get("avg_engagement") or engagement_rate
        raw_data = {
            "recent_videos": telemetry.get("recent_videos", []),
            "avg_views": telemetry.get("avg_views", 0),
            "cadence_weekly": telemetry.get("cadence_weekly", 0.0),
            "top_video": telemetry.get("top_video"),
            "subscribers_text": telemetry.get("subscribers_text"),
            **(telemetry.get("raw_metrics") or {})
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

    plat = account.platform.lower()
    telemetry = None
    if plat == "youtube":
        telemetry = fetch_youtube_telemetry(account.account_name)
    elif plat in ("x", "twitter"):
        telemetry = fetch_x_telemetry(account.account_name)
    elif plat == "tiktok":
        telemetry = fetch_apify_tiktok(account.account_name)
    elif plat == "instagram":
        telemetry = fetch_apify_instagram(account.account_name)

    if telemetry and telemetry.get("success"):
        account.account_name = telemetry.get("channel_title") or account.account_name
        if telemetry.get("avatar_url"):
            account.avatar_url = telemetry.get("avatar_url")
        if telemetry.get("channel_id"):
            account.channel_id = str(telemetry.get("channel_id"))
        if telemetry.get("total_videos") is not None:
            account.total_videos_count = int(telemetry.get("total_videos"))

        raw_data = {
            "recent_videos": telemetry.get("recent_videos", []),
            "avg_views": telemetry.get("avg_views", 0),
            "cadence_weekly": telemetry.get("cadence_weekly", 0.0),
            "top_video": telemetry.get("top_video"),
            "subscribers_text": telemetry.get("subscribers_text"),
            **(telemetry.get("raw_metrics") or {})
        }
        account.raw_details = raw_data
        account.last_synced_at = datetime.utcnow()
        db.commit()

        latest_snap = db.query(AnalyticsSnapshot).filter(
            AnalyticsSnapshot.social_account_id == account.id
        ).order_by(AnalyticsSnapshot.date.desc()).first()

        followers = telemetry.get("followers", 0)
        views = telemetry.get("total_tracked_views", 0)
        eng_rate = telemetry.get("avg_engagement", 0.0)

        if latest_snap and (latest_snap.date.date() == datetime.utcnow().date()):
            latest_snap.followers = followers
            latest_snap.views = views
            latest_snap.impressions = views * 2
            latest_snap.engagement_rate = eng_rate
            latest_snap.raw_data = raw_data
            db.commit()
        else:
            snap = AnalyticsSnapshot(
                social_account_id=account.id,
                followers=followers,
                views=views,
                impressions=views * 2,
                engagement_rate=eng_rate,
                raw_data=raw_data
            )
            db.add(snap)
            db.commit()

        return {
            "message": f"Synchronized live telemetry for {account.account_name}!",
            "success": True,
            "telemetry": telemetry
        }
    elif telemetry and not telemetry.get("success"):
        account.last_synced_at = datetime.utcnow()
        db.commit()
        raise HTTPException(status_code=502, detail=telemetry.get("message", "Live sync failed"))
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
                p = subprocess.run(["curl.exe", "-s", "-L", "--max-time", "15", target_url], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, errors="ignore")
                if p.returncode == 0 and p.stdout:
                    html = p.stdout
            except Exception:
                pass

            if not html:
                try:
                    http_req = urllib.request.Request(target_url, headers=request_headers)
                    with urllib.request.urlopen(http_req, timeout=12) as res:
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
                        subscriber_count_text = f"{count / 1_000:.1f}K subscribers"
                    else:
                        subscriber_count_text = f"{count:,} subscribers"
                else:
                    sub_content_m = re.search(r'"content":"([0-9\.]+[KMBkmb]?\s+subscribers?)"', html, re.IGNORECASE)
                    if sub_content_m:
                        subscriber_count_text = sub_content_m.group(1)
                    else:
                        sub_m = re.search(r'([0-9\.]+[KMBkmb]?\s+subscribers?)', html, re.IGNORECASE)
                        if sub_m:
                            subscriber_count_text = sub_m.group(1)

                # If recent titles not fetched yet, extract cid and query RSS
                if not recent_titles:
                    cid_m = re.search(r'"externalId":"([^"]+)"', html) or re.search(r'"browseId":"(UC[a-zA-Z0-9_\-]+)"', html) or re.search(r'<meta itemprop="channelId" content="([^"]+)"', html)
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
