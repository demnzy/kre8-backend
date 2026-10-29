from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, Float, ForeignKey, JSON
)
from sqlalchemy.orm import relationship
from app.core.database import Base

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    display_name = Column(String(100), default="Creator")
    avatar_url = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    preferences = relationship("UserPreferences", back_populates="user", uselist=False)
    content_items = relationship("ContentItem", back_populates="user")
    ideas = relationship("ContentIdea", back_populates="user")
    scripts = relationship("Script", back_populates="user")
    tasks = relationship("Task", back_populates="user")
    notes = relationship("Note", back_populates="user")
    goals = relationship("Goal", back_populates="user")
    social_accounts = relationship("SocialAccount", back_populates="user")
    watchlist = relationship("CreatorWatchlist", back_populates="user")

class UserPreferences(Base):
    __tablename__ = "user_preferences"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    
    primary_niche = Column(String(100), default="Technology")
    sub_niche = Column(String(100), default="Artificial Intelligence & Agents")
    search_keywords = Column(Text, default="AI, LLM, autonomous agents, coding, tech news")
    target_audience = Column(Text, default="Developers, tech enthusiasts, and digital creators")
    preferred_tone = Column(String(50), default="Informative & Engaging")
    preferred_platforms = Column(JSON, default=lambda: ["YouTube", "LinkedIn", "TikTok", "X"])
    weekly_post_goal = Column(Integer, default=3)
    
    # Multi-Provider AI Engine & Custom Keys (BYOK)
    ai_provider = Column(String(50), default="gemini") # gemini, openai, anthropic, groq, openrouter, deepseek
    ai_model = Column(String(100), default="gemini-2.5-flash")
    gemini_api_key = Column(String(255), nullable=True)
    openai_api_key = Column(String(255), nullable=True)
    anthropic_api_key = Column(String(255), nullable=True)
    groq_api_key = Column(String(255), nullable=True)
    openrouter_api_key = Column(String(255), nullable=True)
    deepseek_api_key = Column(String(255), nullable=True)
    news_api_key = Column(String(255), nullable=True)
    news_region = Column(String(50), default="GLOBAL")
    
    # OAuth client IDs & secrets for social platforms
    youtube_client_id = Column(String(255), nullable=True)
    youtube_client_secret = Column(String(255), nullable=True)
    twitter_client_id = Column(String(255), nullable=True)
    twitter_client_secret = Column(String(255), nullable=True)
    linkedin_client_id = Column(String(255), nullable=True)
    linkedin_client_secret = Column(String(255), nullable=True)
    tiktok_client_key = Column(String(255), nullable=True)
    tiktok_client_secret = Column(String(255), nullable=True)
    meta_app_id = Column(String(255), nullable=True)
    meta_app_secret = Column(String(255), nullable=True)
    
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user = relationship("User", back_populates="preferences")

class NewsArticle(Base):
    __tablename__ = "news_articles"
    
    id = Column(Integer, primary_key=True, index=True)
    niche = Column(String(100), index=True)
    sub_niche = Column(String(100), index=True)
    region = Column(String(50), default="GLOBAL", index=True)
    category = Column(String(50), default="general", index=True)
    headline = Column(String(500), nullable=False)
    summary = Column(Text, nullable=True)
    source_name = Column(String(150), nullable=True)
    source_url = Column(String(1000), nullable=False)
    image_url = Column(String(1000), nullable=True)
    published_date = Column(String(100), nullable=True)
    fetched_at = Column(DateTime, default=datetime.utcnow)
    
    ai_ideas = relationship("NewsAIIdea", back_populates="news_article", cascade="all, delete-orphan")

class NewsAIIdea(Base):
    __tablename__ = "news_ai_ideas"
    
    id = Column(Integer, primary_key=True, index=True)
    news_article_id = Column(Integer, ForeignKey("news_articles.id"), nullable=False)
    topic_angle = Column(String(500), nullable=False)
    why_it_matters = Column(Text, nullable=True)
    recommended_format = Column(String(50), default="Short Video")
    viral_hooks = Column(JSON, default=list)
    talking_points = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_saved_to_ideas = Column(Boolean, default=False)
    
    news_article = relationship("NewsArticle", back_populates="ai_ideas")

class ContentItem(Base):
    __tablename__ = "content_items"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(100), default="Technology")
    platform = Column(String(50), default="YouTube") # YouTube, TikTok, LinkedIn, Instagram, X
    format = Column(String(50), default="Video") # Video, Short/Reel, Carousel, Article, Thread
    status = Column(String(50), default="Idea") 
    # Workflow statuses: Idea, Researching, Script Writing, Ready to Record, Recorded, Editing, Ready to Publish, Scheduled, Published, Repurposed
    priority = Column(String(20), default="Medium") # Low, Medium, High, Urgent
    planned_date = Column(DateTime, nullable=True)
    published_url = Column(String(1000), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = relationship("User", back_populates="content_items")
    scripts = relationship("Script", back_populates="content_item")
    tasks = relationship("Task", back_populates="content_item")

class ContentIdea(Base):
    __tablename__ = "content_ideas"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(100), default="Tech")
    intended_platform = Column(String(50), default="YouTube")
    source_inspiration = Column(String(500), nullable=True)
    priority = Column(String(20), default="Medium")
    tags = Column(JSON, default=list)
    status = Column(String(30), default="Active") # Draft, Active, Converted, Archived
    is_favorite = Column(Boolean, default=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="ideas")

