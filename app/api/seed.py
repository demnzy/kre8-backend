from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.models import (
    User, UserPreferences, ContentItem, ContentIdea, Script, ScriptClip,
    Task, Note, CalendarEvent, Goal, SocialAccount, AnalyticsSnapshot, CreatorWatchlist
)
from app.api.auth import get_current_user

router = APIRouter(prefix="/seed", tags=["seed"])

@router.post("/reset")
def reset_workspace(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Reset workspace data to a clean, fresh state for the current user."""
    db.query(Task).filter(Task.user_id == current_user.id).delete()
    db.query(CalendarEvent).filter(CalendarEvent.user_id == current_user.id).delete()
    db.query(Note).filter(Note.user_id == current_user.id).delete()
    db.query(Goal).filter(Goal.user_id == current_user.id).delete()
    
    # Delete clips via script cascades
    scripts = db.query(Script).filter(Script.user_id == current_user.id).all()
    for s in scripts:
        db.delete(s)
        
    db.query(ContentItem).filter(ContentItem.user_id == current_user.id).delete()
    db.query(ContentIdea).filter(ContentIdea.user_id == current_user.id).delete()
    db.query(CreatorWatchlist).filter(CreatorWatchlist.user_id == current_user.id).delete()
    db.commit()
    return {"message": "Workspace has been reset to a fresh empty state"}

@router.post("/load-demo")
def load_demo_data(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Pre-populate rich realistic demo data for testing."""
    now = datetime.utcnow()

    # 1. Update Preferences
    prefs = db.query(UserPreferences).filter(UserPreferences.user_id == current_user.id).first()
    if prefs:
        prefs.primary_niche = "Technology"
        prefs.sub_niche = "Artificial Intelligence & Agents"
        prefs.search_keywords = "AI, autonomous agents, Claude, OpenAI, Cursor, coding"
        prefs.weekly_post_goal = 4
        db.commit()

    # 2. Content Ideas
    ideas_data = [
        ("The Death of Traditional Web Dev: AI Agent Workflows", "Why manual boilerplate is obsolete and how agent orchestration takes over.", "High", ["ai-agents", "future-tech"]),
        ("Top 5 Open-Source AI Models You Can Run Locally", "Hardware requirements, Ollama setup, and performance benchmarks for 2026.", "Medium", ["local-ai", "hardware"]),
        ("How I Built a Profitable Micro-SaaS in 48 Hours with Cursor", "Step-by-step breakdown from prompt to first paying customer.", "Urgent", ["micro-saas", "case-study"]),
        ("Why Everyone is Leaving Chrome for Arc & Zen Browser", "Privacy, performance, and vertical tab workflow comparison.", "Low", ["browser", "productivity"])
    ]
    for title, desc, prio, tags in ideas_data:
        idea = ContentIdea(
            user_id=current_user.id,
            title=title,
            description=desc,
            category="Technology",
            intended_platform="YouTube",
            priority=prio,
            tags=tags,
            status="Active"
        )
        db.add(idea)

    # 3. Content Items (spread across workflow stages)
    content_data = [
        ("Building Autonomous Coding Agents from Scratch", "Deep dive into tool calling, memory systems, and execution loops.", "YouTube", "Video", "Script Writing", "Urgent", now + timedelta(days=2)),
        ("3 VS Code Extensions You Must Uninstall Today", "Quick punchy short-form video revealing bloated plugins slowing your IDE.", "TikTok", "Short/Reel", "Ready to Record", "High", now + timedelta(days=1)),
        ("The Architecture of Modern LLM Apps in 2026", "Visual carousel detailing vector storage, semantic caching, and reasoning loops.", "LinkedIn", "Carousel", "Editing", "Medium", now + timedelta(days=4)),
        ("Why Context Windows Don't Fix Bad Retrieval", "Engineering deep-dive explaining why RAG still beats million-token contexts.", "YouTube", "Video", "Published", "Medium", now - timedelta(days=3))
    ]
    created_items = []
    for title, desc, plat, fmt, stat, prio, planned in content_data:
        ci = ContentItem(
            user_id=current_user.id,
            title=title,
            description=desc,
            category="Technology",
            platform=plat,
            format=fmt,
            status=stat,
            priority=prio,
            planned_date=planned
        )
        db.add(ci)
        created_items.append(ci)
    db.commit()

    # 4. Create Script with Clips for the first content item
    script = Script(
        user_id=current_user.id,
        content_item_id=created_items[0].id,
        title="Building Autonomous Coding Agents from Scratch",
        tone="Punchy & Technical",
        target_duration_seconds=75,
        full_script="""[HOOK]
Most developers think AI coding is just tab-autocomplete. But real autonomous agents don't suggest code—they build entire systems while you sleep.

[SCENE 1: THE FOUNDATION]
An autonomous agent needs three components: A planner, tool execution hooks, and a reactive feedback loop. Without feedback, your LLM is flying blind.

[SCENE 2: THE EXECUTION ENGINE]
Here is the architecture: When an error triggers, the model inspects standard error, isolates the stack trace, and applies a patch before re-running the test runner.

[OUTRO]
Check the GitHub link in the description for the full starter repository!""",
        generated_hooks=[
            "Stop using AI as a glorified autocomplete—build autonomous agents instead.",
            "This 3-layer architecture lets AI code and debug full apps on its own.",
            "Why software engineers in 2026 don't write syntax anymore."
        ],
        generated_ctas=[
            "Subscribe and clone the repo from the link in description!",
            "Drop your agent ideas in the comments below."
        ]
    )
    db.add(script)
    db.commit()
    db.refresh(script)

    clips_data = [
        (1, "Most developers think AI coding is just tab autocomplete. But real autonomous agents build systems while you sleep.", 8, "STOP USING AI WRONG", "Direct to camera, quick punch in", "Zoom In"),
        (2, "An autonomous agent needs three components: A planner, tool execution hooks, and a reactive feedback loop.", 15, "THE 3 CORE LAYERS", "Diagram on screen showing Planner -> Tool -> Eval", "Slide Left"),
        (3, "When an error triggers, the model isolates the stack trace, and applies a patch before re-running the test runner.", 25, "AUTO-CORRECTION LOOP", "Screen recording showing automated terminal test passing", "Cut"),
        (4, "Check the GitHub link in the description for the full starter repository!", 7, "GET THE CODE", "Direct to camera pointing down at description", "Fade to Black")
    ]
    for num, dialogue, dur, text, visual, trans in clips_data:
        clip = ScriptClip(
            script_id=script.id,
            clip_number=num,
            spoken_dialogue=dialogue,
            estimated_duration=dur,
            on_screen_text=text,
            visual_direction=visual,
            transition=trans
        )
        db.add(clip)

    # 5. Tasks
    tasks_data = [
        ("Record B-Roll for Coding Agent Architecture video", now + timedelta(days=1), "High", [
            {"text": "Record terminal running unit test suite", "done": True},
            {"text": "Screen capture architecture diagram in Excalidraw", "done": False},
            {"text": "Record talking head A-roll in 4K", "done": False}
        ]),
        ("Batch edit 3 short-form clips for TikTok & Shorts", now + timedelta(days=2), "Medium", [
            {"text": "Add auto-captions with bold yellow highlights", "done": False},
            {"text": "Insert whoosh sound effects on transitions", "done": False}
        ]),
        ("Review weekly YouTube analytics & audience retention drop-offs", now, "Urgent", [
            {"text": "Check retention at the 30-second mark", "done": True},
            {"text": "Adjust thumbnail contrast for upcoming upload", "done": True}
        ])
    ]
    for title, due, prio, checklist in tasks_data:
        t = Task(
            user_id=current_user.id,
            title=title,
            due_date=due,
            priority=prio,
            is_completed=False,
            checklist=checklist
        )
        db.add(t)

    # 6. Notes
    notes_data = [
        ("Creator Content Strategy: 70/20/10 Rule", "70% proven evergreen formats (tutorials, setups)\n20% breaking news & timely trend breakdowns\n10% high-risk experimental formats (live coding marathons, interviews)", "Strategy", ["frameworks", "growth"], True),
        ("Best Microphones & Audio Post-Processing Settings", "Shure SM7B into Elgato Wave XLR.\nPlugins in OBS: Reaper ReaEQ, ReaComp, and Waves Clarity VX for background noise reduction.", "Gear & Studio", ["audio", "production"], False),
        ("Video Hook Formula Bank", "1. 'Most people think X, but Y'\n2. 'Here is what nobody tells you about X'\n3. 'If I had to start over in X from zero, here is what I would do'", "Writing", ["hooks", "scripts"], True)
    ]
    for title, content, folder, tags, pinned in notes_data:
        n = Note(
            user_id=current_user.id,
            title=title,
            content=content,
            folder=folder,
            tags=tags,
            is_pinned=pinned
        )
        db.add(n)

    # 7. Goals
    goals_data = [
        ("Publish 4 Videos This Week", "Weekly Posts", 4.0, 2.0, "videos"),
        ("Write 10 Full Video Scripts", "Scripts Written", 10.0, 6.0, "scripts"),
        ("Reach 10,000 YouTube Subscribers", "Follower Milestone", 10000.0, 7840.0, "subscribers"),
        ("Maintain 30-Day Publishing Streak", "Publishing Streak", 30.0, 18.0, "days")
    ]
    for title, gtype, target, cur, unit in goals_data:
        g = Goal(
            user_id=current_user.id,
            title=title,
            goal_type=gtype,
            target_value=target,
            current_value=cur,
            unit=unit,
            deadline=now + timedelta(days=14)
        )
        db.add(g)

    # 8. Calendar Events
    cal_data = [
        ("Upload YouTube: Autonomous Coding Agents", now + timedelta(days=2, hours=14), "Scheduled", "YouTube"),
        ("Post TikTok: 3 VS Code Extensions to Delete", now + timedelta(days=1, hours=17), "Planned", "TikTok"),
        ("Publish LinkedIn Carousel: LLM App Architecture", now + timedelta(days=4, hours=9), "Planned", "LinkedIn")
    ]
    for title, stime, etype, plat in cal_data:
        ce = CalendarEvent(
            user_id=current_user.id,
            title=title,
            start_time=stime,
            event_type=etype,
            platform=plat
        )
        db.add(ce)

    # 9. Watchlist
    watchlist_data = [
        ("Fireship", "@fireship_dev", "YouTube", "https://youtube.com/@fireship", "Tech Code & Speed Runs", "Master of 100-second rapid-fire breakdowns and meme transitions."),
        ("Theo - t3.gg", "@t3dotgg", "YouTube", "https://youtube.com/@t3dotgg", "Web Dev Opinions & Live Streams", "Great at turning community drama and GitHub releases into engaging video essays.")
    ]
    for name, handle, plat, url, niche, notes in watchlist_data:
        cw = CreatorWatchlist(
            user_id=current_user.id,
            creator_name=name,
            handle=handle,
            platform=plat,
            profile_url=url,
            topic_niche=niche,
            personal_notes=notes
        )
        db.add(cw)

    # 10. Social Accounts & Snapshots
    soc_acc = SocialAccount(
        user_id=current_user.id,
        platform="youtube",
        account_name="@creator_channel",
        is_connected=True,
        last_synced_at=now
    )
    db.add(soc_acc)
    db.commit()
    db.refresh(soc_acc)

    snap = AnalyticsSnapshot(
        social_account_id=soc_acc.id,
        followers=7840,
        views=48500,
        impressions=112000,
        likes=3400,
        comments=410,
        shares=195,
        engagement_rate=5.2
    )
    db.add(snap)
    db.commit()

    return {"message": "Demo data loaded successfully"}
