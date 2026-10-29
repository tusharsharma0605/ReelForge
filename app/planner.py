"""The 'director': turns a brief + assets into an edit plan. Uses Claude when a key is set, else a rule-based fallback."""
import json
import re

from .animator import ACTIONS as ANIM_ACTIONS, BACKGROUNDS as ANIM_BGS, EXPRESSIONS as ANIM_EXPR, FX as ANIM_FX, \
    ICONS as ANIM_ICONS, KINDS as ANIM_KINDS
from .audio import MOODS as MUSIC_MOODS, SFX as SFX_KINDS
from .media import preview_for_ai
from .renderer import ASPECTS, FILTERS, MOTIONS, TEXT_STYLES, TRANSITIONS

SYSTEM = f"""You are an award-winning short-form video director and editor (Reels, TikTok, Shorts, ads, trailers).
You receive a creative brief and a library of media assets (with previews, possibly EMPTY). You output an edit
decision list as JSON that a rendering engine executes exactly. You build the video by sequencing, trimming,
re-framing, animating (Ken Burns), color grading, titling and narrating media. Each scene's visual comes from ONE of:
  1. "asset_id": an asset from the library (prefer the user's own media when it fits), or
  2. "source": {{"type": "stock", "query": "...", "media": "photo"|"video", "fallback_query": "..."}} - the engine
     downloads a free stock/Creative-Commons photo or clip. Queries must be CONCRETE and VISUAL, 2-5 English words
     naming what is literally in the frame (e.g. "taj mahal sunrise", "chef chopping vegetables", "rainy tokyo street
     night"), never abstract ("love", "success"). fallback_query = a broader version. Use "video" for motion-heavy
     moments (only reliably available when the engine has a Pexels key; otherwise photos are used).
  3. "source": {{"type": "design", "layout": "title"|"stat"|"quote"|"list"|"text", "headline": "...",
     "subtext": "...", "items": ["..."], "accent": "#RRGGBB", "bg": ["#RRGGBB", "#RRGGBB"]}} - a designed
     motion-graphics card: title cards, big numbers/facts ("stat": headline = the number), quotes, bullet lists,
     calls to action. The card already shows its words, so set the scene "text" to "" for design scenes.
  4. "source": {{"type": "animation", ...spec}} - a 2D CARTOON scene rendered by the engine: fictional characters,
     mascots, logos with faces & limbs, robots, icons, speech bubbles, punches, explosions. Use it for skits, drama,
     satire, memes and "brand vs problem" stories (e.g. "a hiring platform logo knocks out the ATS robot").
     Spec (coordinates are fractions of the frame 0..1, characters stand on y~0.62; t in seconds from scene start):
     {{"background": {{"style": one of {ANIM_BGS}, "colors": ["#hex","#hex"], "query": "stock photo query (style photo only)"}},
       "actors": [{{"id": "hero", "kind": one of {ANIM_KINDS}, "label": "short name shown on it", "color": "#hex",
                   "x": 0.3, "y": 0.62, "size": 1.0, "expression": one of {ANIM_EXPR}, "facing": 1|-1,
                   "icon": one of {ANIM_ICONS} (kind icon), "limbs": true, "face": true,
                   "image_asset_id": "library image id (kind image, e.g. the user's real logo)"}}],
       "actions": [{{"t": 0.0, "actor": "hero", "do": one of {ANIM_ACTIONS}, "dur": 0.6,
                    "x": 0.5, "y": 0.62 (move/enter targets), "text": "bubble text (say/think/shout)",
                    "value": "expression name (do=expression)", "target": "actor id hit by a punch"}}],
       "fx": [{{"t": 1.2, "kind": one of {ANIM_FX}, "x": 0.6, "y": 0.5, "text": "POW!"}}],
       "camera": {{"zoom": "in"|"out"|"none"}}}}
     Rules: actors with an enter_*/pop_in/drop_in action are hidden until it starts. Punches auto-add an impact burst +
     sound on the target; follow with "hit", then "fall"/"explode" for knockouts. Keep bubble text short (<= 9 words),
     give each beat ~1-2s, and make the scene duration cover the last action (+0.5s). Animation scenes play their
     own motion, set "motion": "static". Narration can run over the skit, but leave room to read the bubbles.
Mix stock footage, design cards and animation for rich, Instagram-reel style videos when the library is empty.
Get facts right: if a web search tool is available, research the topic first and use accurate, specific facts.

Craft guidelines:
- Hook in the first 1.5 seconds: strongest visual + punchy on-screen text.
- Pacing follows mood: energetic = 0.8-2s shots, snappy transitions (slide/wipe/zoomin/none cuts);
  calm/emotional/cinematic = 3-5s shots, fade/dissolve/fadeblack.
- Vary camera motion between consecutive image scenes; never repeat the same motion twice in a row.
- On-screen text: short and punchy (max ~8 words), complementing narration, not repeating it word for word.
  Leave text empty when the image should breathe.
- Narration (only if voiceover is enabled): conversational, ~2.5 words per second, must fit its scene duration.
  If the user gave a script, follow it faithfully, splitting it across scenes.
- For video assets choose "start" at the most interesting moment (seconds, within the clip length) and keep
  start+duration*speed within the clip. Use speed 0.5 for slow-motion moments, 1.5-2 for time-lapse feel.
- keep_audio true only when the clip's own sound matters (speech, ambience); set false if a voiceover talks over it.
- You may reuse assets (with different motion/start). Only use asset ids that exist in the library.
- Hit the target duration if one is given (sum of scene durations minus transition overlaps).
- Pick one consistent color look ("filter") unless the brief suggests otherwise.

Return ONLY a JSON object, no prose, no markdown fences, with this schema:
{{
  "title": "short title",
  "filter": one of {list(FILTERS)},
  "text_style": one of {TEXT_STYLES},
  "accent_color": "#RRGGBB",
  "music": {{"asset_id": "audio asset id or null", "generate": one of {MUSIC_MOODS} or null (composed soundtrack when no audio asset), "volume": 0.0-1.0}},
  "captions": "karaoke" (animated word-by-word captions synced to narration) | "off",
  "look": {{"letterbox": bool (cinematic black bars), "grain": bool (film grain)}},
  "sfx": true (whooshes on transitions, pops, hits, booms),
  "scenes": [
    {{
      "asset_id": "id"   (OR "source": {{...}} as described above),
      "start": 0.0,
      "duration": 2.5,
      "speed": 1.0,
      "motion": one of {MOTIONS},
      "transition": one of {TRANSITIONS}  (transition INTO this scene; ignored for the first),
      "transition_duration": 0.2-1.2,
      "text": "on-screen text or empty",
      "text_position": "top" | "center" | "bottom",
      "narration": "voiceover line or empty",
      "keep_audio": false,
      "audio_volume": 1.0,
      "fit": "auto" | "cover" | "contain",
      "sfx": [{{"t": 0.0, "kind": one of {SFX_KINDS}}}]  (optional extra sound effects, seconds from scene start)
    }}
  ]
}}
Style notes: "filmography"/cinematic/documentary = letterbox + grain + cinematic filter + cinematic or dramatic music,
slow motion, fadeblack transitions. Instagram reels = hook text, fast cuts, karaoke captions, upbeat/quirky music,
mix of photos, designed cards and cartoon skits."""


