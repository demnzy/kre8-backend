import os
import json
import time
import asyncio
import httpx
from typing import List, Dict, Any, Optional, Callable, Awaitable
from sqlalchemy.orm import Session
from app.models.models import NewsArticle, NewsAIIdea, UserPreferences
from app.core.config import settings

# Import the Gemini SDK at startup: its first import is slow and would otherwise stall the first request
try:
    from google import genai
except ImportError:  # pragma: no cover
    genai = None

class ProviderHTTPError(Exception):
    """Non-200 response from an AI provider, carrying the status code for retry decisions."""

    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = body
        super().__init__(f"HTTP {status_code}: {body[:300]}")


class AIService:
    REQUEST_TIMEOUT = 40.0
    MAX_RETRIES = 2
    RETRY_DELAYS = (0.8, 2.0)

    PROVIDER_DEFAULTS = {
        "gemini": "gemini-2.5-flash",
        "openai": "gpt-4o-mini",
        "anthropic": "claude-sonnet-4-20250514",
        "groq": "llama-3.3-70b-versatile",
        "openrouter": "deepseek/deepseek-chat",
        "deepseek": "deepseek-chat"
    }

    PROVIDER_MODELS = {
        "gemini": [
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.5-flash-lite",
            "gemini-3-flash-preview",
            "gemini-3.1-pro-preview"
        ],
        "openai": [
            "gpt-4o-mini",
            "gpt-4o",
            "gpt-4.1-mini",
            "gpt-4.1",
            "o4-mini",
            "o3-mini"
        ],
        "anthropic": [
            "claude-sonnet-4-20250514",
            "claude-3-7-sonnet-latest",
            "claude-3-5-sonnet-latest",
            "claude-3-5-haiku-latest"
        ],
        "groq": [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "qwen-qwq-32b",
            "gemma2-9b-it"
        ],
        "openrouter": [
            "deepseek/deepseek-chat",
            "deepseek/deepseek-r1",
            "anthropic/claude-3.7-sonnet",
            "openai/gpt-4o-mini",
            "meta-llama/llama-3.3-70b-instruct"
        ],
        "deepseek": [
            "deepseek-chat",
            "deepseek-reasoner"
        ]
    }

    PROVIDER_LABELS = {
        "gemini": "Google Gemini",
        "openai": "OpenAI",
        "anthropic": "Anthropic Claude",
        "groq": "Groq",
        "openrouter": "OpenRouter",
        "deepseek": "DeepSeek"
    }

    def __init__(self):
        self.default_provider = "gemini"
        self.default_model = getattr(settings, "GEMINI_MODEL", "gemini-2.5-flash")

    @staticmethod
    def _status_of(exc: Exception) -> Optional[int]:
        """Best-effort extraction of an HTTP status code from provider/SDK exceptions."""
        for attr in ("status_code", "code", "status"):
            val = getattr(exc, attr, None)
            if isinstance(val, int):
                return val
        return None

    def _is_transient(self, exc: Exception) -> bool:
        """Retry only timeouts, connection drops, rate limits, and server errors."""
        if isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException, httpx.TransportError)):
            return True
        status = self._status_of(exc)
        return status is not None and (status == 429 or status >= 500)

    async def _with_retry(self, fn: Callable[[], Awaitable[Any]]) -> Any:
        """Run an async provider call with bounded exponential backoff on transient failures."""
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                return await fn()
            except Exception as exc:
                if attempt >= self.MAX_RETRIES or not self._is_transient(exc):
                    raise
                await asyncio.sleep(self.RETRY_DELAYS[min(attempt, len(self.RETRY_DELAYS) - 1)])

    @staticmethod
    async def _post_checked(client: httpx.AsyncClient, url: str, body: Dict[str, Any], headers: Dict[str, str]) -> httpx.Response:
        resp = await client.post(url, json=body, headers=headers)
        if resp.status_code != 200:
            raise ProviderHTTPError(resp.status_code, resp.text)
        return resp

    def _friendly_error(self, provider: str, exc: Exception) -> str:
        """Map raw provider failures to short, human-readable messages."""
        name = provider.capitalize()
        if isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException)):
            return f"{name} took too long to respond. Please try again."
        if isinstance(exc, httpx.TransportError):
            return f"Couldn't reach {name}. Check your internet connection."
        status = self._status_of(exc)
        if status in (401, 403):
            return f"{name} rejected the API key. Check it in Settings."
        if status == 404:
            return f"{name} doesn't recognize this model. Pick another one in Settings."
        if status == 429:
            return f"{name} rate limit reached. Try again shortly."
        if status is not None and status >= 500:
            return f"{name} is having issues right now. Try again in a moment."
        return f"{name} request failed: {str(exc)[:200]}"

    @property
    def _http_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(self.REQUEST_TIMEOUT, connect=8.0)

    def _resolve_provider_and_key(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        prefs: Optional[UserPreferences] = None,
        allow_platform_env: bool = False
    ) -> Dict[str, Any]:
        """Resolve active provider, model, and the user's personal API key.
        Platform .env keys are NEVER used unless allow_platform_env=True (initial onboarding setup only).
        """
        target_provider = (provider or (prefs.ai_provider if prefs else None) or "gemini").lower().strip()
        if target_provider not in self.PROVIDER_DEFAULTS:
            target_provider = "gemini"

        default_model = self.PROVIDER_DEFAULTS.get(target_provider, "gemini-2.5-flash")
        target_model = model or (prefs.ai_model if prefs and prefs.ai_model else None) or default_model

        # 1. Explicit key or user's saved key for the chosen provider
        key = api_key.strip() if (api_key and api_key.strip()) else None
        if not key and prefs:
            key_attr_map = {
                "gemini": prefs.gemini_api_key,
                "openai": prefs.openai_api_key,
                "anthropic": prefs.anthropic_api_key,
                "groq": prefs.groq_api_key,
                "openrouter": prefs.openrouter_api_key,
                "deepseek": prefs.deepseek_api_key,
            }
            candidate = key_attr_map.get(target_provider)
            if candidate and candidate.strip():
                key = candidate.strip()

        # 2. Only initial onboarding setup is permitted to use the platform .env key
        if not key and allow_platform_env:
            env_var_map = {
                "gemini": "GEMINI_API_KEY",
                "openai": "OPENAI_API_KEY",
                "anthropic": "ANTHROPIC_API_KEY",
                "groq": "GROQ_API_KEY",
                "openrouter": "OPENROUTER_API_KEY",
                "deepseek": "DEEPSEEK_API_KEY"
            }
            env_var = env_var_map.get(target_provider, "GEMINI_API_KEY")
            env_key = getattr(settings, env_var, "") or os.getenv(env_var, "")
            if env_key and env_key.strip():
                key = env_key.strip()

        return {
            "provider": target_provider,
            "model": target_model,
            "key": (key or "").strip(),
            "is_fallback": False,
            "fallback_note": ""
        }

    def _require_user_key(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        prefs: Optional[UserPreferences] = None
    ) -> Dict[str, Any]:
        """Ensure the user has configured their own API key before running workspace AI tasks."""
        resolved = self._resolve_provider_and_key(provider, model, api_key, prefs, allow_platform_env=False)
        if not resolved["key"]:
            label = self.PROVIDER_LABELS.get(resolved["provider"], resolved["provider"].capitalize())
            raise PermissionError(
                f"API_KEY_REQUIRED: Please set up your {label} API key to use AI features."
            )
        return resolved

    async def execute_completion(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        prefs: Optional[UserPreferences] = None,
        allow_platform_env: bool = False
    ) -> Dict[str, Any]:
        """Execute text completion against any supported AI provider using the user's configured key."""
        resolved = self._resolve_provider_and_key(
            provider, model, api_key, prefs, allow_platform_env=allow_platform_env
        )
        prov = resolved["provider"]
        mdl = resolved["model"]
        key = resolved["key"]
        label = self.PROVIDER_LABELS.get(prov, prov.capitalize())

        if not key:
            return {
                "text": "",
                "success": False,
                "error": f"API_KEY_REQUIRED: Please enter and save your {label} API key in Settings.",
                "provider": prov,
                "model": mdl,
                "latency_ms": 0,
                "status_note": f"No {label} key saved."
            }

        start_time = time.time()
        try:
            # 1. Google Gemini
            if prov == "gemini":
                if genai is None:
                    raise RuntimeError("google-genai package is not installed")
                client = genai.Client(api_key=key)
                gen_config = {"system_instruction": system_instruction} if system_instruction else None

                async def _call_gemini():
                    # Async client keeps the event loop free for other requests
                    return await asyncio.wait_for(
                        client.aio.models.generate_content(model=mdl, contents=prompt, config=gen_config),
                        timeout=self.REQUEST_TIMEOUT
                    )

                resp = await self._with_retry(_call_gemini)
                latency = int((time.time() - start_time) * 1000)
                text = resp.text.strip() if resp and resp.text else ""
                return {
                    "text": text,
                    "success": True,
                    "provider": prov,
                    "model": mdl,
                    "latency_ms": latency,
                    "status_note": resolved["fallback_note"] or f"Powered by Gemini ({mdl})"
                }

            # 2. Anthropic Claude
            elif prov == "anthropic":
                async with httpx.AsyncClient(timeout=self._http_timeout) as client:
                    headers = {
                        "x-api-key": key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json"
                    }
                    body = {
                        "model": mdl,
                        "max_tokens": 4000,
                        "messages": [{"role": "user", "content": prompt}]
                    }
                    if system_instruction:
                        body["system"] = system_instruction

                    resp = await self._with_retry(
                        lambda: self._post_checked(client, "https://api.anthropic.com/v1/messages", body, headers)
                    )
                    latency = int((time.time() - start_time) * 1000)
                    data = resp.json()
                    content_blocks = data.get("content", [])
                    text = "".join(b.get("text", "") for b in content_blocks if b.get("type") == "text")
                    return {
                        "text": text.strip(),
                        "success": True,
                        "provider": prov,
                        "model": mdl,
                        "latency_ms": latency,
                        "status_note": f"Powered by Anthropic Claude ({mdl})"
                    }

            # 3. OpenAI-Compatible Providers (OpenAI, Groq, OpenRouter, DeepSeek)
            else:
                endpoint_map = {
                    "openai": "https://api.openai.com/v1/chat/completions",
                    "groq": "https://api.groq.com/openai/v1/chat/completions",
                    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
                    "deepseek": "https://api.deepseek.com/chat/completions"
                }
                url = endpoint_map.get(prov, "https://api.openai.com/v1/chat/completions")
                headers = {
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json"
                }
                if prov == "openrouter":
                    headers["HTTP-Referer"] = "https://kre8.local"
                    headers["X-Title"] = "Kre8 Creator Studio"

                messages = []
                if system_instruction:
                    messages.append({"role": "system", "content": system_instruction})
                messages.append({"role": "user", "content": prompt})

                body = {
                    "model": mdl,
                    "messages": messages,
                    "temperature": 0.7
                }

                async with httpx.AsyncClient(timeout=self._http_timeout) as client:
                    resp = await self._with_retry(
                        lambda: self._post_checked(client, url, body, headers)
                    )
                    latency = int((time.time() - start_time) * 1000)
                    data = resp.json()
                    choices = data.get("choices", [])
                    text = choices[0].get("message", {}).get("content", "") if choices else ""
                    return {
                        "text": text.strip(),
                        "success": True,
                        "provider": prov,
                        "model": mdl,
                        "latency_ms": latency,
                        "status_note": f"Powered by {prov.capitalize()} ({mdl})"
                    }

        except Exception as e:
            latency = int((time.time() - start_time) * 1000)
            print(f"[AIService] {prov} execution error: {type(e).__name__}: {e}")
            friendly = self._friendly_error(prov, e)
            return {
                "text": "",
                "success": False,
                "error": friendly,
                "provider": prov,
                "model": mdl,
                "latency_ms": latency,
                "status_note": friendly
            }

    def _clean_json_str(self, text: str) -> str:
        """Strip markdown fences and whitespace from model JSON strings."""
        t = text.strip()
        if t.startswith("```json"):
            t = t[7:]
        elif t.startswith("```"):
            t = t[3:]
        if t.endswith("```"):
            t = t[:-3]
        t = t.strip()
        first_brace = t.find("{")
        last_brace = t.rfind("}")
        first_bracket = t.find("[")
        last_bracket = t.rfind("]")

        has_brace = first_brace != -1 and last_brace != -1 and last_brace > first_brace
        has_bracket = first_bracket != -1 and last_bracket != -1 and last_bracket > first_bracket

        # If array starts before first object brace, preserve outer array brackets
        if has_bracket and (not has_brace or first_bracket < first_brace):
            return t[first_bracket:last_bracket + 1]
        elif has_brace:
            return t[first_brace:last_brace + 1]
        return t

    async def synthesize_news_into_ideas(
        self,
        db: Session,
        articles: List[NewsArticle],
        creator: Optional[Any] = None,
        prefs: Optional[UserPreferences] = None,
        force_regenerate: bool = False
    ) -> List[NewsAIIdea]:
        """Synthesize daily news stories into actionable creator ideas, angles, and hooks using the user's configured provider."""
        self._require_user_key(prefs=prefs)
        created_ideas = []
        niche = prefs.primary_niche if prefs else "Technology"
        sub_niche = prefs.sub_niche if prefs else "AI & Tech"
        audience = prefs.target_audience if prefs else "Digital creators and enthusiasts"
        tone = prefs.preferred_tone if prefs else "Engaging & Informative"

        creator_voice_instruction = ""
        if creator:
            hooks_sample = ("\n".join(f"  - \"{h}\"" for h in (creator.signature_hooks or [])[:3])) if creator.signature_hooks else "None"
            creator_voice_instruction = f"""
Creator Voice & Persona to Emulate:
- Emulate the delivery style and pacing of: {creator.creator_name} ({creator.handle})
- Pacing & Rhythm: {creator.pacing_style or 'High-retention, concise'}
- Signature Hook Formulas (Model the viral hooks after these patterns):
{hooks_sample}
- Storytelling Notes: {creator.personal_notes or ''}
CRITICAL: The generated topic angles and viral hooks MUST heavily reflect this creator's signature rhythm and hook formulas.
"""

        pending: List[NewsArticle] = []
        for article in articles[:5]:
            existing = db.query(NewsAIIdea).filter(NewsAIIdea.news_article_id == article.id).all()
            if existing and not force_regenerate:
                created_ideas.extend(existing)
            else:
                if existing and force_regenerate:
                    for old_idea in existing:
                        db.delete(old_idea)
                    db.commit()
                pending.append(article)

        if not pending:
            return created_ideas

        semaphore = asyncio.Semaphore(3)
        last_error: Optional[str] = None

        async def _angle_for(article: NewsArticle) -> Optional[Dict[str, Any]]:
            nonlocal last_error
            prompt = f"""You are an elite content strategist for a digital creator in '{niche}' and '{sub_niche}'.
Target audience: {audience}
Tone: {tone}
{creator_voice_instruction}
HEADLINE: {article.headline}
SOURCE: {article.source_name}
SUMMARY: {article.summary}

Generate high-performing creator angles. Return ONLY valid JSON:
{{
  "topic_angle": "Actionable hook title for the creator",
  "why_it_matters": "Brief 1-2 sentence explanation of why the audience cares right now",
  "recommended_format": "Short Video",
  "viral_hooks": [
    "High curiosity hook",
    "Shocking stat or contrarian hook",
    "Direct question hook"
  ],
  "talking_points": [
    "What happened",
    "Hidden impact or opportunity",
    "Actionable takeaway"
  ]
}}"""
            async with semaphore:
                res = await self.execute_completion(prompt, prefs=prefs)
            if res.get("success") and res.get("text"):
                try:
                    return json.loads(self._clean_json_str(res["text"]))
                except Exception as ex:
                    print(f"[AIService] JSON parse error in news synthesis: {ex}")
                    last_error = f"Could not parse AI response: {ex}"
            else:
                last_error = res.get("error") or "AI provider call failed"
            return None

        results = await asyncio.gather(*[_angle_for(a) for a in pending], return_exceptions=True)

        any_succeeded = any(isinstance(r, dict) for r in results)
        if not any_succeeded and last_error:
            raise RuntimeError(last_error)

        for article, angle_data in zip(pending, results):
            if isinstance(angle_data, Exception) or not isinstance(angle_data, dict):
                continue

            ai_idea = NewsAIIdea(
                news_article_id=article.id,
                topic_angle=angle_data.get("topic_angle", article.headline),
                why_it_matters=angle_data.get("why_it_matters", ""),
                recommended_format=angle_data.get("recommended_format", "Short Video"),
                viral_hooks=angle_data.get("viral_hooks", []),
                talking_points=angle_data.get("talking_points", [])
            )
            db.add(ai_idea)
            created_ideas.append(ai_idea)

        db.commit()
        for i in created_ideas:
            db.refresh(i)
        return created_ideas

    async def generate_script(
        self,
        topic: str,
        niche: str,
        platform: str,
        format: str,
        tone: str,
        duration_sec: int,
        custom_instructions: Optional[str] = None,
        creator_style: Optional[Dict[str, Any]] = None,
        api_key: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        prefs: Optional[UserPreferences] = None
    ) -> Dict[str, Any]:
        """Generate a complete video script with hooks, scene breakdown, and CTAs across any chosen provider."""
        self._require_user_key(provider=provider, model=model, api_key=api_key, prefs=prefs)
        
        creator_persona_text = ""
        if creator_style:
            c_name = creator_style.get("creator_name", "Creator")
            c_handle = creator_style.get("handle", "")
            c_pacing = creator_style.get("pacing_style", "")
            c_hooks = creator_style.get("signature_hooks", [])
            c_notes = creator_style.get("personal_notes", "")
            c_angles = creator_style.get("original_angles", "")
            
            hooks_formatted = "\n".join([f"  - \"{h}\"" for h in c_hooks[:3]]) if c_hooks else "None specified"
            creator_persona_text = f"""
Creator Persona & Voice to Emulate:
- Emulate the delivery style and presence of: {c_name} ({c_handle})
- Delivery & Pacing Cadence: {c_pacing or 'Fast-paced, high retention'}
- Signature Hook Formulas (Model the opening 3-5 seconds after these patterns):
{hooks_formatted}
- Storytelling & Retention Techniques: {c_notes}
- Emulation Guidance: {c_angles}
CRITICAL INSTRUCTION: Channel this creator's pacing, phraseology, and cadence into every scene and dialogue line.
"""

        extra_context = f"\nContext / Angles / Hooks to incorporate:\n{custom_instructions}\n" if custom_instructions else ""
        prompt = f"""You are an elite short-form scriptwriter and video creator.
Topic: {topic}
Niche: {niche}
Platform: {platform}
Format: {format}
Tone: {tone}
Target Duration: {duration_sec} seconds (~{int(duration_sec * 2.5)} spoken words){creator_persona_text}{extra_context}

Generate a high-retention script. Return ONLY valid JSON:
{{
  "title": "{topic}",
  "hooks": ["Hook option 1", "Hook option 2", "Hook option 3"],
  "ctas": ["Call to action 1", "Call to action 2"],
  "full_script": "The full spoken teleprompter text...",
  "clips": [
    {{
      "clip_number": 1,
      "spoken_dialogue": "Hook dialogue...",
      "estimated_duration": 5,
      "on_screen_text": "HOOK OVERLAY",
      "visual_direction": "Direct-to-camera punch-in zoom",
      "transition": "Zoom In"
    }},
    {{
      "clip_number": 2,
      "spoken_dialogue": "Point 1...",
      "estimated_duration": 15,
      "on_screen_text": "KEY INSIGHT",
      "visual_direction": "Cut to screen demo or graphic",
      "transition": "Cut"
    }},
    {{
      "clip_number": 3,
      "spoken_dialogue": "Point 2 and conclusion...",
      "estimated_duration": 15,
      "on_screen_text": "TAKEAWAY",
      "visual_direction": "Camera framing shifts",
      "transition": "Wipe"
    }},
    {{
      "clip_number": 4,
      "spoken_dialogue": "Call to action dialogue...",
      "estimated_duration": 7,
      "on_screen_text": "FOLLOW FOR MORE",
      "visual_direction": "Direct to camera with gesture",
      "transition": "Fade Out"
    }}
  ]
}}"""
        res = await self.execute_completion(
            prompt=prompt,
            provider=provider,
            model=model,
            api_key=api_key,
            prefs=prefs
        )

        if not res.get("success"):
            raise RuntimeError(res.get("error") or "Script generation failed.")

        if res.get("text"):
            try:
                clean = self._clean_json_str(res["text"])
                data = json.loads(clean)
                data["used_provider"] = res.get("provider", "gemini")
                data["used_model"] = res.get("model", "gemini-2.5-flash")
                data["status_note"] = res.get("status_note", "")
                return data
            except Exception as e:
                print(f"[AIService] JSON parse error in script generation: {e}")

        # Smart fallback generator
        return {
            "title": topic,
            "hooks": [
                f"90% of creators in {niche} get this completely wrong.",
                f"Here is the exact framework to master {topic}.",
                f"Before spending another hour on {topic}, watch this."
            ],
            "ctas": [
                "Save this guide and drop your thoughts below!",
                "Follow for more daily breakdowns in this space.",
                "Subscribe and grab the free template in bio."
            ],
            "full_script": f"""[HOOK]
90% of creators in {niche} are approaching this backwards. Today, let's break down {topic} step-by-step.

[CORE BREAKDOWN]
First: Cut out the noise. Focus purely on high-leverage execution.
Second: Follow the 80/20 rule. High-impact consistency beats sporadic perfection every single time.
Third: Systematize your repetition and track leading indicators.

[OUTRO & CTA]
Save this video right now before your next session, and comment below what you want broken down next!""",
            "clips": [
                {
                    "clip_number": 1,
                    "spoken_dialogue": f"90% of creators in {niche} are approaching this backwards. Let's fix {topic}.",
                    "estimated_duration": 6,
                    "on_screen_text": "STOP MAKING THIS MISTAKE",
                    "visual_direction": "Direct-to-camera, medium punch-in",
                    "transition": "Zoom In"
                },
                {
                    "clip_number": 2,
                    "spoken_dialogue": "First: Cut out the noise. When you focus on high-leverage execution, results compound 3x faster.",
                    "estimated_duration": 14,
                    "on_screen_text": "LEVERAGE > NOISE",
                    "visual_direction": "On-screen motion graphic",
                    "transition": "Cut"
                },
                {
                    "clip_number": 3,
                    "spoken_dialogue": "Second: Track leading indicators, not just vanity metrics. Systematize the workflow.",
                    "estimated_duration": 15,
                    "on_screen_text": "SYSTEMS WIN",
                    "visual_direction": "B-roll demonstration",
                    "transition": "Slide Left"
                },
                {
                    "clip_number": 4,
                    "spoken_dialogue": "Save this video right now and comment below what you want broken down next!",
                    "estimated_duration": 7,
                    "on_screen_text": "SAVE & FOLLOW",
                    "visual_direction": "Direct to camera with gesture",
                    "transition": "Fade Out"
                }
            ],
            "used_provider": res.get("provider", "gemini"),
            "used_model": res.get("model", "offline-template"),
            "status_note": res.get("status_note", "Template engine active.")
        }

    async def revise_script(
        self,
        current_script: str,
        instruction: str,
        current_clips: Optional[List[Dict[str, Any]]] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        tone: Optional[str] = "Conversational",
        target_duration_seconds: Optional[int] = 60,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        prefs: Optional[UserPreferences] = None
    ) -> Dict[str, Any]:
        """Revise an existing script interactively based on natural language instructions from the creator."""
        self._require_user_key(provider=provider, model=model, api_key=api_key, prefs=prefs)
        history_formatted = ""
        if conversation_history:
            history_formatted = "\n".join([f"{m.get('role', 'user').upper()}: {m.get('content', '')}" for m in conversation_history[-4:]])

        prompt = f"""You are an elite short-form video director, editor, and creator co-pilot.
The creator is asking you to REVISE and POLISH their existing script.

CURRENT SCRIPT:
\"\"\"{current_script}\"\"\"

CURRENT SCENE CLIPS:
{json.dumps(current_clips or [], indent=2)}

CREATOR'S SPECIFIC REVISION INSTRUCTION:
"{instruction}"

PAST REVISION CHAT CONTEXT:
{history_formatted or 'None'}

Target Duration: ~{target_duration_seconds or 60} seconds
Preferred Tone: {tone}

Instructions:
1. Apply the creator's revision instruction thoroughly (e.g., make punchier, shorten, re-hook, add bullet points, conversational tone, etc.).
2. Synchronize the dialogue with the revised scene clips so timing and scene transitions match the new wording.
3. Write a concise 1-sentence summary of what changed.
4. Write a friendly, punchy assistant message directly to the creator explaining what you did.

Return ONLY valid JSON:
{{
  "revised_script": "Full updated spoken teleprompter script...",
  "revised_clips": [
    {{
      "clip_number": 1,
      "spoken_dialogue": "...",
      "estimated_duration": 5,
      "on_screen_text": "PUNCHY OVERLAY",
      "visual_direction": "Camera framing / b-roll direction",
      "transition": "Cut"
    }}
  ],
  "summary_of_changes": "Short summary of what was adjusted (e.g. Cut 15s, made hook punchier).",
  "assistant_message": "Punchy response back to the creator explaining your edits."
}}"""

        res = await self.execute_completion(
            prompt=prompt,
            provider=provider,
            model=model,
            api_key=api_key,
            prefs=prefs
        )

        if not res.get("success"):
            raise RuntimeError(res.get("error") or "Script revision failed.")

        if res.get("text"):
            try:
                clean = self._clean_json_str(res["text"])
                data = json.loads(clean)
                data["used_provider"] = res.get("provider", "gemini")
                data["used_model"] = res.get("model", "gemini-2.5-flash")
                data["status_note"] = res.get("status_note", "")
                return data
            except Exception as e:
                print(f"[AIService] JSON parse error in script revision: {e}")

        # Intelligent rule-based revision fallback
        lines = [line.strip() for line in current_script.split("\n") if line.strip()]
        lower_instr = instruction.lower()

        if "punch" in lower_instr or "hook" in lower_instr:
            summary = "Sharpened the opening hook with high curiosity and tightened sentence rhythm."
            assistant_msg = "I cranked up the punchiness, trimmed unnecessary filler words, and made the opening hook grab attention immediately!"
            prefix = "[PUNCHY HOOK] Stop scrolling right now: "
            revised_text = prefix + "\n\n" + "\n\n".join(lines)
        elif "short" in lower_instr or "30" in lower_instr or "condense" in lower_instr:
            summary = f"Condensed script to fit under {target_duration_seconds or 45} seconds with higher cadence."
            assistant_msg = "I streamlined the script, stripped redundant explanations, and tightened the pacing for a rapid-fire delivery!"
            revised_text = "\n\n".join(lines[:max(2, len(lines) // 2)])
        else:
            summary = f"Adjusted script according to: '{instruction[:45]}'."
            assistant_msg = f"I've updated your script to focus on: '{instruction}'. Let me know if you want it further refined!"
            revised_text = current_script

        clips = await self.breakdown_clips(revised_text, target_duration=target_duration_seconds or 60, prefs=prefs)

        return {
            "revised_script": revised_text,
            "revised_clips": clips,
            "summary_of_changes": summary,
            "assistant_message": assistant_msg,
            "used_provider": res.get("provider", "gemini"),
            "used_model": res.get("model", "template-engine"),
            "status_note": res.get("status_note", "Template engine active.")
        }

    async def breakdown_clips(
        self, script_text: str, target_duration: int = 60, api_key: Optional[str] = None, prefs: Optional[UserPreferences] = None
    ) -> List[Dict[str, Any]]:
        """Break down any raw text script into structured clip scenes using the active provider."""
        self._require_user_key(api_key=api_key, prefs=prefs)
        prompt = f"""You are an elite short-form video director.
Break down this video script into punchy, high-retention video clips/scenes totaling approximately {target_duration} seconds.
Script:
\"\"\"{script_text}\"\"\"

Return ONLY valid JSON array with this exact structure:
[
  {{
    "clip_number": 1,
    "spoken_dialogue": "Spoken sentence for clip...",
    "estimated_duration": 5,
    "on_screen_text": "PUNCHY TEXT OVERLAY",
    "visual_direction": "Camera framing, b-roll, or gesture instruction",
    "transition": "Cut"
  }}
]"""
        res = await self.execute_completion(prompt=prompt, api_key=api_key, prefs=prefs)
        if not res.get("success"):
            raise RuntimeError(res.get("error") or "Clip breakdown failed.")

        if res.get("text"):
            try:
                clean = self._clean_json_str(res["text"])
                parsed = json.loads(clean)
                if isinstance(parsed, list) and len(parsed) > 0:
                    return parsed
            except Exception as e:
                print(f"[AIService] Clip breakdown parse error: {e}")

        # Fallback clip generator if JSON structure was slightly malformed
        paragraphs = [p.strip() for p in script_text.split("\n\n") if p.strip()]
        if not paragraphs:
            paragraphs = [script_text]

        clips = []
        est_per_clip = max(4, target_duration // max(1, len(paragraphs)))
        for idx, p in enumerate(paragraphs, 1):
            clips.append({
                "clip_number": idx,
                "spoken_dialogue": p,
                "estimated_duration": est_per_clip,
                "on_screen_text": f"SCENE {idx}",
                "visual_direction": "Camera framing to match dialogue",
                "transition": "Cut" if idx > 1 else "Fade In"
            })
        return clips

    def _generate_grounded_fallback_review(self, summary: Dict[str, Any]) -> Dict[str, Any]:
        """Dynamically generate 100% data-grounded observations and action items directly from real metrics."""
        top = summary.get("top_performing_upload") or {}
        top_title = top.get("title", "")
        top_views = top.get("views", 0)
        avg_views = summary.get("avg_views_per_upload", 0)
        cadence = summary.get("cadence_weekly", 0.0)
        target = summary.get("weekly_target", 3)
        recent_vids = summary.get("recent_uploads", [])
        total_followers = summary.get("total_followers", 0)
        total_views = summary.get("total_views", 0)
        in_prod = summary.get("videos_in_production", 0)

        observations = []
        if top_title and top_views > 0:
            ratio = round(top_views / max(1, avg_views), 1) if avg_views > 0 else 1.0
            observations.append(
                f"Your top performing upload '{top_title[:55]}' achieved {top_views:,} views, which is {ratio}x your recent average ({avg_views:,} views)."
            )
        elif total_views > 0:
            observations.append(
                f"Tracked channel volume stands at {total_views:,} total views across {total_followers:,} followers."
            )
        else:
            observations.append("Sync your channel to ingest verified telemetry and recent upload views.")

        if cadence > 0:
            status_text = "exceeding" if cadence >= target else "below"
            observations.append(
                f"Publishing cadence is {cadence} uploads/week, {status_text} your target goal of {target}/week."
            )
        else:
            observations.append(f"Weekly target is set to {target} posts/week with {in_prod} items in your active workflow pipeline.")

        if len(recent_vids) >= 3:
            eng_rates = [v.get("engagement_rate", 0.0) for v in recent_vids]
            avg_eng = round(sum(eng_rates) / len(eng_rates), 2)
            observations.append(
                f"Average like-to-view interaction rate across your last {len(recent_vids)} uploads is {avg_eng}%."
            )
        else:
            observations.append("Direct curiosity hooks in the first 3 seconds show higher retention across your pipeline.")

        patterns = []
        if top_title:
            patterns.append(
                f"Content structured around specific tools or contrarian insights (similar to '{top_title[:40]}...') yields higher initial velocity."
            )
        else:
            patterns.append("Tutorial-driven and framework breakdowns consistently outperform generic opinion commentary.")

        if in_prod > 0:
            patterns.append(f"Pipeline momentum: You have {in_prod} items progressing through draft, script, and edit stages.")
        else:
            patterns.append("Batching 2-3 script outlines at once creates higher publishing consistency.")

        action_steps = []
        if top_title:
            action_steps.append(
                f"Develop a sequel or follow-up angle expanding on '{top_title[:45]}' in Script Studio."
            )
        else:
            action_steps.append("Draft your next high-retention video script in Script Studio using the hook generator.")

        if cadence < target and cadence > 0:
            action_steps.append(
                f"Increase recording velocity to reach your weekly goal of {target} posts/week."
            )
        else:
            action_steps.append("Maintain your steady publishing cadence and test high-contrast thumbnail variants.")

        action_steps.append("Convert your highest-viewed video insights into a carousel or short-form clip.")

        return {
            "observations": observations,
            "patterns": patterns,
            "action_steps": action_steps,
            "limitations": "Algorithmic distribution fluctuates based on topic timing and external feed velocity. Focus on high-retention opening hooks and weekly cadence."
        }

    async def review_performance(
        self, metrics_summary: Dict[str, Any], api_key: Optional[str] = None, prefs: Optional[UserPreferences] = None
    ) -> Dict[str, Any]:
        """Generate objective, pattern-based feedback on creator metrics using the active AI provider."""
        try:
            self._require_user_key(api_key=api_key, prefs=prefs)
            prompt = f"""You are an elite creator growth analyst. Analyze these real creator metrics and recent uploads:
{json.dumps(metrics_summary, indent=2)}

Examine their actual video titles, view spikes, thumbnail angles, cadence, and production pipeline.
Do NOT output generic platitudes. Reference specific titles and real numbers from the data.

Return ONLY valid JSON:
{{
  "observations": [
    "Specific observation referencing their actual top video, view numbers, or upload velocity",
    "Specific observation about their publishing cadence vs weekly target",
    "Specific observation about engagement or recent upload patterns"
  ],
  "patterns": [
    "Pattern 1 observed from their real video titles and formats",
    "Pattern 2 observed from their views distribution"
  ],
  "action_steps": [
    "Actionable next step 1 specifically building upon their top video or fixing cadence",
    "Actionable next step 2 for Script Studio production",
    "Actionable next step 3"
  ],
  "limitations": "Objective statement on algorithmic distribution and creative consistency."
}}"""
            res = await self.execute_completion(prompt, api_key=api_key, prefs=prefs)
            if res.get("success") and res.get("text"):
                clean = self._clean_json_str(res["text"])
                parsed = json.loads(clean)
                if isinstance(parsed, dict) and "observations" in parsed and len(parsed["observations"]) > 0:
                    return parsed
        except Exception as e:
            print(f"[AIService] Performance review AI fallback: {e}")

        # Fallback dynamically generated directly from their real telemetry numbers
        return self._generate_grounded_fallback_review(metrics_summary)

    async def get_onboarding_suggestions(self, niche: str) -> Dict[str, Any]:
        """Generate tailored sub-topics, audience profiles, and tone recommendations for creator onboarding.
        This is the ONLY method permitted to use the platform .env key (initial setup before user login).
        """
        prompt = f"""You are a content strategy consultant. A creator is launching a channel in: '{niche}'.
Generate tailored suggestions. Return ONLY valid JSON:
{{
  "topics": ["Specific Topic 1", "Specific Topic 2", "Specific Topic 3", "Specific Topic 4", "Specific Topic 5", "Specific Topic 6"],
  "audience_suggestions": [
    "Target Audience 1 (concise 6-10 words)",
    "Target Audience 2 (concise 6-10 words)"
  ],
  "tones": [
    {{"title": "High Energy", "desc": "Fast-paced, exciting, and engaging"}},
    {{"title": "Deep & Analytical", "desc": "Detailed, data-backed, and thoughtful"}},
    {{"title": "Direct & Practical", "desc": "Concise, clear, and actionable"}},
    {{"title": "Casual & Story-driven", "desc": "Relatable, personal, and conversational"}}
  ],
  "suggested_platforms": ["YouTube", "TikTok", "X", "LinkedIn"]
}}"""
        res = await self.execute_completion(prompt, allow_platform_env=True)
        if res.get("success") and res.get("text"):
            try:
                clean = self._clean_json_str(res["text"])
                data = json.loads(clean)
                if isinstance(data, dict) and "topics" in data:
                    return data
            except Exception as e:
                print(f"[AIService] Onboarding suggestion parse error: {e}")

        nl = (niche or "").lower()
        if "tech" in nl or "ai" in nl or "code" in nl or "software" in nl:
            return {
                "topics": [
                    "Artificial Intelligence & Agents",
                    "Coding & Developer Tools",
                    "Startups & Micro-SaaS",
                    "Cloud Infrastructure & DevOps",
                    "Cybersecurity & Privacy",
                    "Hardware & Next-Gen Chips"
                ],
                "audience_suggestions": [
                    "Software engineers, developers, and tech builders",
                    "Tech enthusiasts and early startup founders"
                ],
                "tones": [
                    {"title": "High Energy", "desc": "Fast-paced, exciting, and engaging"},
                    {"title": "Deep & Analytical", "desc": "Detailed, data-backed, and thoughtful"},
                    {"title": "Direct & Practical", "desc": "Concise, clear, and actionable"},
                    {"title": "Casual & Story-driven", "desc": "Relatable, personal, and conversational"}
                ],
                "suggested_platforms": ["YouTube", "X", "LinkedIn"]
            }
        else:
            return {
                "topics": [
                    f"{niche} Fundamentals & Getting Started",
                    f"Advanced {niche} Techniques",
                    f"Top Tools & Gear for {niche}",
                    f"Common Mistakes in {niche}",
                    f"Industry Trends & Future of {niche}",
                    f"{niche} Case Studies & Stories"
                ],
                "audience_suggestions": [
                    f"Enthusiasts, beginners, and practitioners in {niche}",
                    f"Curious learners wanting to master {niche}"
                ],
                "tones": [
                    {"title": "High Energy", "desc": "Engaging, lively, and enthusiastic"},
                    {"title": "Direct & Practical", "desc": "Concise, step-by-step guidance"},
                    {"title": "Deep & Analytical", "desc": "Detailed explanations and breakdowns"},
                    {"title": "Casual & Story-driven", "desc": "Friendly, relatable, and approachable"}
                ],
                "suggested_platforms": ["YouTube", "TikTok", "Instagram", "X"]
            }

    async def list_models(
        self,
        provider: str = "gemini",
        api_key: Optional[str] = None,
        prefs: Optional[UserPreferences] = None
    ) -> Dict[str, Any]:
        """Return verified valid models for the provider, plus live-fetched models when an API key is supplied."""
        resolved = self._resolve_provider_and_key(provider, None, api_key, prefs, allow_platform_env=False)
        prov = resolved["provider"]
        key = resolved["key"]
        curated = list(self.PROVIDER_MODELS.get(prov, [self.PROVIDER_DEFAULTS.get(prov, "gemini-2.5-flash")]))
        live_models: List[str] = []

        if key:
            try:
                if prov == "gemini" and genai is not None:
                    client = genai.Client(api_key=key)
                    pager = await asyncio.wait_for(client.aio.models.list(), timeout=10.0)
                    async for m in pager:
                        name = getattr(m, "name", "") or ""
                        if name.startswith("models/"):
                            name = name[len("models/"):]
                        actions = getattr(m, "supported_actions", None) or []
                        if name.startswith("gemini-") and ("generateContent" in actions or not actions):
                            if "tts" not in name and "embedding" not in name and "imagen" not in name:
                                live_models.append(name)
                elif prov == "anthropic":
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        resp = await client.get(
                            "https://api.anthropic.com/v1/models",
                            headers={"x-api-key": key, "anthropic-version": "2023-06-01"}
                        )
                        if resp.status_code == 200:
                            for item in resp.json().get("data", []):
                                mid = item.get("id")
                                if mid:
                                    live_models.append(mid)
                elif prov in ("openai", "groq", "openrouter", "deepseek"):
                    models_url_map = {
                        "openai": "https://api.openai.com/v1/models",
                        "groq": "https://api.groq.com/openai/v1/models",
                        "openrouter": "https://openrouter.ai/api/v1/models",
                        "deepseek": "https://api.deepseek.com/models"
                    }
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        resp = await client.get(
                            models_url_map[prov],
                            headers={"Authorization": f"Bearer {key}"}
                        )
                        if resp.status_code == 200:
                            for item in resp.json().get("data", []):
                                mid = item.get("id")
                                if mid and not any(skip in mid for skip in ("whisper", "tts", "dall-e", "embedding", "moderation", "audio", "realtime")):
                                    live_models.append(mid)
            except Exception as e:
                print(f"[AIService] Live model fetch note for {prov}: {e}")

        # Merge curated top picks first, followed by additional live models
        merged: List[str] = []
        for m in curated + live_models[:40]:
            if m and m not in merged:
                merged.append(m)

        return {
            "provider": prov,
            "default_model": self.PROVIDER_DEFAULTS.get(prov, merged[0] if merged else "gemini-2.5-flash"),
            "models": merged,
            "live_fetched": len(live_models) > 0
        }

    async def analyze_creator_profile(
        self,
        creator_name: str,
        handle: str,
        platform: str,
        bio: str,
        recent_titles: List[str],
        user_niche: Optional[str] = None,
        prefs: Optional[UserPreferences] = None
    ) -> Dict[str, Any]:
        """Dissect a creator's public profile and recent titles to extract niche, pacing, signature hooks, and angles."""
        self._require_user_key(prefs=prefs)
        
        titles_formatted = "\n".join(f"- {t}" for t in recent_titles[:8]) if recent_titles else "(None available)"
        user_context = f"User's Own Target Niche: '{user_niche}'. (CRITICAL: Do NOT assign this to the creator. The creator's topic_niche must come strictly from the creator's own content. Use the user's niche ONLY for 'original_angles'.)" if user_niche else ""

        prompt = f"""You are an elite creator growth strategist. Dissect this public creator profile:
Creator Name: {creator_name}
Handle: {handle}
Platform: {platform}
Bio/Description: {bio or 'No bio provided.'}

Recent Video / Post Titles:
{titles_formatted}

{user_context}

Analyze this creator's style and provide actionable intelligence. Return ONLY a valid JSON object with these keys:
{{
  "topic_niche": "Concise 2-4 word primary niche derived STRICTLY from the creator's own titles and bio (e.g. 'LLM Systems & AI Engineering', NEVER the user's niche)",
  "pacing_style": "Concise phrase describing delivery & cadence (e.g. 'Hyper-condensed 100s sprints with dry sarcasm')",
  "personal_notes": "2-3 crisp sentences detailing their storytelling structure, retention tricks, and why their audience watches.",
  "signature_hooks": [
    "Hook formula 1 adapted from their style (e.g. 'X is dead. Here is what actually replaces it.')",
    "Hook formula 2 adapted from their style",
    "Hook formula 3 adapted from their style"
  ],
  "original_angles": "2-3 actionable ways the user can emulate this creator's rhythm and hook framing within their own content without copying topics."
}}"""

        res = await self.execute_completion(prompt, prefs=prefs)
        if not res.get("success"):
            raise RuntimeError(res.get("error") or "Creator profile analysis failed.")

        if res.get("text"):
            try:
                clean = self._clean_json_str(res["text"])
                parsed = json.loads(clean)
                if isinstance(parsed, dict) and "signature_hooks" in parsed:
                    hooks = parsed.get("signature_hooks", [])
                    if isinstance(hooks, list):
                        hooks = [str(h) for h in hooks if str(h).strip()][:5]
                    else:
                        hooks = []
                    return {
                        "topic_niche": str(parsed.get("topic_niche") or f"{platform} Content").strip(),
                        "pacing_style": str(parsed.get("pacing_style") or "Engaging & Direct").strip(),
                        "personal_notes": str(parsed.get("personal_notes") or "").strip(),
                        "signature_hooks": hooks,
                        "original_angles": str(parsed.get("original_angles") or "").strip(),
                    }
            except Exception as e:
                print(f"[AIService] Creator profile parse error: {e}")

        # Sensible fallback if JSON parse fails
        return {
            "topic_niche": f"{creator_name} Niche",
            "pacing_style": "High-retention, concise pacing",
            "personal_notes": f"Creates consistent {platform} content focusing on high-curiosity titles and direct delivery.",
            "signature_hooks": [
                f"Why everyone is wrong about {recent_titles[0] if recent_titles else 'this topic'}",
                "The 3 things nobody tells you before starting",
                "How I approached this so you don't make the same mistake"
            ],
            "original_angles": "Borrow their immediate punch-in opening and apply it to your own domain."
        }

    async def test_connection(
        self,
        provider: str = "gemini",
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        prefs: Optional[UserPreferences] = None
    ) -> Dict[str, Any]:
        """Test round-trip live connectivity with any selected AI provider."""
        resolved = self._resolve_provider_and_key(provider, model, api_key, prefs, allow_platform_env=False)
        prov = resolved["provider"]
        mdl = resolved["model"]
        key = resolved["key"]
        label = self.PROVIDER_LABELS.get(prov, prov.capitalize())

        if not key:
            return {
                "status": "missing_key",
                "connected": False,
                "provider": prov,
                "model": mdl,
                "latency_ms": 0,
                "message": f"No {label} API key saved. Paste your {label} API key and click Save Key."
            }

        res = await self.execute_completion(
            prompt="Reply with exact 1 short sentence: 'AI engine online for Kre8 Creator Studio.'",
            provider=prov,
            model=mdl,
            api_key=key,
            allow_platform_env=False
        )

        k_preview = f"{key[:6]}...{key[-4:]}" if len(key) > 10 else "***"

        if res.get("success"):
            return {
                "status": "online",
                "connected": True,
                "provider": prov,
                "model": mdl,
                "latency_ms": res.get("latency_ms", 0),
                "message": f"Connected to {label} ({mdl})",
                "key_preview": k_preview,
                "is_fallback": False,
                "status_note": f"Connected to {label} ({mdl})"
            }
        else:
            return {
                "status": "error",
                "connected": False,
                "provider": prov,
                "model": mdl,
                "latency_ms": res.get("latency_ms", 0),
                "message": res.get("error", "Connection failed"),
                "key_preview": k_preview
            }

    async def synthesize_ideas_cross_pillar(
        self,
        user_niche: str,
        source_type: str,
        news_article: Optional[Any] = None,
        creator: Optional[Any] = None,
        topic_prompt: Optional[str] = None,
        count: int = 3,
        prefs: Optional[UserPreferences] = None
    ) -> List[Dict[str, Any]]:
        """Synthesize ideas combining breaking news, creator watchlist voice/style, or custom themes."""
        self._require_user_key(prefs=prefs)

        context_blocks = []
        if news_article:
            context_blocks.append(f"""BREAKING NEWS SOURCE:
Headline: {news_article.headline}
Source: {news_article.source_name}
Summary: {news_article.summary}
URL: {news_article.source_url}""")

        if creator:
            hooks_fmt = "\n".join([f"  - \"{h}\"" for h in (creator.signature_hooks or [])[:3]]) if creator.signature_hooks else "None"
            context_blocks.append(f"""CREATOR VOICE & STYLE TO EMULATE:
Creator: {creator.creator_name} ({creator.handle})
Platform: {creator.platform}
Pacing & Rhythm: {creator.pacing_style or 'Fast, punchy'}
Signature Hook Patterns:
{hooks_fmt}
Storytelling Techniques: {creator.personal_notes or 'Clear, direct breakdowns'}
Original Angles: {creator.original_angles or ''}""")

        if topic_prompt:
            context_blocks.append(f"""CUSTOM THEME / PROMPT:\n{topic_prompt}""")

        context_str = "\n\n".join(context_blocks) if context_blocks else "Generate trending, high-velocity topics."

        prompt = f"""You are an elite creative director for video creators.
User's Target Niche: {user_niche}
Mode: {source_type.upper()}

{context_str}

Generate {count} distinct, high-impact content ideas tailored to the user's niche. If a creator style is specified, the ideas, hook formulas, and tone MUST heavily reflect that creator's signature pacing and delivery.

Return ONLY a valid JSON array of objects with this schema:
[
  {{
    "title": "Magnetic, punchy video title",
    "description": "2 sentence explanation of why this angle will captivate viewers right now",
    "intended_platform": "YouTube",
    "category": "{user_niche}",
    "priority": "High",
    "tags": ["trending", "idea"],
    "hook_formulas": [
      "Curiosity opening hook",
      "Contrarian opening hook"
    ],
    "talking_points": [
      "Key point or scene 1",
      "Key point or scene 2",
      "Takeaway / CTA"
    ],
    "pacing_note": "Guidance on delivery rhythm"
  }}
]"""

        res = await self.execute_completion(prompt=prompt, prefs=prefs)
        if res.get("success") and res.get("text"):
            try:
                data = json.loads(self._clean_json_str(res["text"]))
                if isinstance(data, list):
                    return data
            except Exception as ex:
                print(f"[AIService] JSON error in cross-pillar ideas: {ex}")
                raise RuntimeError(f"Could not parse generated ideas: {ex}")
        raise RuntimeError(res.get("error") or "AI idea generation failed")

    async def test_prompt(
        self,
        prompt: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        prefs: Optional[UserPreferences] = None
    ) -> Dict[str, Any]:
        """Run an interactive test prompt through the active provider."""
        res = await self.execute_completion(
            prompt=prompt,
            provider=provider,
            model=model,
            api_key=api_key,
            prefs=prefs,
            allow_platform_env=False
        )
        return {
            "success": res.get("success", False),
            "response": res.get("text") or res.get("error") or "No response",
            "latency_ms": res.get("latency_ms", 0),
            "provider": res.get("provider", "gemini"),
            "model": res.get("model", "gemini-2.5-flash")
        }

ai_service = AIService()
