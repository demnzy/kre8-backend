from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, EmailStr

# Auth Schemas
class UserRegister(BaseModel):
    email: str
    password: str
    display_name: Optional[str] = "Creator"
    primary_niche: Optional[str] = "Technology"
    sub_niche: Optional[str] = "Artificial Intelligence & Agents"
    sub_niches: Optional[List[str]] = None
    search_keywords: Optional[str] = None
    target_audience: Optional[str] = None
    preferred_tone: Optional[str] = "Informative & Engaging"
    preferred_platforms: Optional[List[str]] = ["YouTube", "LinkedIn", "TikTok", "X"]
    weekly_post_goal: Optional[int] = 3

class UserLogin(BaseModel):
    email: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str
    user: Dict[str, Any]

# Preferences Schemas
class PreferencesUpdate(BaseModel):
    primary_niche: Optional[str] = None
    sub_niche: Optional[str] = None
    search_keywords: Optional[str] = None
    target_audience: Optional[str] = None
    preferred_tone: Optional[str] = None
    preferred_platforms: Optional[List[str]] = None
    weekly_post_goal: Optional[int] = None
    ai_provider: Optional[str] = "gemini"
    ai_model: Optional[str] = "gemini-2.5-flash"
    gemini_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    groq_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    deepseek_api_key: Optional[str] = None
    news_api_key: Optional[str] = None
    youtube_client_id: Optional[str] = None
    youtube_client_secret: Optional[str] = None
    linkedin_client_id: Optional[str] = None
    linkedin_client_secret: Optional[str] = None
    tiktok_client_key: Optional[str] = None
    tiktok_client_secret: Optional[str] = None
    meta_app_id: Optional[str] = None
    meta_app_secret: Optional[str] = None

class PreferencesOut(BaseModel):
    id: int
    primary_niche: str
    sub_niche: str
    search_keywords: Optional[str]
    target_audience: Optional[str]
    preferred_tone: Optional[str]
    preferred_platforms: List[str]
    weekly_post_goal: int
    ai_provider: Optional[str] = "gemini"
    ai_model: Optional[str] = "gemini-2.5-flash"
    gemini_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    groq_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    deepseek_api_key: Optional[str] = None
    news_api_key: Optional[str] = None
    youtube_client_id: Optional[str] = None
    linkedin_client_id: Optional[str] = None
    tiktok_client_key: Optional[str] = None
    meta_app_id: Optional[str] = None

    class Config:
        from_attributes = True

# News Schemas
class NewsAIIdeaOut(BaseModel):
    id: int
    topic_angle: str
    why_it_matters: Optional[str]
    recommended_format: str
    viral_hooks: List[str]
    talking_points: List[str]
    is_saved_to_ideas: bool

    class Config:
        from_attributes = True

class NewsArticleOut(BaseModel):
    id: int
    niche: str
    sub_niche: str
    headline: str
    summary: Optional[str]
    source_name: Optional[str]
    source_url: str
    image_url: Optional[str] = None
    published_date: Optional[str]
    ai_ideas: List[NewsAIIdeaOut] = []

    class Config:
        from_attributes = True

# Content Items
class ContentItemCreate(BaseModel):
    title: str
    description: Optional[str] = None
    category: Optional[str] = "Technology"
    platform: Optional[str] = "YouTube"
    format: Optional[str] = "Video"
    status: Optional[str] = "Idea"
    priority: Optional[str] = "Medium"
    planned_date: Optional[datetime] = None
    published_url: Optional[str] = None

class ContentItemUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    platform: Optional[str] = None
    format: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    planned_date: Optional[datetime] = None
    published_url: Optional[str] = None

class ContentItemOut(BaseModel):
    id: int
    title: str
    description: Optional[str]
    category: str
    platform: str
    format: str
    status: str
    priority: str
    planned_date: Optional[datetime]
    published_url: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# Ideas
class ContentIdeaCreate(BaseModel):
    title: str
    description: Optional[str] = None
    category: Optional[str] = "Tech"
    intended_platform: Optional[str] = "YouTube"
    source_inspiration: Optional[str] = None
    priority: Optional[str] = "Medium"
    tags: Optional[List[str]] = []
    status: Optional[str] = "Active"
    is_favorite: Optional[bool] = False
    notes: Optional[str] = None

class ContentIdeaUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    intended_platform: Optional[str] = None
    priority: Optional[str] = None
    tags: Optional[List[str]] = None
    status: Optional[str] = None
    is_favorite: Optional[bool] = None
    notes: Optional[str] = None