def _num(v, lo, hi, default):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


def sanitize(plan: dict, req: dict, assets: list[dict], from_plan=False) -> dict:
    """from_plan=True: an existing/edited plan -> its own aspect, voiceover, style and music win over the form."""
    by_id = {a["id"]: a for a in assets}
    visual = {i for i, a in by_id.items() if a["kind"] in ("image", "video", "anim")}
    audio = [a["id"] for a in assets if a["kind"] == "audio"]
    music = plan.get("music") or {}
    look = plan.get("look") if isinstance(plan.get("look"), dict) else {}
    gen = music.get("generate") if music.get("generate") in MUSIC_MOODS else None
    if from_plan:
        vo = plan.get("voiceover") or {}
        aspect = plan.get("aspect") if plan.get("aspect") in ASPECTS else req.get("aspect")
        style = plan.get("text_style")
        voice = {"enabled": bool(vo.get("enabled")), "voice": vo.get("voice") or req.get("voice", ""), "rate": vo.get("rate", 0)}
        mid = music.get("asset_id") if music.get("asset_id") in audio else None
        if "generate" not in music and not mid:
            gen = None
    else:
        aspect = req.get("aspect")
        style = req.get("text_style") if req.get("text_style") in TEXT_STYLES else plan.get("text_style")
        voice = {"enabled": bool(req.get("voiceover")), "voice": req.get("voice", ""), "rate": req.get("voice_rate", 0)}
        rm = req.get("music_asset_id") or ""
        mid = (None if rm == "none" or rm.startswith("gen:") else rm if rm in audio
               else music.get("asset_id") if music.get("asset_id") in audio else audio[0] if audio else None)
        if rm.startswith("gen:") and rm[4:] in MUSIC_MOODS:
            gen = rm[4:]
        elif rm == "none":
            gen = None
        elif not mid:
            gen = gen or _mood_music(" ".join([req.get("prompt", ""), req.get("direction", "")]))
        if req.get("look") == "cinematic":
            look = {"letterbox": True, "grain": True}
        elif req.get("look") == "clean":
            look = {"letterbox": False, "grain": False}
    voice["rate"] = int(_num(voice["rate"], -5, 5, 0))
    captions = plan.get("captions") if plan.get("captions") in ("karaoke", "off") else "karaoke"
    if not from_plan and req.get("captions") in ("karaoke", "off"):
        captions = req["captions"]
    out = {
        "title": str(plan.get("title") or "Untitled reel")[:80],
        "aspect": aspect if aspect in ASPECTS else "9:16",
        "filter": plan.get("filter") if plan.get("filter") in FILTERS else "none",
        "text_style": style if style in TEXT_STYLES else "bold",
        "accent_color": plan.get("accent_color") if re.fullmatch(r"#[0-9a-fA-F]{6}", str(plan.get("accent_color", ""))) else "#FFCC00",
        "voiceover": voice,
        "music": {"asset_id": mid, "generate": None if mid else gen, "volume": _num(music.get("volume"), 0, 1, 0.3 if gen and not mid else 0.35)},
        "captions": captions,
        "look": {"letterbox": bool(look.get("letterbox")), "grain": bool(look.get("grain"))},
        "sfx": bool(plan.get("sfx", True)) if from_plan or req.get("sfx", True) else False,
        "scenes": [],
    }
    for s in plan.get("scenes", []):
        aid = s.get("asset_id")
        if aid not in visual:
            continue
        a = by_id[aid]
        speed = _num(s.get("speed"), 0.25, 3, 1.0)
        dur = _num(s.get("duration"), 0.5, 20, 3.0)
        start = 0.0
        if a["kind"] == "video":
            start = _num(s.get("start"), 0, max(0, a["duration"] - 0.3), 0)
        out["scenes"].append({
            "asset_id": aid,
            "start": round(start, 2),
            "duration": round(dur, 2),
            "speed": speed,
            "motion": s.get("motion") if s.get("motion") in MOTIONS else "zoom_in",
            "transition": s.get("transition") if s.get("transition") in TRANSITIONS else "fade",
            "transition_duration": _num(s.get("transition_duration"), 0.1, 1.5, 0.5),
            "text": str(s.get("text") or "")[:200],
            "text_position": s.get("text_position") if s.get("text_position") in ("top", "center", "bottom") else "bottom",
            "narration": str(s.get("narration") or "")[:600] if out["voiceover"]["enabled"] or from_plan else "",
            "keep_audio": bool(s.get("keep_audio", False)),
            "audio_volume": _num(s.get("audio_volume"), 0, 2, 1.0),
            "fit": s.get("fit") if s.get("fit") in ("auto", "cover", "contain") else "auto",
            "filter": s.get("filter") if s.get("filter") in FILTERS else out["filter"],
            "sfx": [x for x in (s.get("sfx") or []) if isinstance(x, dict) and x.get("kind") in SFX_KINDS][:12],
        })
        if isinstance(s.get("source"), dict) and a.get("source") not in (None, "upload"):
            out["scenes"][-1]["source"] = s["source"]  # lets the engine re-create auto-cleaned media when editing later
        if a["kind"] == "anim":
            out["scenes"][-1]["motion"] = "static"
    return out


