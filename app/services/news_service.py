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

REGION_CONFIG: Dict[str, Dict[str, Any]] = {
    "GLOBAL": {
        "code": "GLOBAL",
        "label": "Global",
        "flag": "🌐",
        "gl": "US",
        "hl": "en-US",
        "ceid": "US:en",
        "country": None,
        "description": "Worldwide headlines & international breaking trends"
    },
    "NG": {
        "code": "NG",
        "label": "Nigeria",
        "flag": "🇳🇬",
        "gl": "NG",
        "hl": "en-NG",
        "ceid": "NG:en",
        "country": "ng",
        "description": "Nigerian tech, startup, economy & creator updates"
    },
    "US": {
        "code": "US",
        "label": "United States",
        "flag": "🇺🇸",
        "gl": "US",
        "hl": "en-US",
        "ceid": "US:en",
        "country": "us",
        "description": "US media, Silicon Valley, business & culture"
    },
    "UK": {
        "code": "UK",
        "label": "United Kingdom",
        "flag": "🇬🇧",
        "gl": "GB",
        "hl": "en-GB",
        "ceid": "GB:en",
        "country": "gb",
        "description": "UK tech, media, business & European policy"
    },
    "CA": {
        "code": "CA",
        "label": "Canada",
        "flag": "🇨🇦",
        "gl": "CA",
        "hl": "en-CA",
        "ceid": "CA:en",
        "country": "ca",
        "description": "Canadian innovation, startups, media & tech"
    },
    "IN": {
        "code": "IN",
        "label": "India",
        "flag": "🇮🇳",
        "gl": "IN",
        "hl": "en-IN",
        "ceid": "IN:en",
        "country": "in",
        "description": "Indian creator economy, venture, AI & tech ecosystem"
    },
    "ZA": {
        "code": "ZA",
        "label": "South Africa",
        "flag": "🇿🇦",
        "gl": "ZA",
        "hl": "en-ZA",
        "ceid": "ZA:en",
        "country": "za",
        "description": "South African & Southern Africa media & business"
    },
    "KE": {
        "code": "KE",
        "label": "Kenya",
        "flag": "🇰🇪",
        "gl": "KE",
        "hl": "en-KE",
        "ceid": "KE:en",
        "country": "ke",
        "description": "East African Silicon Savannah & creator stories"
    },
    "EU": {
        "code": "EU",
        "label": "Europe",
        "flag": "🇪🇺",
        "gl": "DE",
        "hl": "en-DE",
        "ceid": "DE:en",
        "country": "de",
        "description": "European tech, AI governance & startup ecosystems"
    }
}