class ContentIdeaOut(BaseModel):
    id: int
    title: str
    description: Optional[str]
    category: str
    intended_platform: str
    source_inspiration: Optional[str]
    priority: str
    tags: List[str]
    status: str
    is_favorite: bool
    notes: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True

# Script & Clips
class ScriptClipCreate(BaseModel):
    clip_number: int
    spoken_dialogue: Optional[str] = ""
    estimated_duration: Optional[int] = 5
    on_screen_text: Optional[str] = ""
    visual_direction: Optional[str] = ""
    transition: Optional[str] = "Cut"
    cta: Optional[str] = None

class ScriptClipOut(BaseModel):
    id: int
    clip_number: int
    spoken_dialogue: Optional[str]
    estimated_duration: int
    on_screen_text: Optional[str]
    visual_direction: Optional[str]
    transition: str
    cta: Optional[str]

    class Config:
        from_attributes = True

class ScriptCreate(BaseModel):
    content_item_id: Optional[int] = None
    title: str
    tone: Optional[str] = "Conversational"
    target_duration_seconds: Optional[int] = 60
    full_script: Optional[str] = ""
    generated_hooks: Optional[List[str]] = []
    generated_ctas: Optional[List[str]] = []
    clips: Optional[List[ScriptClipCreate]] = []
    versions: Optional[List[Dict[str, Any]]] = []

class ScriptUpdate(BaseModel):
    title: Optional[str] = None
    tone: Optional[str] = None
    target_duration_seconds: Optional[int] = None
    full_script: Optional[str] = None
    generated_hooks: Optional[List[str]] = None
    generated_ctas: Optional[List[str]] = None
    clips: Optional[List[ScriptClipCreate]] = None
    versions: Optional[List[Dict[str, Any]]] = None

class ScriptOut(BaseModel):
    id: int
    content_item_id: Optional[int]
    title: str
    tone: str
    target_duration_seconds: int
    full_script: Optional[str]
    generated_hooks: List[str]
    generated_ctas: List[str]
    clips: List[ScriptClipOut] = []
    versions: Optional[List[Dict[str, Any]]] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# Tasks
class TaskChecklistItem(BaseModel):
    text: str
    done: bool

class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    content_item_id: Optional[int] = None
    due_date: Optional[datetime] = None
    priority: Optional[str] = "Medium"
    is_completed: Optional[bool] = False
    checklist: Optional[List[TaskChecklistItem]] = []

class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    content_item_id: Optional[int] = None
    due_date: Optional[datetime] = None
    priority: Optional[str] = None
    is_completed: Optional[bool] = None
    checklist: Optional[List[TaskChecklistItem]] = None

class TaskOut(BaseModel):
    id: int
    title: str
    description: Optional[str]
    content_item_id: Optional[int]
    due_date: Optional[datetime]
    priority: str
    is_completed: bool
    checklist: List[Dict[str, Any]]
    created_at: datetime

    class Config:
        from_attributes = True

# Notes
class NoteCreate(BaseModel):
    title: str
    content: Optional[str] = ""
    folder: Optional[str] = "General"
    tags: Optional[List[str]] = []
    is_pinned: Optional[bool] = False
    linked_type: Optional[str] = None
    linked_id: Optional[int] = None

class NoteUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    folder: Optional[str] = None
    tags: Optional[List[str]] = None
    is_pinned: Optional[bool] = None

class NoteOut(BaseModel):
    id: int
    title: str
    content: str
    folder: str
    tags: List[str]
    is_pinned: bool
    linked_type: Optional[str]
    linked_id: Optional[int]
    updated_at: datetime

    class Config:
        from_attributes = True

# Calendar Events
class CalendarEventCreate(BaseModel):
    title: str
    start_time: datetime
    end_time: Optional[datetime] = None
    content_item_id: Optional[int] = None
    event_type: Optional[str] = "Planned"
    platform: Optional[str] = "YouTube"
    reminder_minutes_before: Optional[int] = 30
    notes: Optional[str] = None

class CalendarEventUpdate(BaseModel):
    title: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    content_item_id: Optional[int] = None
    event_type: Optional[str] = None
    platform: Optional[str] = None
    reminder_minutes_before: Optional[int] = None
    notes: Optional[str] = None

class CalendarEventOut(BaseModel):
    id: int
    title: str
    start_time: datetime
    end_time: Optional[datetime]
    content_item_id: Optional[int]
    event_type: str
    platform: str
    notes: Optional[str]

    class Config:
        from_attributes = True

# Goals
class GoalCreate(BaseModel):
    title: str
    goal_type: str
    target_value: float
    current_value: Optional[float] = 0.0
    unit: Optional[str] = "posts"
    deadline: Optional[datetime] = None