def _mood_music(brief):
    b = brief.lower()
    for pat, mood in ((r"funny|comedy|meme|satir|skit|quirky|kill|vs\b|versus|fight|roast", "quirky"),
                      (r"film|cinema|documentary|epic|history|trailer|story|filmography", "cinematic"),
                      (r"drama|dark|thriller|tension|horror|mystery|war", "dramatic"),
                      (r"calm|relax|peace|wedding|love|nature|meditat|soft|memor", "calm")):
        if re.search(pat, b):
            return mood
    return "upbeat"


# ---------------------------------------------------------------- Claude director
def _brief(req, assets, context_text):
    lines = [
        f"PROMPT / IDEA:\n{req.get('prompt') or '(none)'}",
        f"SCRIPT:\n{req.get('script') or '(none - write narration/text yourself if useful)'}",
        f"DIRECTION / STYLE NOTES:\n{req.get('direction') or '(none - use your judgement)'}",
        f"ASPECT RATIO: {req.get('aspect', '9:16')}",
        f"TARGET DURATION: {str(req.get('target_duration')) + ' seconds' if req.get('target_duration') else 'auto (choose what fits best, typically 15-30s)'}",
        f"VOICEOVER: {'enabled - write narration lines' if req.get('voiceover') else 'disabled - leave narration empty'}",
        f"TEXT STYLE: {req.get('text_style') or 'auto'}",
    ]
    lines.append("MEDIA: " + ("you may use stock and design sources for any scene (required if the library is empty)"
                              if req.get("auto_media", True) else "use ONLY library assets (design cards are allowed)"))
    if context_text:
        lines.append(f"ATTACHED DOCUMENTS / RESEARCH (reference material):\n{context_text[:15000]}")
    return "\n\n".join(lines)


