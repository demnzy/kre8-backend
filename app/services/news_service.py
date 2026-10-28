import urllib.request
import urllib.parse
import json
import asyncio
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import feedparser
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session
from app.models.models import NewsArticle, UserPreferences
from app.core.config import settings

class DailyNewsService:
    @staticmethod
    def _map_niche_to_category(niche: str) -> Optional[str]:
        """Map user creator niche to valid NewsAPI category if applicable, else None."""
        n = (niche or "").lower().strip()
        if any(w in n for w in ["tech", "software", "ai", "artificial", "agent", "code", "cyber", "crypto", "robot"]):
            return "technology"
        if any(w in n for w in ["business", "finance", "money", "invest", "startup", "economy", "market"]):
            return "business"
        if any(w in n for w in ["health", "fitness", "wellness", "diet", "mental", "bio"]):
            return "health"
        if any(w in n for w in ["science", "space", "physics", "climate", "nature"]):
            return "science"
        if any(w in n for w in ["entertainment", "movie", "film", "music", "game", "gaming"]):
            return "entertainment"
        if any(w in n for w in ["sport", "athletic"]):
            return "sports"
        return None

    @classmethod
    def get_query_candidates(cls, niche: str, sub_niche: str, keywords: Optional[str] = None) -> List[str]:
        """Generate targeted search queries ordered from specific to high-signal broad."""
        candidates = []
        niche_clean = (niche or "").replace("&", " and ").replace('"', '').replace("'", '').strip()

        # Parse sub-niche topics if multi-topic selection was used
        raw_topics = [t.strip() for t in (sub_niche or "").split(",") if t.strip()]
        clean_topics = [t.replace("&", " and ").replace('"', '').replace("'", '').strip() for t in raw_topics if t.strip()]

        # 1. Multi-topic disjunction with primary niche
        if clean_topics and niche_clean:
            # Query with individual top sub-topics
            candidates.append(f"{niche_clean} OR {' OR '.join(clean_topics[:2])}")
            # Query with quotes around top subtopic phrases
            top_quoted = [f'"{t}"' for t in clean_topics[:2]]
            candidates.append(f"({' OR '.join(top_quoted)}) OR {niche_clean}")
        elif clean_topics:
            candidates.append(" OR ".join(clean_topics[:2]))

        # 2. Add domain-specific high-signal terms for specialized niches
        n_lower = niche_clean.lower()
        if n_lower in ["farming", "farm", "agriculture"]:
            candidates.append("farming OR agriculture OR livestock OR crops")
            candidates.append("agricultural technology OR regenerative farming")
        elif n_lower in ["finance", "investing", "crypto"]:
            candidates.append("investing OR cryptocurrency OR personal finance")
        elif n_lower in ["health", "fitness", "longevity"]:
            candidates.append("fitness OR longevity OR nutrition OR wellness")
        elif niche_clean:
            candidates.append(niche_clean)

        if keywords and keywords.strip():
            kws = [k.replace("&", " and ").replace('"', '').strip() for k in keywords.split(",") if k.strip()][:2]
            if kws:
                candidates.append(" OR ".join(kws))

        # Deduplicate preserving order
        seen = set()
        result = []
        for c in candidates:
            c_norm = c.strip()
            if c_norm and c_norm not in seen:
                seen.add(c_norm)
                result.append(c_norm)

        if not result:
            result.append(niche_clean or "technology")
        return result

    @staticmethod
    def is_relevant_article(title: str, summary: str, niche: str, sub_niche: str) -> bool:
        """Verify that an article is genuinely relevant to the creator's niche and sub-niche."""
        text = f"{title} {summary}".lower()
        n = (niche or "").lower().strip()

        # Check primary niche name
        if n and n in text:
            return True

        # Check domain-specific synonyms
        synonyms = {
            "farming": ["farm", "farmer", "agricultur", "crop", "livestock", "harvest", "soil", "cattle", "pastur", "agri", "dairy", "grain", "fertilizer", "poultry"],
            "finance": ["money", "market", "invest", "stock", "econom", "fed", "bank", "wealth", "fund", "treasury"],
            "fitness": ["workout", "exercise", "muscle", "train", "diet", "gym", "bodybuild", "athlet", "cardio"],
            "health": ["health", "medic", "diseas", "doctor", "wellness", "biotech", "longev", "therap", "clinic"],
            "technology": ["tech", "software", "ai", "hardware", "app", "code", "cyber", "data", "cloud"],
            "crypto": ["crypto", "bitcoin", "ethereum", "blockchain", "token", "btc", "eth", "solana", "web3"]
        }
        for syn in synonyms.get(n, []):
            if syn in text:
                return True

        # Check for significant words in the sub-niche (length >= 4)
        sub_words = [w.lower() for w in re.findall(r'\b[a-zA-Z]{4,}\b', sub_niche or "")]
        matches = sum(1 for w in sub_words if w in text)
        if matches >= 1:
            return True

        return False

    @classmethod
    async def fetch_specialized_news_api(
        cls, candidates: List[str], api_key: str, limit: int = 10, niche: str = "technology", sub_niche: str = ""
    ) -> List[Dict[str, Any]]:
        """Query specialized live news search APIs (NewsAPI.org or GNews.io) with strict relevancy filtering."""
        articles: List[Dict[str, Any]] = []
        clean_key = api_key.strip()
        if not clean_key:
            return articles

        headers = {
            "User-Agent": "Kre8/1.0 (Creator Studio; contact@kre8.local)"
        }

        # 1. NewsAPI.org format (32 hex characters)
        if len(clean_key) == 32:
            def _fetch_url(target_url: str) -> Optional[dict]:
                req = urllib.request.Request(target_url, headers=headers)
                try:
                    with urllib.request.urlopen(req, timeout=8) as resp:
                        return json.loads(resp.read().decode("utf-8", errors="ignore"))
                except Exception as ex:
                    print(f"[NewsService] NewsAPI request failed: {ex}")
                    return None

            for query in candidates:
                encoded_query = urllib.parse.quote(query)
                url = f"https://newsapi.org/v2/everything?q={encoded_query}&sortBy=relevancy&pageSize={limit}&language=en&apiKey={clean_key}"

                data = await asyncio.to_thread(_fetch_url, url)
                if data and data.get("status") == "ok":
                    raw_items = data.get("articles", [])
                    for item in raw_items:
                        title = item.get("title") or ""
                        summary = (item.get("description") or title)[:350]
                        if not title or "[Removed]" in title:
                            continue

                        # Strict relevancy check
                        if not cls.is_relevant_article(title, summary, niche, sub_niche):
                            continue

                        articles.append({
                            "headline": title,
                            "summary": summary,
                            "source_name": item.get("source", {}).get("name") or "Verified News",
                            "source_url": item.get("url") or "",
                            "image_url": item.get("urlToImage"),
                            "published_date": item.get("publishedAt") or datetime.utcnow().strftime("%a, %d %b %Y")
                        })
                        if len(articles) >= limit:
                            break

                if len(articles) >= 3:
                    print(f"[NewsService] NewsAPI.org returned {len(articles)} verified relevant articles for '{query}'.")
                    return articles

            # Category top-headlines ONLY if niche explicitly maps to a category
            valid_category = cls._map_niche_to_category(niche)
            if valid_category and len(articles) < 3:
                cat_url = f"https://newsapi.org/v2/top-headlines?category={valid_category}&pageSize={limit}&language=en&apiKey={clean_key}"
                data = await asyncio.to_thread(_fetch_url, cat_url)
                if data and data.get("status") == "ok":
                    for item in data.get("articles", []):
                        title = item.get("title") or ""
                        summary = (item.get("description") or title)[:350]
                        if not title or "[Removed]" in title:
                            continue
                        if not cls.is_relevant_article(title, summary, niche, sub_niche):
                            continue
                        articles.append({
                            "headline": title,
                            "summary": summary,
                            "source_name": item.get("source", {}).get("name") or "Verified News",
                            "source_url": item.get("url") or "",
                            "image_url": item.get("urlToImage"),
                            "published_date": item.get("publishedAt") or datetime.utcnow().strftime("%a, %d %b %Y")
                        })
                        if len(articles) >= limit:
                            break

        return articles

    # Curated authoritative niche feeds to blend with Google News RSS
    NICHE_DIRECT_FEEDS = {
        "technology": [
            ("TechCrunch", "https://techcrunch.com/feed/"),
            ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
            ("The Verge", "https://www.theverge.com/rss/index.xml"),
            ("Hacker News", "https://news.ycombinator.com/rss")
        ],
        "business": [
            ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
            ("CNBC", "https://search.cnbc.com/rs/search/view.html?partnerId=2000&keywords=investing&sort=date")
        ],
        "science": [
            ("ScienceDaily", "https://www.sciencedaily.com/rss/top/science.xml")
        ]
    }

    @classmethod
    async def fetch_news_rss(cls, candidates: List[str], limit: int = 20, niche: str = "", sub_niche: str = "") -> List[Dict[str, Any]]:
        """Fetch real-time live daily news from Google News RSS feed and curated niche publication feeds."""
        articles: List[Dict[str, Any]] = []
        seen_titles = set()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        }

        def _fetch_rss(target_url: str) -> Optional[str]:
            req = urllib.request.Request(target_url, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=8) as resp:
                    return resp.read().decode("utf-8", errors="ignore")
            except Exception as ex:
                return None

        # 1. First, search Google News RSS for each targeted candidate query
        for query in candidates:
            if len(articles) >= limit:
                break
            clean_q = query.replace('"', '').strip()
            encoded_query = urllib.parse.quote(clean_q)
            rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"

            raw_xml = await asyncio.to_thread(_fetch_rss, rss_url)
            if raw_xml:
                feed = feedparser.parse(raw_xml)
                for entry in feed.entries[:8]:
                    title = entry.get("title", "")
                    source_name = "Industry News"
                    if " - " in title:
                        parts = title.rsplit(" - ", 1)
                        title = parts[0]
                        source_name = parts[1]

                    norm_title = title.lower().strip()
                    if norm_title in seen_titles:
                        continue

                    raw_summary = entry.get("summary", "")
                    soup = BeautifulSoup(raw_summary, "html.parser")

                    img_tag = soup.find("img")
                    image_url = img_tag.get("src") if img_tag else None

                    clean_summary = soup.get_text(separator=" ").strip()
                    if not clean_summary:
                        clean_summary = title

                    # Relevancy check
                    if not cls.is_relevant_article(title, clean_summary, niche, sub_niche):
                        continue

                    seen_titles.add(norm_title)
                    link = entry.get("link", "")
                    pub_date = entry.get("published", datetime.utcnow().strftime("%a, %d %b %Y"))

                    articles.append({
                        "headline": title,
                        "summary": clean_summary[:350],
                        "source_name": source_name,
                        "source_url": link,
                        "image_url": image_url,
                        "published_date": pub_date
                    })
                    if len(articles) >= limit:
                        break

        # 2. Blend in direct publications if available for this niche category
        cat = cls._map_niche_to_category(niche) or "technology"
        direct_sources = cls.NICHE_DIRECT_FEEDS.get(cat, [])
        for src_name, feed_url in direct_sources:
            if len(articles) >= limit:
                break
            raw_xml = await asyncio.to_thread(_fetch_rss, feed_url)
            if raw_xml:
                feed = feedparser.parse(raw_xml)
                for entry in feed.entries[:5]:
                    title = entry.get("title", "")
                    norm_title = title.lower().strip()
                    if not title or norm_title in seen_titles:
                        continue

                    raw_summary = entry.get("summary", "") or entry.get("description", "")
                    soup = BeautifulSoup(raw_summary, "html.parser")
                    img_tag = soup.find("img")
                    image_url = img_tag.get("src") if img_tag else None
                    clean_summary = soup.get_text(separator=" ").strip() or title

                    if not cls.is_relevant_article(title, clean_summary, niche, sub_niche):
                        continue

                    seen_titles.add(norm_title)
                    articles.append({
                        "headline": title,
                        "summary": clean_summary[:350],
                        "source_name": src_name,
                        "source_url": entry.get("link", ""),
                        "image_url": image_url,
                        "published_date": entry.get("published", datetime.utcnow().strftime("%a, %d %b %Y"))
                    })
                    if len(articles) >= limit:
                        break

        return articles

    @classmethod
    async def get_or_refresh_daily_news(
        cls,
        db: Session,
        niche: str,
        sub_niche: str,
        keywords: Optional[str] = None,
        force_refresh: bool = False,
        api_key: Optional[str] = None
    ) -> List[NewsArticle]:
        """Fetch cached news or query live NewsAPI / RSS engine with strict niche relevancy."""
        now = datetime.utcnow()
        two_hours_ago = now - timedelta(hours=2)

        # Check cache if not forcing refresh
        if not force_refresh:
            cached = (
                db.query(NewsArticle)
                .filter(
                    NewsArticle.niche == niche,
                    NewsArticle.sub_niche == sub_niche,
                    NewsArticle.fetched_at >= two_hours_ago,
                    NewsArticle.source_name != "Industry Wire",
                    ~NewsArticle.headline.like("%Major Breakthrough Unveiled%")
                )
                .order_by(NewsArticle.id.desc())
                .limit(20)
                .all()
            )
            # Ensure cached items are genuinely relevant to this niche
            valid_cached = [
                a for a in cached
                if cls.is_relevant_article(a.headline, a.summary, niche, sub_niche)
            ]
            if len(valid_cached) >= 6:
                return valid_cached

        # Purge stale or irrelevant articles for this niche when refreshing
        try:
            old_arts = db.query(NewsArticle).filter(
                NewsArticle.niche == niche,
                NewsArticle.sub_niche == sub_niche
            ).all()
            deleted_count = 0
            for oa in old_arts:
                if not cls.is_relevant_article(oa.headline, oa.summary, niche, sub_niche) or force_refresh:
                    db.delete(oa)
                    deleted_count += 1
            if deleted_count > 0:
                db.commit()
                print(f"[NewsService] Purged {deleted_count} stale/irrelevant articles for niche '{niche}'.")
        except Exception as e:
            db.rollback()
            print(f"[NewsService] Cache purge warning: {e}")

        # Build prioritized query candidates
        candidates = cls.get_query_candidates(niche, sub_niche, keywords)
        active_news_key = api_key or getattr(settings, "NEWS_API_KEY", "")

        fresh_items: List[Dict[str, Any]] = []

        # 1. Query specialized News API candidates
        if active_news_key and active_news_key.strip():
            fresh_items = await cls.fetch_specialized_news_api(
                candidates=candidates,
                api_key=active_news_key,
                limit=20,
                niche=niche,
                sub_niche=sub_niche
            )

        # 2. Seamlessly blend with Google News RSS & niche publication feeds
        if len(fresh_items) < 15:
            rss_items = await cls.fetch_news_rss(candidates, limit=20, niche=niche, sub_niche=sub_niche)
            for ri in rss_items:
                if not any(f["headline"].strip().lower() == ri["headline"].strip().lower() for f in fresh_items):
                    fresh_items.append(ri)
                if len(fresh_items) >= 20:
                    break

        # Save to DB
        created_records = []
        for item in fresh_items:
            article = NewsArticle(
                niche=niche,
                sub_niche=sub_niche,
                headline=item["headline"],
                summary=item["summary"],
                source_name=item["source_name"],
                source_url=item["source_url"],
                image_url=item.get("image_url"),
                published_date=item["published_date"],
                fetched_at=now
            )
            db.add(article)
            created_records.append(article)

        if created_records:
            db.commit()
            for r in created_records:
                db.refresh(r)
            return created_records

        # If completely empty, return whatever existing items matched
        fallback_existing = (
            db.query(NewsArticle)
            .filter(NewsArticle.niche == niche, NewsArticle.sub_niche == sub_niche)
            .order_by(NewsArticle.id.desc())
            .limit(10)
            .all()
        )
        return fallback_existing

news_service = DailyNewsService()