class GoalUpdate(BaseModel):
    title: Optional[str] = None
    goal_type: Optional[str] = None
    target_value: Optional[float] = None
    current_value: Optional[float] = None
    unit: Optional[str] = None
    deadline: Optional[datetime] = None
    is_achieved: Optional[bool] = None

class GoalOut(BaseModel):
    id: int
    title: str
    goal_type: str
    target_value: float
    current_value: float
    unit: str
    deadline: Optional[datetime]
    is_achieved: bool

    class Config:
        from_attributes = True

# Creator Watchlist
class CreatorWatchlistCreate(BaseModel):
    creator_name: str
    handle: str
    platform: Optional[str] = "YouTube"
    profile_url: Optional[str] = None
    topic_niche: Optional[str] = None
    avatar_url: Optional[str] = None
    subscriber_count_text: Optional[str] = None
    pacing_style: Optional[str] = None
    signature_hooks: Optional[List[str]] = []
    personal_notes: Optional[str] = None
    original_angles: Optional[str] = None

class CreatorWatchlistUpdate(BaseModel):
    creator_name: Optional[str] = None
    handle: Optional[str] = None
    platform: Optional[str] = None
    profile_url: Optional[str] = None
    topic_niche: Optional[str] = None
    avatar_url: Optional[str] = None
    subscriber_count_text: Optional[str] = None
    pacing_style: Optional[str] = None
    signature_hooks: Optional[List[str]] = None
    personal_notes: Optional[str] = None
    original_angles: Optional[str] = None

class CreatorWatchlistOut(BaseModel):
    id: int
    creator_name: str
    handle: str
    platform: str
    profile_url: Optional[str] = None
    topic_niche: Optional[str] = None
    avatar_url: Optional[str] = None
    subscriber_count_text: Optional[str] = None
    pacing_style: Optional[str] = None
    signature_hooks: Optional[List[str]] = []
    personal_notes: Optional[str] = None
    original_angles: Optional[str] = None

    class Config:
        from_attributes = True

class CreatorInspectRequest(BaseModel):
    url_or_handle: str
    platform: Optional[str] = None

class CreatorInspectResponse(BaseModel):
    success: bool
    creator_name: str
    handle: str
    platform: str
    profile_url: str
    avatar_url: Optional[str] = None
    subscriber_count_text: Optional[str] = None
    topic_niche: str
    personal_notes: str
    original_angles: str
    pacing_style: str
    signature_hooks: List[str] = []
    recent_titles: List[str] = []
    error: Optional[str] = None

# AI Action Schemas
class IdeasSynthesizeRequest(BaseModel):
    source_type: str = "news"  # 'news', 'watchlist', 'hybrid', 'topic'
    news_article_id: Optional[int] = None
    creator_watchlist_id: Optional[int] = None
    topic_prompt: Optional[str] = None
    count: Optional[int] = 3

class AIScriptGenRequest(BaseModel):
    topic: str
    niche: Optional[str] = None
    platform: Optional[str] = "YouTube"
    format: Optional[str] = "Short Video"
    tone: Optional[str] = "Engaging & Direct"
    target_duration_seconds: Optional[int] = 60
    custom_instructions: Optional[str] = None
    creator_watchlist_id: Optional[int] = None
    creator_style: Optional[Dict[str, Any]] = None

class AIClipsBreakdownRequest(BaseModel):
    script_text: str
    target_duration: Optional[int] = 60

class AINoteExtractRequest(BaseModel):
    note_content: str

class AIPerformanceReviewRequest(BaseModel):
    timeframe: Optional[str] = "Last 30 Days"

class AIReviseScriptRequest(BaseModel):
    script_id: Optional[int] = None
    current_script: Optional[str] = None
    full_script: Optional[str] = None
    current_clips: Optional[List[Dict[str, Any]]] = None
    clips: Optional[List[Dict[str, Any]]] = None
    instruction: str
    conversation_history: Optional[List[Dict[str, str]]] = []
    target_duration_seconds: Optional[int] = 60
    tone: Optional[str] = "Conversational"

    @property
    def effective_script(self) -> str:
        return self.current_script or self.full_script or ""

    @property
    def effective_clips(self) -> List[Dict[str, Any]]:
        return self.current_clips or self.clips or []

class AIReviseScriptResponse(BaseModel):
    revised_script: str
    revised_clips: List[Dict[str, Any]]
    summary_of_changes: str
    assistant_message: str
    version_number: int
    used_provider: str
    used_model: str
    versions: Optional[List[Dict[str, Any]]] = []

class AITestConnectionRequest(BaseModel):
    provider: Optional[str] = "gemini"
    model: Optional[str] = None
    api_key: Optional[str] = None