def _extract_json(text):
    starts = [m.start() for m in re.finditer(r"\{", text)]
    end = text.rfind("}")
    for s in starts:
        try:
            return json.loads(text[s:end + 1])
        except json.JSONDecodeError:
            continue
    raise ValueError("Claude did not return valid JSON")


def _library(assets, log, selected=()):
    content, shown = [], 0
    for a in assets:
        desc = f"Asset id={a['id']} kind={a['kind']} file=\"{a['name']}\""
        if a["kind"] == "video":
            desc += f" duration={a['duration']:.1f}s size={a['width']}x{a['height']} has_audio={a['has_audio']} (preview = frames at 15%/50%/85%)"
        elif a["kind"] == "image":
            desc += f" size={a['width']}x{a['height']}"
        elif a["kind"] == "audio":
            desc += f" duration={a['duration']:.1f}s (music/sound candidate)"
        if a["id"] in selected:
            desc += " [SELECTED by the user right now]"
        content.append({"type": "text", "text": desc})
        if a["kind"] in ("image", "video") and shown < 40:
            try:
                b64 = preview_for_ai(a["path"], a["kind"], a)
                content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}})
                shown += 1
            except Exception as e:
                log(f"preview failed for {a['name']}: {e}")
    return content, shown


MODELS = [
    ("claude-sonnet-5-5", "Claude Sonnet 5.5 - best speed/quality balance (recommended)"),
    ("claude-opus-5-5", "Claude Opus 5.5 - smarter, slower"),
    ("claude-fable-5-1", "Claude Fable 5.1 - deepest reasoning, slowest, priciest"),
    ("claude-haiku-5-5", "Claude Haiku 5.5 - fastest & cheapest"),
]
DEFAULT_MODEL = MODELS[0][0]