class DailyNewsService:
    # Curated authoritative publications by geographic region
    REGIONAL_DIRECT_FEEDS: Dict[str, List[tuple]] = {
        "NG": [
            ("TechCabal", "https://techcabal.com/feed/"),
            ("Techpoint Africa", "https://techpoint.africa/feed/"),
            ("Benjamin Dada", "https://www.benjamindada.com/feed/"),
            ("BusinessDay Nigeria", "https://businessday.ng/feed/"),
            ("Punch Nigeria", "https://punchng.com/feed/"),
            ("Premium Times", "https://www.premiumtimesng.com/feed"),
            ("Nairametrics", "https://nairametrics.com/feed/"),
            ("Rest of World (Africa)", "https://restofworld.org/region/africa/feed")
        ],
        "KE": [
            ("Techweez", "https://techweez.com/feed/"),
            ("Disrupt Africa", "https://disrupt-africa.com/feed/"),
            ("Business Daily Africa", "https://www.businessdailyafrica.com/feed"),
            ("Rest of World (Africa)", "https://restofworld.org/region/africa/feed")
        ],
        "ZA": [
            ("MyBroadband", "https://mybroadband.co.za/news/feed"),
            ("ITWeb", "https://www.itweb.co.za/rss/all"),
            ("Ventureburn", "https://ventureburn.com/feed/"),
            ("Disrupt Africa", "https://disrupt-africa.com/feed/")
        ],
        "UK": [
            ("Sifted", "https://sifted.eu/feed"),
            ("The Guardian Tech", "https://www.theguardian.com/uk/technology/rss"),
            ("BBC News Tech", "https://feeds.bbci.co.uk/news/technology/rss.xml"),
            ("The Register", "https://www.theregister.com/headlines.atom")
        ],
        "EU": [
            ("Sifted", "https://sifted.eu/feed"),
            ("EU-Startups", "https://www.eu-startups.com/feed/"),
            ("Euronews Next", "https://www.euronews.com/rss?format=mrss&level=theme&name=next")
        ],
        "IN": [
            ("YourStory", "https://yourstory.com/feed"),
            ("Inc42", "https://inc42.com/feed/"),
            ("Economic Times Tech", "https://economictimes.indiatimes.com/tech/rssfeeds/13357270.cms"),
            ("MediaNama", "https://www.medianama.com/feed/")
        ],
        "CA": [
            ("BetaKit", "https://betakit.com/feed/"),
            ("MobileSyrup", "https://mobilesyrup.com/feed/")
        ],
        "US": [
            ("TechCrunch", "https://techcrunch.com/feed/"),
            ("The Verge", "https://www.theverge.com/rss/index.xml"),
            ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
            ("VentureBeat", "https://venturebeat.com/feed/"),
            ("MIT Technology Review", "https://www.technologyreview.com/feed/")
        ],
        "GLOBAL": [
            ("Rest of World", "https://restofworld.org/feed/latest"),
            ("TechCrunch", "https://techcrunch.com/feed/"),
            ("The Verge", "https://www.theverge.com/rss/index.xml"),
            ("Hacker News", "https://news.ycombinator.com/rss"),
            ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index")
        ]
    }

    # Curated authoritative publications by category / creator niche
    NICHE_DIRECT_FEEDS: Dict[str, List[tuple]] = {
        "creator": [
            ("Tubefilter", "https://www.tubefilter.com/feed/"),
            ("Social Media Today", "https://www.socialmediatoday.com/feeds/news/"),
            ("Digiday", "https://digiday.com/feed/"),
            ("The Verge Creators", "https://www.theverge.com/rss/creator/index.xml")
        ],
        "technology": [
            ("TechCrunch", "https://techcrunch.com/feed/"),
            ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
            ("The Verge", "https://www.theverge.com/rss/index.xml"),
            ("Hacker News", "https://news.ycombinator.com/rss"),
            ("VentureBeat AI", "https://venturebeat.com/category/ai/feed/")
        ],
        "business": [
            ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
            ("CNBC", "https://search.cnbc.com/rs/search/view.html?partnerId=2000&keywords=investing&sort=date"),
            ("Rest of World Business", "https://restofworld.org/feed/latest")
        ],
        "gaming": [
            ("Polygon", "https://www.polygon.com/rss/index.xml"),
            ("Eurogamer", "https://www.eurogamer.net/feed"),
            ("PC Gamer", "https://www.pcgamer.com/rss")
        ],
        "science": [
            ("ScienceDaily", "https://www.sciencedaily.com/rss/top/science.xml"),
            ("Medical News Today", "https://rss.medicalnewstoday.com/featurednews.xml")
        ],
        "design": [
            ("Creative Bloq", "https://www.creativebloq.com/feed"),
            ("It's Nice That", "https://www.itsnicethat.com/rss")
        ]
    }

    @staticmethod
    def _map_niche_to_category(niche: str) -> str:
        """Map user creator niche to standardized category."""
        n = (niche or "").lower().strip()
        if any(w in n for w in ["creator", "youtube", "media", "social", "stream", "video", "influencer", "content"]):
            return "creator"
        if any(w in n for w in ["tech", "software", "ai", "artificial", "agent", "code", "cyber", "robot"]):
            return "technology"
        if any(w in n for w in ["business", "finance", "money", "invest", "startup", "economy", "market", "crypto"]):
            return "business"
        if any(w in n for w in ["gaming", "game", "esport"]):
            return "gaming"
        if any(w in n for w in ["design", "creative", "ui", "ux", "art", "architecture"]):
            return "design"
        if any(w in n for w in ["health", "fitness", "wellness", "science", "space", "biology", "longevity"]):
            return "science"
        return "technology"

    @classmethod
    def _detect_category(cls, title: str, summary: str, fallback_niche: str) -> str:
        text = f"{title} {summary}".lower()
        if any(w in text for w in ["youtube", "tiktok", "creator", "influencer", "subscribers", "monetiz", "streamer", "algorithm", "podcast"]):
            return "creator"
        if any(w in text for w in ["ai", "model", "llm", "software", "tech", "app", "chip", "nvidia", "google", "apple", "microsoft", "code"]):
            return "technology"
        if any(w in text for w in ["funding", "startup", "investor", "revenue", "dollar", "naira", "market", "economy", "crypto", "valuation"]):
            return "business"
        if any(w in text for w in ["game", "gaming", "playstation", "xbox", "steam", "nintendo", "esport"]):
            return "gaming"
        if any(w in text for w in ["health", "study", "doctor", "medicine", "nasa", "space", "science", "climate"]):
            return "science"
        if any(w in text for w in ["design", "ux", "ui", "creative", "typography", "branding"]):
            return "design"
        return cls._map_niche_to_category(fallback_niche)

    @classmethod
    def get_query_candidates(cls, niche: str, sub_niche: str, keywords: Optional[str] = None, region: str = "GLOBAL") -> List[str]:
        """Generate targeted search queries tailored to niche, sub-niche, and region."""
        candidates = []
        niche_clean = (niche or "").replace("&", " and ").replace('"', '').replace("'", '').strip()

        # Parse sub-niche topics if multi-topic selection was used
        raw_topics = [t.strip() for t in (sub_niche or "").split(",") if t.strip()]
        clean_topics = [t.replace("&", " and ").replace('"', '').replace("'", '').strip() for t in raw_topics if t.strip()]

        # Regional modifier if applicable
        reg_mod = ""
        if region == "NG":
            reg_mod = "Nigeria OR Africa"
        elif region == "UK":
            reg_mod = "UK OR Britain"
        elif region == "IN":
            reg_mod = "India"
        elif region == "CA":
            reg_mod = "Canada"
        elif region == "ZA":
            reg_mod = "South Africa"
        elif region == "KE":
            reg_mod = "Kenya OR East Africa"

        # 1. Multi-topic disjunction with primary niche
        if clean_topics and niche_clean:
            if reg_mod:
                candidates.append(f"({niche_clean} OR {clean_topics[0]}) AND ({reg_mod})")
            candidates.append(f"{niche_clean} OR {' OR '.join(clean_topics[:2])}")
            top_quoted = [f'"{t}"' for t in clean_topics[:2]]
            candidates.append(f"({' OR '.join(top_quoted)}) OR {niche_clean}")
        elif clean_topics:
            candidates.append(" OR ".join(clean_topics[:2]))

        # 2. Add domain-specific high-signal terms for specialized niches
        n_lower = niche_clean.lower()
        if any(w in n_lower for w in ["creator", "media", "video", "content"]):
            candidates.append("creator economy OR youtube algorithm OR tiktok trends")
            candidates.append("content creators OR video production OR digital media")
        elif any(w in n_lower for w in ["ai", "tech", "software"]):
            candidates.append("artificial intelligence OR autonomous agents OR generative ai")
            candidates.append("ai technology OR tech startup OR developer tools")
        elif any(w in n_lower for w in ["business", "finance", "money", "startup"]):
            candidates.append("startup venture OR venture capital OR personal finance")
            candidates.append("business economy OR fintech OR markets")
        elif any(w in n_lower for w in ["health", "fitness", "longevity"]):
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
    def is_relevant_article(title: str, summary: str, niche: str, sub_niche: str, region: str = "GLOBAL") -> bool:
        """Verify that an article is genuinely relevant to the creator's niche and sub-niche."""
        text = f"{title} {summary}".lower()
        n = (niche or "").lower().strip()

        # Check primary niche name
        if n and n in text:
            return True

        # Check domain-specific synonyms
        synonyms = {
            "creator": ["creator", "youtube", "tiktok", "video", "streamer", "influencer", "subscribers", "content", "podcast", "monetiz", "instagram", "reels", "shorts"],
            "farming": ["farm", "farmer", "agricultur", "crop", "livestock", "harvest", "soil", "cattle", "pastur", "agri", "dairy", "grain", "fertilizer", "poultry"],
            "finance": ["money", "market", "invest", "stock", "econom", "fed", "bank", "wealth", "fund", "treasury", "fintech", "startup"],
            "fitness": ["workout", "exercise", "muscle", "train", "diet", "gym", "bodybuild", "athlet", "cardio"],
            "health": ["health", "medic", "diseas", "doctor", "wellness", "biotech", "longev", "therap", "clinic"],
            "technology": ["tech", "software", "ai", "hardware", "app", "code", "cyber", "data", "cloud", "model", "developer", "agent", "llm"],
            "crypto": ["crypto", "bitcoin", "ethereum", "blockchain", "token", "btc", "eth", "solana", "web3"]
        }
        
        # If niche is creator / media, also check creator synonyms
        cat = DailyNewsService._map_niche_to_category(niche)
        for syn in synonyms.get(cat, []) + synonyms.get(n, []):
            if syn in text:
                return True

        # Check for significant words in the sub-niche (length >= 4)
        sub_words = [w.lower() for w in re.findall(r'\b[a-zA-Z]{4,}\b', sub_niche or "")]
        matches = sum(1 for w in sub_words if w in text)
        if matches >= 1:
            return True

        # If region is localized (e.g. NG, UK, IN), check regional keywords
        if region == "NG" and any(k in text for k in ["nigeria", "lagos", "african", "naira", "cabal", "techpoint"]):
            return True
        if region == "KE" and any(k in text for k in ["kenya", "nairobi", "east africa", "mpesa", "shilling"]):
            return True
        if region == "ZA" and any(k in text for k in ["south africa", "cape town", "johannesburg", "rand"]):
            return True
        if region == "UK" and any(k in text for k in ["uk", "britain", "london", "pound", "rishi", "sifted"]):
            return True
        if region == "IN" and any(k in text for k in ["india", "bengaluru", "delhi", "mumbai", "rupee", "yourstory"]):
            return True

        return False

    @classmethod
    async def fetch_specialized_news_api(
        cls,
        candidates: List[str],
        api_key: str,
        limit: int = 15,
        niche: str = "technology",
        sub_niche: str = "",
        region: str = "GLOBAL"
    ) -> List[Dict[str, Any]]:
        """Query live news search APIs supporting NewsAPI.org, GNews.io, and NewsData.io with region localization."""
        articles: List[Dict[str, Any]] = []
        clean_key = api_key.strip()
        if not clean_key:
            return articles

        headers = {
            "User-Agent": "Kre8/1.0 (Creator Studio; contact@kre8.local)"
        }

        reg_info = REGION_CONFIG.get(region, REGION_CONFIG["GLOBAL"])
        country_code = reg_info.get("country")
        category_name = cls._map_niche_to_category(niche)

        def _fetch_url(target_url: str) -> Optional[dict]:
            req = urllib.request.Request(target_url, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=9) as resp:
                    return json.loads(resp.read().decode("utf-8", errors="ignore"))
            except Exception as ex:
                print(f"[NewsService] Live News API request failed ({target_url[:60]}...): {ex}")
                return None

        # A. NewsData.io format (keys usually start with 'pub_')
        if clean_key.startswith("pub_"):
            for query in candidates[:2]:
                encoded_q = urllib.parse.quote(query)
                url = f"https://newsdata.io/api/1/news?apikey={clean_key}&q={encoded_q}&language=en"
                if country_code:
                    url += f"&country={country_code}"
                data = await asyncio.to_thread(_fetch_url, url)
                if data and data.get("status") == "success":
                    for item in data.get("results", []):
                        title = item.get("title") or ""
                        summary = (item.get("description") or title)[:350]
                        if not title or "[Removed]" in title:
                            continue
                        if not cls.is_relevant_article(title, summary, niche, sub_niche, region):
                            continue
                        articles.append({
                            "headline": title,
                            "summary": summary,
                            "source_name": item.get("source_id") or "News Wire",
                            "source_url": item.get("link") or "",
                            "image_url": item.get("image_url"),
                            "published_date": item.get("pubDate") or datetime.utcnow().strftime("%a, %d %b %Y"),
                            "region": region,
                            "category": cls._detect_category(title, summary, niche)
                        })
                        if len(articles) >= limit:
                            return articles

        # B. NewsAPI.org format (32 hex characters)
        elif len(clean_key) == 32 and re.match(r'^[a-f0-9]{32}$', clean_key, re.I):
            for query in candidates[:2]:
                encoded_query = urllib.parse.quote(query)
                url = f"https://newsapi.org/v2/everything?q={encoded_query}&sortBy=relevancy&pageSize={limit}&language=en&apiKey={clean_key}"
                data = await asyncio.to_thread(_fetch_url, url)
                if data and data.get("status") == "ok":
                    for item in data.get("articles", []):
                        title = item.get("title") or ""
                        summary = (item.get("description") or title)[:350]
                        if not title or "[Removed]" in title:
                            continue
                        if not cls.is_relevant_article(title, summary, niche, sub_niche, region):
                            continue
                        articles.append({
                            "headline": title,
                            "summary": summary,
                            "source_name": item.get("source", {}).get("name") or "Verified News",
                            "source_url": item.get("url") or "",
                            "image_url": item.get("urlToImage"),
                            "published_date": item.get("publishedAt") or datetime.utcnow().strftime("%a, %d %b %Y"),
                            "region": region,
                            "category": cls._detect_category(title, summary, niche)
                        })
                        if len(articles) >= limit:
                            return articles

            # Top headlines fallback with country code
            if country_code and len(articles) < 3:
                cat_url = f"https://newsapi.org/v2/top-headlines?country={country_code}&category={category_name}&pageSize={limit}&apiKey={clean_key}"
                data = await asyncio.to_thread(_fetch_url, cat_url)
                if data and data.get("status") == "ok":
                    for item in data.get("articles", []):
                        title = item.get("title") or ""
                        summary = (item.get("description") or title)[:350]
                        if not title or "[Removed]" in title:
                            continue
                        articles.append({
                            "headline": title,
                            "summary": summary,
                            "source_name": item.get("source", {}).get("name") or "Top Wire",
                            "source_url": item.get("url") or "",
                            "image_url": item.get("urlToImage"),
                            "published_date": item.get("publishedAt") or datetime.utcnow().strftime("%a, %d %b %Y"),
                            "region": region,
                            "category": category_name
                        })

        # C. GNews.io format
        else:
            for query in candidates[:2]:
                encoded_q = urllib.parse.quote(query)
                url = f"https://gnews.io/api/v4/search?q={encoded_q}&lang=en&max={limit}&apikey={clean_key}"
                if country_code:
                    url += f"&country={country_code}"
                data = await asyncio.to_thread(_fetch_url, url)
                if data and "articles" in data:
                    for item in data.get("articles", []):
                        title = item.get("title") or ""
                        summary = (item.get("description") or title)[:350]
                        articles.append({
                            "headline": title,
                            "summary": summary,
                            "source_name": item.get("source", {}).get("name") or "GNews Wire",
                            "source_url": item.get("url") or "",
                            "image_url": item.get("image"),
                            "published_date": item.get("publishedAt") or datetime.utcnow().strftime("%a, %d %b %Y"),
                            "region": region,
                            "category": cls._detect_category(title, summary, niche)
                        })
                        if len(articles) >= limit:
                            return articles

        return articles

    @classmethod
    async def fetch_news_rss(
        cls,
        candidates: List[str],
        limit: int = 25,
        niche: str = "",
        sub_niche: str = "",
        region: str = "GLOBAL",
        category: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Fetch real-time live daily news from localized Google News RSS feed, regional publishers, and curated niche publication feeds."""
        articles: List[Dict[str, Any]] = []
        seen_titles = set()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        }

        reg_info = REGION_CONFIG.get(region, REGION_CONFIG["GLOBAL"])
        gl = reg_info.get("gl", "US")
        hl = reg_info.get("hl", "en-US")
        ceid = reg_info.get("ceid", "US:en")

        def _fetch_rss(target_url: str) -> Optional[str]:
            req = urllib.request.Request(target_url, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=8) as resp:
                    return resp.read().decode("utf-8", errors="ignore")
            except Exception:
                return None

        # 1. Localized Google News RSS for each targeted candidate query
        for query in candidates:
            if len(articles) >= limit:
                break
            clean_q = query.replace('"', '').strip()
            encoded_query = urllib.parse.quote(clean_q)
            rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl={hl}&gl={gl}&ceid={ceid}"

            raw_xml = await asyncio.to_thread(_fetch_rss, rss_url)
            if raw_xml:
                feed = feedparser.parse(raw_xml)
                for entry in feed.entries[:8]:
                    title = entry.get("title", "")
                    source_name = "Industry Wire"
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

                    if not cls.is_relevant_article(title, clean_summary, niche, sub_niche, region):
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
                        "published_date": pub_date,
                        "region": region,
                        "category": cls._detect_category(title, clean_summary, niche)
                    })
                    if len(articles) >= limit:
                        break

        # 2. Blend direct regional publications for this specific region
        direct_regional = cls.REGIONAL_DIRECT_FEEDS.get(region, cls.REGIONAL_DIRECT_FEEDS.get("GLOBAL", []))
        for src_name, feed_url in direct_regional:
            if len(articles) >= limit:
                break
            raw_xml = await asyncio.to_thread(_fetch_rss, feed_url)
            if raw_xml:
                feed = feedparser.parse(raw_xml)
                for entry in feed.entries[:6]:
                    title = entry.get("title", "")
                    norm_title = title.lower().strip()
                    if not title or norm_title in seen_titles:
                        continue

                    raw_summary = entry.get("summary", "") or entry.get("description", "")
                    soup = BeautifulSoup(raw_summary, "html.parser")
                    img_tag = soup.find("img")
                    image_url = img_tag.get("src") if img_tag else None
                    clean_summary = soup.get_text(separator=" ").strip() or title

                    if not cls.is_relevant_article(title, clean_summary, niche, sub_niche, region):
                        continue

                    seen_titles.add(norm_title)
                    articles.append({
                        "headline": title,
                        "summary": clean_summary[:350],
                        "source_name": src_name,
                        "source_url": entry.get("link", ""),
                        "image_url": image_url,
                        "published_date": entry.get("published", datetime.utcnow().strftime("%a, %d %b %Y")),
                        "region": region,
                        "category": cls._detect_category(title, clean_summary, niche)
                    })
                    if len(articles) >= limit:
                        break

        # 3. Blend direct niche publications (creator economy, tech, business)
        target_cat = category or cls._map_niche_to_category(niche)
        direct_niche = cls.NICHE_DIRECT_FEEDS.get(target_cat, [])
        # Always mix in creator publications for digital creators
        if target_cat != "creator":
            direct_niche = direct_niche + cls.NICHE_DIRECT_FEEDS.get("creator", [])[:2]

        for src_name, feed_url in direct_niche:
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

                    seen_titles.add(norm_title)
                    articles.append({
                        "headline": title,
                        "summary": clean_summary[:350],
                        "source_name": src_name,
                        "source_url": entry.get("link", ""),
                        "image_url": image_url,
                        "published_date": entry.get("published", datetime.utcnow().strftime("%a, %d %b %Y")),
                        "region": "GLOBAL" if region == "GLOBAL" else region,
                        "category": cls._detect_category(title, clean_summary, niche)
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
        api_key: Optional[str] = None,
        region: str = "GLOBAL",
        category: Optional[str] = None
    ) -> List[NewsArticle]:
        """Fetch cached news or query live NewsAPI / multi-region RSS engine with strict niche and region relevancy."""
        now = datetime.utcnow()
        two_hours_ago = now - timedelta(hours=2)

        # Normalize region
        active_region = (region or "GLOBAL").upper()
        if active_region not in REGION_CONFIG and active_region != "ALL":
            active_region = "GLOBAL"

        # Check cache if not forcing refresh
        if not force_refresh:
            query = (
                db.query(NewsArticle)
                .filter(
                    NewsArticle.niche == niche,
                    NewsArticle.sub_niche == sub_niche,
                    NewsArticle.fetched_at >= two_hours_ago,
                    NewsArticle.source_name != "Industry Wire",
                    ~NewsArticle.headline.like("%Major Breakthrough Unveiled%")
                )
            )
            if active_region != "ALL":
                query = query.filter(NewsArticle.region == active_region)
            if category and category != "all":
                query = query.filter(NewsArticle.category == category)

            cached = query.order_by(NewsArticle.id.desc()).limit(25).all()
            valid_cached = [
                a for a in cached
                if cls.is_relevant_article(a.headline, a.summary, niche, sub_niche, active_region)
            ]
            if len(valid_cached) >= 6:
                return valid_cached

        # Purge stale or irrelevant articles for this niche and region when refreshing
        try:
            purge_query = db.query(NewsArticle).filter(
                NewsArticle.niche == niche,
                NewsArticle.sub_niche == sub_niche
            )
            if active_region != "ALL":
                purge_query = purge_query.filter(NewsArticle.region == active_region)

            old_arts = purge_query.all()
            deleted_count = 0
            for oa in old_arts:
                if not cls.is_relevant_article(oa.headline, oa.summary, niche, sub_niche, active_region) or force_refresh:
                    db.delete(oa)
                    deleted_count += 1
            if deleted_count > 0:
                db.commit()
                print(f"[NewsService] Purged {deleted_count} stale/irrelevant articles for niche '{niche}' region '{active_region}'.")
        except Exception as e:
            db.rollback()
            print(f"[NewsService] Cache purge warning: {e}")

        # Build prioritized query candidates
        candidates = cls.get_query_candidates(niche, sub_niche, keywords, region=active_region)
        active_news_key = api_key or getattr(settings, "NEWS_API_KEY", "")

        fresh_items: List[Dict[str, Any]] = []

        # 1. Query specialized News APIs if key provided
        if active_news_key and active_news_key.strip():
            fresh_items = await cls.fetch_specialized_news_api(
                candidates=candidates,
                api_key=active_news_key,
                limit=20,
                niche=niche,
                sub_niche=sub_niche,
                region=active_region
            )

        # 2. Blend with Google News RSS & regional/niche publication feeds
        if len(fresh_items) < 18:
            rss_items = await cls.fetch_news_rss(
                candidates,
                limit=25,
                niche=niche,
                sub_niche=sub_niche,
                region=active_region,
                category=category
            )
            for ri in rss_items:
                if not any(f["headline"].strip().lower() == ri["headline"].strip().lower() for f in fresh_items):
                    fresh_items.append(ri)
                if len(fresh_items) >= 25:
                    break

        # Save to DB
        created_records = []
        for item in fresh_items:
            art_cat = item.get("category") or cls._detect_category(item["headline"], item["summary"], niche)
            article = NewsArticle(
                niche=niche,
                sub_niche=sub_niche,
                region=item.get("region", active_region),
                category=art_cat,
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

        # Fallback to any recent matching items
        fallback_query = (
            db.query(NewsArticle)
            .filter(NewsArticle.niche == niche, NewsArticle.sub_niche == sub_niche)
        )
        if active_region != "ALL":
            fallback_query = fallback_query.filter(NewsArticle.region == active_region)
        fallback_existing = fallback_query.order_by(NewsArticle.id.desc()).limit(15).all()

        return fallback_existing

news_service = DailyNewsService()