class Script(Base):
    __tablename__ = "scripts"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    content_item_id = Column(Integer, ForeignKey("content_items.id"), nullable=True)
    title = Column(String(255), nullable=False)
    tone = Column(String(50), default="Conversational")
    target_duration_seconds = Column(Integer, default=60)
    full_script = Column(Text, nullable=True)
    generated_hooks = Column(JSON, default=list)
    generated_ctas = Column(JSON, default=list)
    versions = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = relationship("User", back_populates="scripts")
    content_item = relationship("ContentItem", back_populates="scripts")
    clips = relationship("ScriptClip", back_populates="script", cascade="all, delete-orphan", order_by="ScriptClip.clip_number")

class ScriptClip(Base):
    __tablename__ = "script_clips"
    
    id = Column(Integer, primary_key=True, index=True)
    script_id = Column(Integer, ForeignKey("scripts.id"), nullable=False)
    clip_number = Column(Integer, nullable=False)
    spoken_dialogue = Column(Text, nullable=True)
    estimated_duration = Column(Integer, default=5) # seconds
    on_screen_text = Column(String(500), nullable=True)
    visual_direction = Column(Text, nullable=True)
    transition = Column(String(100), default="Cut")
    cta = Column(String(255), nullable=True)
    
    script = relationship("Script", back_populates="clips")

class CalendarEvent(Base):
    __tablename__ = "calendar_events"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    content_item_id = Column(Integer, ForeignKey("content_items.id"), nullable=True)
    title = Column(String(255), nullable=False)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=True)
    event_type = Column(String(50), default="Planned") # Planned, Scheduled, Published
    platform = Column(String(50), default="YouTube")
    reminder_minutes_before = Column(Integer, default=30)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Task(Base):
    __tablename__ = "tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    content_item_id = Column(Integer, ForeignKey("content_items.id"), nullable=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    due_date = Column(DateTime, nullable=True)
    priority = Column(String(20), default="Medium") # Low, Medium, High, Urgent
    is_completed = Column(Boolean, default=False)
    checklist = Column(JSON, default=list) # [{ text: str, done: bool }]
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="tasks")
    content_item = relationship("ContentItem", back_populates="tasks")

class Note(Base):
    __tablename__ = "notes"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(255), nullable=False)
    content = Column(Text, default="")
    folder = Column(String(100), default="General")
    tags = Column(JSON, default=list)
    is_pinned = Column(Boolean, default=False)
    linked_type = Column(String(50), nullable=True) # content, script, idea
    linked_id = Column(Integer, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = relationship("User", back_populates="notes")

class Goal(Base):
    __tablename__ = "goals"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(255), nullable=False)
    goal_type = Column(String(50), default="Weekly Posts") # Weekly Posts, Scripts Written, Follower Milestone, Publishing Streak
    target_value = Column(Float, nullable=False)
    current_value = Column(Float, default=0.0)
    unit = Column(String(50), default="posts")
    deadline = Column(DateTime, nullable=True)
    is_achieved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="goals")

class SocialAccount(Base):
    __tablename__ = "social_accounts"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    platform = Column(String(50), nullable=False) # youtube, linkedin, tiktok, instagram, x
    account_name = Column(String(150), nullable=False)
    account_id = Column(String(255), nullable=True)
    avatar_url = Column(String(500), nullable=True)
    channel_id = Column(String(255), nullable=True)
    custom_url = Column(String(500), nullable=True)
    total_videos_count = Column(Integer, default=0)
    raw_details = Column(JSON, default=dict)
    access_token = Column(Text, nullable=True)
    refresh_token = Column(Text, nullable=True)
    token_expires_at = Column(DateTime, nullable=True)
    is_connected = Column(Boolean, default=True)
    last_synced_at = Column(DateTime, nullable=True)
    
    user = relationship("User", back_populates="social_accounts")
    snapshots = relationship("AnalyticsSnapshot", back_populates="account", cascade="all, delete-orphan")

class AnalyticsSnapshot(Base):
    __tablename__ = "analytics_snapshots"
    
    id = Column(Integer, primary_key=True, index=True)
    social_account_id = Column(Integer, ForeignKey("social_accounts.id"), nullable=False)
    date = Column(DateTime, default=datetime.utcnow)
    followers = Column(Integer, default=0)
    views = Column(Integer, default=0)
    impressions = Column(Integer, default=0)
    likes = Column(Integer, default=0)
    comments = Column(Integer, default=0)
    shares = Column(Integer, default=0)
    engagement_rate = Column(Float, default=0.0)
    raw_data = Column(JSON, default=dict)
    
    account = relationship("SocialAccount", back_populates="snapshots")

class PublishedPost(Base):
    __tablename__ = "published_posts"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    platform = Column(String(50), nullable=False)
    post_id = Column(String(255), nullable=True)
    title = Column(String(255), nullable=False)
    published_url = Column(String(1000), nullable=True)
    published_date = Column(DateTime, default=datetime.utcnow)
    views = Column(Integer, default=0)
    likes = Column(Integer, default=0)
    comments = Column(Integer, default=0)
    shares = Column(Integer, default=0)
    lessons_learned = Column(Text, nullable=True)

class CreatorWatchlist(Base):
    __tablename__ = "creator_watchlist"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    creator_name = Column(String(150), nullable=False)
    handle = Column(String(150), nullable=False)
    platform = Column(String(50), default="YouTube")
    profile_url = Column(String(1000), nullable=True)
    topic_niche = Column(String(150), nullable=True)
    avatar_url = Column(String(1000), nullable=True)
    subscriber_count_text = Column(String(50), nullable=True)
    pacing_style = Column(String(200), nullable=True)
    signature_hooks = Column(JSON, default=list)
    personal_notes = Column(Text, nullable=True)
    original_angles = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="watchlist")