def make_client(settings):
    import anthropic

    ws = (settings.get("workspace_id") or "").strip()
    return anthropic.Anthropic(api_key=settings["anthropic_api_key"],
                               default_headers={"anthropic-workspace-id": ws} if ws else None)


def list_models(settings):
    """Models available to this key (live from the API), falling back to the known current lineup."""
    known = dict(MODELS)
    if settings.get("anthropic_api_key"):
        try:
            live = [m for m in make_client(settings).models.list(limit=100).data]
            if live:
                return [{"id": m.id, "label": known.get(m.id) or getattr(m, "display_name", m.id)} for m in live], True
        except Exception:
            pass
    return [{"id": i, "label": l} for i, l in MODELS], False


def _ask_claude(settings, system, content, web_search=False, log=print):
    import anthropic

    client = make_client(settings)
    kw = dict(model=settings["model"], max_tokens=12000, system=system, messages=[{"role": "user", "content": content}])
    if web_search:
        try:
            msg = client.messages.create(**kw, tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}])
            searches = sum(1 for b in msg.content if b.type == "server_tool_use")
            if searches:
                log(f"Claude researched the topic with {searches} web search(es)")
        except anthropic.BadRequestError as e:
            log(f"Web search not available for this key/model ({str(e)[:120]}); continuing without it.")
            msg = client.messages.create(**kw)
    else:
        msg = client.messages.create(**kw)
    return _extract_json("".join(b.text for b in msg.content if b.type == "text"))


def claude_plan(req, assets, settings, context_text, log):
    lib, shown = _library(assets, log)
    content = [{"type": "text", "text": _brief(req, assets, context_text) + "\n\nMEDIA LIBRARY:" + ("" if lib else " (empty)")},
               *lib, {"type": "text", "text": "Now output the JSON edit plan."}]
    log(f"Asking Claude ({settings['model']}) to write and direct the video ({shown} previews)...")
    return _ask_claude(settings, SYSTEM, content, web_search=req.get("research", True), log=log)


REVISE_SYSTEM = SYSTEM + f"""

REVISION MODE: you get the CURRENT PLAN of an existing video and the user's CHANGE REQUEST. Apply the request
precisely and keep everything else identical unless the request implies otherwise. Scene numbers are 1-based.
Assets marked [SELECTED] are the ones the user is pointing at (e.g. "add these", "replace scene 2 with this").
In revision mode the JSON must also contain "aspect" (one of {list(ASPECTS)}),
"voiceover": {{"enabled": bool, "voice": "voice name", "rate": -5..5}}, and
"changes": ["short human summary of each change you made"]. Return the FULL revised plan JSON only."""


def claude_revise(plan, instruction, assets, selected, settings, log):
    used = {s.get("asset_id") for s in plan.get("scenes", [])}
    relevant = [a for a in assets if a["id"] in used or a["id"] in selected or a["kind"] == "audio"]
    lib, shown = _library(relevant, log, selected)
    content = [{"type": "text", "text": f"CURRENT PLAN:\n{json.dumps(plan, indent=1)}\n\nCHANGE REQUEST:\n{instruction}\n\nMEDIA LIBRARY:"},
               *lib, {"type": "text", "text": "Now output the full revised JSON plan."}]
    log(f"Asking Claude ({settings['model']}) to apply: {instruction}")
    return _ask_claude(settings, REVISE_SYSTEM, content, web_search=req.get("research", True), log=log)


def _finish(plan, req, assets, resolver, from_plan):
    new = []
    if resolver:
        plan, new = resolver(plan)
    return sanitize(plan, req, assets + new, from_plan=from_plan)


def revise(plan, instruction, req, assets, settings, log, resolver=None):
    """Apply a natural-language change to an existing plan -> (plan, director, changes)."""
    from .editor import rule_revise

    selected = [i for i in req.get("asset_ids", [])]
    if req.get("use_ai", True) and settings.get("anthropic_api_key"):
        try:
            new = claude_revise(plan, instruction, assets, selected, settings, log)
            changes = [str(c) for c in new.get("changes", [])][:20] or ["Applied your change"]
            return _finish(new, req, assets, resolver, True), "claude", changes
        except Exception as e:
            log(f"Claude editor failed ({e}); trying the built-in editor.")
    new, changes = rule_revise(json.loads(json.dumps(plan)), instruction, selected, assets)
    return _finish(new, req, assets, resolver, True), "builtin", changes


# ---------------------------------------------------------------- fallback director
MOODS = {
    "energetic": (r"energ|hype|fast|exciting|party|sport|gym|action|upbeat|fun|travel", 1.8,
                  ["slideleft", "zoomin", "wipeleft", "slideup", "none"], "vivid", "#FF3D6E"),
    "cinematic": (r"cinema|film|movie|epic|trailer|dramatic|moody|dark|documentary|history|manufactur|factory|story", 3.5,
                  ["fadeblack", "dissolve", "fade", "smoothleft"], "cinematic", "#E8C07D"),
    "calm": (r"calm|peace|emotional|love|wedding|memor|nostalg|soft|relax|family", 3.5,
             ["fade", "dissolve", "fade", "circleopen"], "warm", "#FFD6A5"),
}


def _sentences(text):
    parts = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def skit_plan(req):
    from .skits import skit

    res = skit(req.get("prompt") or "")
    if not res:
        return None
    spec, beats, title, outro = res
    vo = req.get("voiceover")
    return {"title": title, "filter": "vivid", "text_style": "box", "accent_color": "#FFD400", "captions": "karaoke",
            "music": {"generate": "quirky", "volume": 0.3}, "sfx": True,
            "scenes": [
                {"source": {"type": "design", "layout": "title", "headline": title, "subtext": "a very short story", "accent": "#FFD400"},
                 "duration": 2.4, "motion": "zoom_in", "transition": "fade", "narration": beats[0], "text": "",
                 "sfx": [{"t": 0.0, "kind": "riser"}]},
                {"source": {"type": "animation", **spec}, "duration": 8.2, "motion": "static", "transition": "zoomin",
                 "transition_duration": 0.4, "narration": beats[1] if vo else "", "text": ""},
                {"source": {"type": "design", "layout": "text", "headline": outro, "subtext": "Follow for more"},
                 "duration": 2.6, "motion": "zoom_in", "transition": "slideup", "transition_duration": 0.4,
                 "narration": beats[2], "text": "", "sfx": [{"t": 0.1, "kind": "ding"}]},
            ]}


def fallback_plan(req, assets, context_text, log=print):
    from .sourcing import subject_of, topic_of, wikipedia_research

    if not [a for a in assets if a["kind"] in ("image", "video")] and (sk := skit_plan(req)):
        log("Built-in director: writing a cartoon skit")
        return sk
    brief = " ".join([req.get("prompt", ""), req.get("direction", "")]).lower()
    mood = next((m for m, v in MOODS.items() if re.search(v[0], brief)), None)
    pattern, shot, trans, flt, accent = MOODS.get(mood) or ("", 2.6, ["fade", "slideleft", "dissolve", "wipeleft"], "none", "#FFCC00")
    visual = [a for a in assets if a["kind"] in ("image", "video")]
    auto = req.get("auto_media", True)
    if not visual and not auto:
        raise ValueError("Upload/select at least one photo or video, or turn on 'Find photos & videos online'.")
    target = float(req.get("target_duration") or 0)
    topic = topic_of(req.get("prompt") or req.get("script") or "")
    subject = subject_of(topic)
    script = req.get("script") or context_text
    if not script and not visual and req.get("research", True):
        budget = (target or 30) * (2.4 if req.get("voiceover") else 3.2)
        lines, used = [], 0
        for l in (l for l in _sentences(wikipedia_research(subject, log)) if 4 <= len(l.split()) <= 30):
            if used + len(l.split()) > budget and lines:
                break
            lines.append(l)
            used += len(l.split())
    else:
        lines = _sentences(script or "")
    if not visual:
        split = []
        for l in lines:
            w = l.split()
            cut = next((k for k in sorted(range(5, len(w) - 4), key=lambda k: abs(k - len(w) / 2)) if w[k - 1].endswith(",")), None) if len(w) > 16 else None
            split += [" ".join(w[:cut]).rstrip(","), " ".join(w[cut:])] if cut else [l]
        lines = split
    prompt_only = not visual
    body = lines
    n = max(len(visual), len(body)) if body else (len(visual) or max(3, round(target / 3) if target else 5))
    if target:
        shot = max(0.8, target / (n + prompt_only))
    motions = ["zoom_in", "pan_right", "zoom_out", "pan_left", "pan_up", "zoom_in", "pan_down"]
    small = {"of", "the", "a", "an", "and", "in", "on", "for", "to", "at", "by", "vs"}
    title = " ".join(w if (k and w.lower() in small) or w[1:] != w[1:].lower() else w[:1].upper() + w[1:]
                     for k, w in enumerate(topic.split())) if prompt_only else " ".join((req.get("prompt") or "").strip().split("\n")[0].split()[:7])
    td = 0.25 if mood == "energetic" else 0.7
    scenes = []
    if prompt_only:
        scenes.append({"source": {"type": "design", "layout": "title", "headline": title, "accent": accent},
                       "duration": max(shot, 2.5), "motion": "zoom_in", "transition": "fade", "transition_duration": td,
                       "text": "", "narration": f"{subject[:1].upper() + subject[1:]}. Here's what you need to know."
                                                if lines else f"{title}.", "sfx": [{"t": 0.0, "kind": "riser"}]})
    def caption(t):
        if len(t.split()) <= 12:
            return t
        first = re.split(r",|;| - | which | who | and ", t)[0].strip()
        return first if 3 <= len(first.split()) <= 12 else " ".join(t.split()[:10]) + "..."

    for i in range(n):
        line = body[i] if i < len(body) else ""
        if i < len(visual) or (visual and not auto):
            a = visual[i % len(visual)]
            src = {"asset_id": a["id"], "keep_audio": a["kind"] == "video" and not req.get("voiceover")}
            dur = min(max(shot, 2.0), a["duration"]) if a["kind"] == "video" and a["duration"] else shot
        else:
            src = {"source": {"type": "stock", "query": subject, "media": "photo"}}
            dur = shot
        text = line or ("" if prompt_only or i else title)
        scenes.append({**src, "start": 0, "duration": dur, "speed": 1.0,
                       "motion": motions[(i + prompt_only) % len(motions)], "transition": trans[(i + prompt_only) % len(trans)],
                       "transition_duration": td,
                       "text": caption(text),
                       "text_position": "center" if i == 0 and not prompt_only and not line else "bottom",
                       "narration": line})
    cine = mood == "cinematic"
    return {"title": title or "My reel", "filter": flt, "text_style": "box" if mood == "energetic" else "bold",
            "accent_color": accent, "music": {"asset_id": None, "volume": 0.35}, "captions": "karaoke", "sfx": True,
            "look": {"letterbox": cine, "grain": cine}, "scenes": scenes}


def make_plan(req, assets, settings, context_text, log, resolver=None):
    if req.get("use_ai", True) and settings.get("anthropic_api_key"):
        try:
            return _finish(claude_plan(req, assets, settings, context_text, log), req, assets, resolver, False), "claude"
        except Exception as e:
            log(f"Claude director failed ({e}); using built-in director instead.")
    else:
        log("No Claude API key set - using the built-in rule-based director.")
    return _finish(fallback_plan(req, assets, context_text, log), req, assets, resolver, False), "builtin"
