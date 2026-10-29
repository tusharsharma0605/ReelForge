"""Built-in (offline) prompt editor: understands common edit commands and applies them to a plan."""
import re

from . import tts

NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10}
SCENE = r"(?:scene|clip|shot|slide|part|photo|image|picture|video)"
VERBS = (r"make|change|set|add|remove|delete|use|put|move|swap|mute|unmute|turn|give|apply|replace|cut|drop|speed|slow|"
         r"increase|decrease|reduce|lower|raise|switch|convert|reverse|shuffle|duplicate|repeat|show|hide|keep|zoom|pan|"
         r"let|enable|disable|start|end|include|insert")
COLORS = {"red": "#FF3B3B", "blue": "#2F7BFF", "yellow": "#FFD400", "gold": "#E8C07D", "pink": "#FF4D8D",
          "green": "#2BD67B", "purple": "#8B5CFF", "orange": "#FF8A00", "white": "#FFFFFF", "black": "#111111",
          "cyan": "#00E5FF", "teal": "#14B8A6"}
FILTER_WORDS = [(r"black (?:and|&) white|b&w|\bbw\b|gr[ae]yscale|monochrome", "bw"),
                (r"cinematic|film look|movie look|filmic", "cinematic"),
                (r"warm(?:er)?\s+(?:look|tone|colou?rs?|filter|grade|feel)|\bwarmer\b", "warm"),
                (r"(?:cool|cold)(?:er)?\s+(?:look|tone|colou?rs?|filter|grade|feel)|\bcooler\b", "cool"),
                (r"vivid|saturat|vibrant|colou?rful|punchy colou?rs", "vivid"),
                (r"vintage|retro|old film|nostalgic look", "vintage"),
                (r"no filter|remove (?:the )?(?:filter|grade|look)|original colou?rs|natural colou?rs", "none")]
TRANS_WORDS = [(r"hard cuts?|no transitions?|jump cuts?|\bcuts?\b", "none"), (r"fade to black|black fade|dip to black", "fadeblack"),
               (r"white flash|\bflash|fade to white", "fadewhite"), (r"dissolve|cross ?fade", "dissolve"),
               (r"slide", "slideleft"), (r"wipe", "wipeleft"), (r"zoom", "zoomin"), (r"circle", "circleopen"),
               (r"glitch|pixel", "pixelize"), (r"blur", "hblur"), (r"smooth", "smoothleft"), (r"radial|spin", "radial"),
               (r"squeeze", "squeezev"), (r"\bfades?\b", "fade")]
MOTION_WORDS = [(r"zoom(?:ing)? in|push in", "zoom_in"), (r"zoom(?:ing)? out|pull (?:out|back)", "zoom_out"),
                (r"pan(?:ning)? left", "pan_left"), (r"pan(?:ning)? right", "pan_right"),
                (r"pan(?:ning)? up|tilt up", "pan_up"), (r"pan(?:ning)? down|tilt down", "pan_down"),
                (r"\bstatic\b|no (?:motion|movement|zoom)|keep (?:it )?still", "static")]
MOTION_CYCLE = ["zoom_in", "pan_right", "zoom_out", "pan_left", "pan_up", "pan_down"]
HELP = ("I couldn't understand that edit. Add a Claude API key in Settings for free-form edits, or try things like: "
        "'make it faster', 'make it 15 seconds', 'make scene 2 5 seconds', 'remove scene 3', 'move scene 4 to the start', "
        "'swap scenes 1 and 2', 'change scene 1 text to \"Hello Goa\"', 'move text to the top', 'neon captions', "
        "'yellow captions', 'cinematic look', 'black and white', 'fade transitions', 'hard cuts', 'zoom in on scene 2', "
        "'slow motion on the clip', 'no music', 'music quieter', 'add voiceover', 'female voice', 'make it square', "
        "'add the selected photos at the end', 'replace scene 2 with the selected photo', 'reverse the order'.")


def _mask_quotes(text):
    quotes = []

    def keep(m):
        quotes.append(m.group(1))
        return f" \x00{len(quotes) - 1}\x00 "

    text = re.sub(r"[\"“”](.+?)[\"“”]", keep, text)
    text = re.sub(r"(?<!\w)'(.+?)'(?!\w)", keep, text)
    return text, quotes


def _clauses(masked):
    masked = re.sub(rf"\b({SCENE}s?)\s+({'|'.join(NUM_WORDS)})\b", lambda m: f"{m[1]} {NUM_WORDS[m[2]]}", masked, flags=re.I)
    parts = re.split(rf"\s*(?:;|\n|\.\s+|,?\s+(?:and\s+)?then\s+|,?\s+and\s+(?=(?:{VERBS})\b)|,\s+(?=(?:{VERBS})\b))\s*",
                     masked, flags=re.I)
    return [p.strip(" .,") for p in parts if p.strip(" .,")]


def _targets(c, n):
    idx = []
    for m in re.finditer(rf"{SCENE}s?\s*#?(\d+)\s*(?:-|to|through)\s*(\d+)", c):
        idx += range(int(m[1]) - 1, int(m[2]))
    for m in re.finditer(rf"{SCENE}s\s+((?:\d+(?:\s*(?:,|and|&)\s*)?)+)", c):
        idx += [int(d) - 1 for d in re.findall(r"\d+", m[1])]
    idx += [int(d) - 1 for d in re.findall(rf"{SCENE}\s*#?(\d+)", c)]
    for w, k in ORDINALS.items():
        if re.search(rf"\b{w}\s+(?:{SCENE[3:-1]}|one)\b", c):
            idx.append(k - 1)
    if re.search(rf"\b(?:last|final)\s+(?:{SCENE[3:-1]}|one)\b|\bending\b|\boutro\b", c):
        idx.append(n - 1)
    if re.search(r"\bopening\b|\bintro\b|\bhook\b", c):
        idx.append(0)
    return sorted({i for i in idx if 0 <= i < n})


def _value(c, raw_quotes):
    if m := re.search(r"\x00(\d+)\x00", c):
        return raw_quotes[int(m[1])], True
    if m := re.search(r"(?:\bto\b|\bsay(?:s|ing)?\b|\bread(?:s|ing)?\b|:)\s+(.+)$", c, re.I):
        return m[1].strip(), False
    if m := re.search(r"\b(?:titled?|text|caption|heading|headline)\s+(?!(?:on|in|at|of|for|the|a|style|colou?r|position|size)\b)(.+)$", c, re.I):
        return m[1].strip(), False
    return None, False


def _new_scene(asset, k, transition="fade"):
    dur = 3.0 if asset["kind"] == "image" else max(1.0, min(4.0, asset["duration"] or 4.0))
    return {"asset_id": asset["id"], "start": 0, "duration": dur, "speed": 1.0, "motion": MOTION_CYCLE[k % len(MOTION_CYCLE)],
            "transition": transition, "transition_duration": 0.5, "text": "", "text_position": "bottom", "narration": "",
            "keep_audio": False}


def _src_scene(source, k, transition="fade"):
    return {"source": source, "start": 0, "duration": 3.0, "speed": 1.0, "motion": MOTION_CYCLE[k % len(MOTION_CYCLE)],
            "transition": transition, "transition_duration": 0.5, "text": "", "text_position": "bottom", "narration": "",
            "keep_audio": False}


def _card(layout, val):
    val = (val or "").strip()
    if layout == "stat" and (m := re.match(r"([\d.,]+\s*[%kKmMbB+x]*|\$[\d.,]+\s*\w*)\s*(.*)", val)):
        return {"type": "design", "layout": "stat", "headline": m[1].strip(), "subtext": m[2].strip()}
    if layout == "list":
        head, _, rest = val.partition(":") if ":" in val else ("Key points", "", val)
        return {"type": "design", "layout": "list", "headline": head.strip(),
                "items": [i.strip() for i in re.split(r",|;|\band\b", rest) if i.strip()]}
    if layout == "quote":
        parts = re.split(r"\s+(?:-|by)\s+", val, maxsplit=1) + [""]
        return {"type": "design", "layout": "quote", "headline": parts[0], "subtext": parts[1]}
    return {"type": "design", "layout": layout, "headline": val}


def _insert(sc, items, c, tg):
    if re.search(r"\b(start|beginning|front|intro|opening)\b", c):
        sc[0:0] = items
        return "at the start"
    if re.search(r"\bbefore\b", c) and tg:
        sc[tg[0]:tg[0]] = items
        return f"before scene {tg[0] + 1}"
    if tg and not re.search(r"\b(end|outro|closing|last)\b", c):
        sc[tg[0] + 1:tg[0] + 1] = items
        return f"after scene {tg[0] + 1}"
    sc.extend(items)
    return "at the end"


def rule_revise(plan, instruction, selected_ids, assets):
    by_id = {a["id"]: a for a in assets}
    sel = [by_id[i] for i in selected_ids if i in by_id]
    sel_visual = [a for a in sel if a["kind"] in ("image", "video")]
    masked, quotes = _mask_quotes(instruction)
    changes = []
    sc = plan["scenes"]
    common_t = max({s["transition"] for s in sc} or {"fade"}, key=lambda t: sum(s["transition"] == t for s in sc))

    for clause in _clauses(masked):
        c = clause.lower()
        n = len(sc)
        tg = _targets(c, n)
        names = ", ".join(str(i + 1) for i in tg)
        val, quoted = _value(clause, quotes)
        on = lambda: [sc[i] for i in tg] if tg else sc

        # ---------- structural edits (consume the clause)
        if m := re.search(rf"swap\s+{SCENE}s?\s*(\d+)\s*(?:and|with|&)\s*(?:{SCENE}\s*)?(\d+)", c):
            a, b = int(m[1]) - 1, int(m[2]) - 1
            if 0 <= a < n and 0 <= b < n:
                sc[a], sc[b] = sc[b], sc[a]
                changes.append(f"Swapped scenes {a + 1} and {b + 1}")
            continue
        if m := re.search(rf"move\s+(?:the\s+)?{SCENE}\s*(\d+)\s+to\s+(?:the\s+)?(start|beginning|front|end|last|(?:position|{SCENE})\s*(\d+))", c):
            a = int(m[1]) - 1
            if 0 <= a < n:
                s = sc.pop(a)
                dest = 0 if m[2] in ("start", "beginning", "front") else n - 1 if m[2] in ("end", "last") else int(m[3]) - 1
                sc.insert(max(0, min(dest, n - 1)), s)
                changes.append(f"Moved scene {a + 1} to position {max(0, min(dest, n - 1)) + 1}")
            continue
        if re.search(r"reverse (?:the )?order|backwards", c):
            sc.reverse()
            changes.append("Reversed the scene order")
            continue
        if re.search(r"shuffle|random order", c):
            import random

            random.shuffle(sc)
            changes.append("Shuffled the scenes")
            continue
        if re.search(r"\b(duplicate|repeat)\b", c) and tg:
            for i in reversed(tg):
                sc.insert(i + 1, dict(sc[i], motion=MOTION_CYCLE[(MOTION_CYCLE.index(sc[i]["motion"]) + 1) % 6] if sc[i]["motion"] in MOTION_CYCLE else "zoom_out"))
            changes.append(f"Duplicated scene {names}")
            continue
        # ---------- captions / look / sound effects / music mood
        if re.search(r"\b(captions?|subtitles?)\b", c) and re.search(r"word[\s-]*by[\s-]*word|karaoke|animated|tiktok|instagram|"
                                                                     r"\b(no|remove|hide|without|turn off|disable|add|enable|turn on|show)\b", c) \
                and not re.search(r"\x00|\bto\b|\bscene\s*\d", c):
            plan["captions"] = "off" if re.search(r"\b(no|remove|hide|without|turn off|disable)\b", c) else "karaoke"
            changes.append("Word-by-word captions " + ("off" if plan["captions"] == "off" else "on"))
            continue
        if re.search(r"filmography|film look|movie look|more cinematic|cinematic (?:style|feel|vibe|video|reel)|like a (?:film|movie)|documentary style", c):
            plan["look"] = {"letterbox": True, "grain": True}
            plan["filter"] = "cinematic"
            for s in sc:
                s["filter"] = "cinematic"
                if s["transition"] not in ("none",):
                    s["transition"] = "fadeblack" if s is not sc[0] else s["transition"]
            plan.setdefault("music", {})
            if not plan["music"].get("asset_id"):
                plan["music"]["generate"] = "cinematic"
            changes.append("Cinematic film look: black bars, film grain, cinematic grade, fade-to-black cuts, cinematic score")
            continue
        if re.search(r"letter\s*box|black bars|cinema(?:tic)? bars|widescreen bars", c):
            plan.setdefault("look", {})["letterbox"] = not re.search(r"\b(no|remove|without|turn off|disable)\b", c)
            changes.append("Cinematic bars " + ("on" if plan["look"]["letterbox"] else "off"))
            continue
        if re.search(r"\bgrain\b", c):
            plan.setdefault("look", {})["grain"] = not re.search(r"\b(no|remove|without|turn off|disable)\b", c)
            changes.append("Film grain " + ("on" if plan["look"]["grain"] else "off"))
            continue
        if re.search(r"sound effects?|\bsfx\b|whoosh", c):
            plan["sfx"] = not re.search(r"\b(no|remove|without|turn off|disable|mute)\b", c)
            changes.append("Sound effects " + ("on" if plan["sfx"] else "off"))
            continue
        if m := re.search(r"\b(cinematic|epic|upbeat|happy|energetic|calm|chill|relaxing|soft|dramatic|tense|dark|suspense|funny|quirky|comedic|playful)\s+"
                          r"(?:background\s+)?(music|soundtrack|song|track|beat|bgm|score)", c):
            mood = {"epic": "cinematic", "happy": "upbeat", "energetic": "upbeat", "chill": "calm", "relaxing": "calm", "soft": "calm",
                    "tense": "dramatic", "dark": "dramatic", "suspense": "dramatic", "funny": "quirky", "comedic": "quirky",
                    "playful": "quirky"}.get(m[1], m[1])
            plan["music"] = {**(plan.get("music") or {}), "asset_id": None, "generate": mood}
            changes.append(f"Soundtrack: composed {mood} music")
            continue
        # ---------- cartoon skit ("add a scene where a hiring platform logo kills the ATS")
        if re.search(r"\b(scene|skit|animation|cartoon|clip)\b", c) and re.search(r"\b(add|insert|include|put|make|create|replace|start|end)\b", c):
            from .skits import parse, skit

            raw = re.sub(r"\x00(\d+)\x00", lambda q: quotes[int(q[1])], clause)
            body = re.split(r"(?i)\b(?:where|in which|of|showing|with|about)\b", raw, maxsplit=1)
            res = skit(body[1]) if len(body) > 1 and parse(body[1]) else None
            if res:
                spec, beats, title, _ = res
                new = _src_scene({"type": "animation", **spec}, len(sc), "zoomin")
                new.update(duration=8.2, motion="static", narration=beats[1])
                if re.search(r"\breplace\b", c) and tg:
                    for i in tg:
                        sc[i] = dict(new)
                    changes.append(f"Scene {names} -> cartoon skit: {title}")
                else:
                    changes.append(f"Added a cartoon skit ({title}) {_insert(sc, [new], c, tg)}")
                continue
        # ---------- web media ("add a photo of the eiffel tower at the end", "replace scene 2 with a video of waves")
        m = re.search(r"\b(photos?|pictures?|images?|shots?|clips?|videos?|footage)\s+(?:of|showing|from)\s+(?:an?\s+|the\s+|some\s+)?(.+?)"
                      rf"(?=\s+(?:at|to)\s+the\s+(?:start|beginning|front|end)\b|\s+(?:after|before|in|on)\s+{SCENE}|\s+(?:at|to)\s+the\s+end|$)", c)
        if (m and re.search(r"\b(add|insert|include|put|append|replace|use|show|swap|need|want)\b", c)
                and not re.search(r"\b(selected|these|this|my|uploaded)\b", c)):
            media = "video" if m[1].startswith(("clip", "video", "footage")) else "photo"
            src = {"type": "stock", "query": m[2].strip(" ."), "media": media}
            if re.search(r"\breplace|swap\b", c) and tg:
                for i in tg:
                    sc[i].pop("asset_id", None)
                    sc[i].update(source=dict(src), start=0)
                changes.append(f"Scene {names}: new {media} of '{src['query']}' from the web")
            else:
                where = _insert(sc, [_src_scene(src, len(sc), common_t)], c, tg)
                changes.append(f"Added a {media} of '{src['query']}' {where}")
            continue
        # ---------- designed cards ("add an end card saying Follow for more", "add a stat card 22,000 workers")
        if (m := re.search(r"\b(title|intro|stat|number|fact|quote|list|bullet|text|end|outro|closing|cta|call to action)\s*(?:card|slide|screen|page)s?\b", c)) \
                and re.search(r"\b(add|insert|put|include|append|replace|use|make|create|start|end|finish|open)\b", c):
            layout = {"intro": "title", "number": "stat", "fact": "stat", "bullet": "list"}.get(m[1], m[1])
            layout = layout if layout in ("title", "stat", "quote", "list") else "text"
            qm = re.search(r"\x00(\d+)\x00", clause)
            val = quotes[int(qm[1])] if qm else (re.search(r"(?:card|slide|screen|page)s?\b\s*(?:saying|that says|says|reading|with|of|:)?\s*(.*)$", clause, re.I) or [None, ""])[1]
            val = re.sub(rf"\s+(?:at|to)\s+the\s+(?:start|beginning|end)\b.*$|\s+(?:after|before)\s+{SCENE}.*$", "", val or "", flags=re.I).strip()
            if not val:
                val = plan.get("title", "") if layout == "title" else "Thanks for watching"
            card = _card(layout, val)
            if re.search(r"\breplace\b", c) and tg:
                for i in tg:
                    sc[i].pop("asset_id", None)
                    sc[i].update(source=dict(card), text="")
                changes.append(f"Scene {names} -> {layout} card")
            else:
                c2 = c + (" start" if m[1] in ("title", "intro") and not tg else "")
                changes.append(f"Added a {layout} card {_insert(sc, [_src_scene(card, len(sc), common_t)], c2, tg)}: \"{val}\"")
            continue
        if re.search(r"\breplace\b", c) and tg and not re.search(r"\b(text|caption|title|music|song)\b", c):
            if not sel_visual:
                raise ValueError("Select the photo/video to use in the library first, then ask to replace the scene.")
            for k, i in enumerate(tg):
                a = sel_visual[k % len(sel_visual)]
                sc[i].update(asset_id=a["id"], start=0)
                sc[i].pop("source", None)
            changes.append(f"Replaced scene {names} with {', '.join(a['name'] for a in sel_visual[:len(tg)])}")
            continue
        if (re.search(r"\b(add|include|insert|append|put in)\b", c)
                and re.search(r"\b(selected|new|these|this|photos?|images?|pictures?|videos?|clips?|files?|media|footage)\b", c)
                and not re.search(r"slow|text|caption|title|voice|narrat|music|song|transition|filter|zoom|pan|effect|look|audio|sound", c)):
            if not sel_visual:
                raise ValueError("Select the photos/videos to add in the library (click them) first.")
            used = {s.get("asset_id") for s in sc}
            new = [a for a in sel_visual if a["id"] not in used] or sel_visual
            items = [_new_scene(a, len(sc) + k, common_t) for k, a in enumerate(new)]
            if re.search(r"\b(start|beginning|front|first)\b", c):
                sc[0:0] = items
                where = "at the start"
            elif tg:
                sc[tg[0] + 1:tg[0] + 1] = items
                where = f"after scene {tg[0] + 1}"
            else:
                sc.extend(items)
                where = "at the end"
            changes.append(f"Added {len(items)} scene(s) {where}")
            continue
        if (re.search(r"\b(remove|delete|drop|cut|cut out|get rid of|skip)\b", c) and tg and not re.search(r"hard|jump", c)
                and not re.search(r"\b(text|captions?|title|words|music|song|voice|narration|filter|transitions?|audio|sound|motion|zoom)\b", c)):
            for i in reversed(tg):
                sc.pop(i)
            changes.append(f"Removed scene {names}")
            continue

        # ---------- clip audio
        if re.search(r"(original|clip|video|camera|natural)\s*(audio|sound)", c):
            keep = not re.search(r"\b(mute|remove|no|turn off|silence|without|drop)\b", c)
            vids = [s for s in on() if by_id.get(s.get("asset_id"), {}).get("kind") == "video"]
            for s in vids:
                s["keep_audio"] = keep
            changes.append(f"{'Kept' if keep else 'Muted'} original clip sound on {len(vids)} clip(s)")
            continue

        # ---------- music
        if re.search(r"\b(music|song|soundtrack|track|bgm|background audio|beat)\b", c):
            mus = plan.setdefault("music", {"asset_id": None, "volume": 0.35})
            audio = [a for a in assets if a["kind"] == "audio"]
            if re.search(r"\b(remove|no|mute|without|turn off|drop|delete|stop)\b", c):
                mus["asset_id"] = None
                changes.append("Removed the music")
            elif m := re.search(r"(\d+)\s*%", c):
                mus["volume"] = min(1, int(m[1]) / 100)
                changes.append(f"Music volume set to {m[1]}%")
            elif re.search(r"\b(louder|increase|raise|higher|boost|up)\b", c):
                mus["volume"] = min(1, max(0.1, mus.get("volume", 0.35) * 1.5))
                changes.append("Music louder")
            elif re.search(r"\b(quieter|lower|softer|reduce|decrease|down)\b", c):
                mus["volume"] = mus.get("volume", 0.35) * 0.6
                changes.append("Music quieter")
            else:
                if not audio:
                    raise ValueError("Upload a music file (mp3/wav/m4a) to the library first.")
                pick = next((a for a in sel if a["kind"] == "audio"), None)
                pick = pick or next((a for a in audio if any(w in a["name"].lower() for w in re.findall(r"[a-z0-9]{3,}", c)
                                                             if w not in ("music", "song", "use", "change", "track", "add", "the", "with"))), None)
                if not pick:
                    ids = [a["id"] for a in audio]
                    cur = mus.get("asset_id")
                    pick = audio[(ids.index(cur) + 1) % len(audio)] if cur in ids else audio[0]
                mus["asset_id"] = pick["id"]
                changes.append(f"Music: {pick['name']}")
            continue

        # ---------- voiceover
        if re.search(r"voice\s*-?over|narrat|\bvoice\b|\bspeak|\bvo\b|\bnarrator\b", c):
            vo = plan.setdefault("voiceover", {"enabled": False, "voice": "", "rate": 0})
            voices = list(tts.list_voices())
            before = len(changes)
            if re.search(r"\b(remove|no|without|turn off|disable|mute|stop|drop|delete)\b", c):
                vo["enabled"] = False
                changes.append("Voiceover off")
                continue
            if quoted and tg or (val and tg and re.search(r"narrat|say", c)):
                for s in on():
                    s["narration"] = val
                vo["enabled"] = True
                changes.append(f"Narration for scene {names}: \"{val}\"")
                continue
            if re.search(r"\bfemale|woman|girl|lady\b", c) or re.search(r"\b(male|man|guy)\b", c):
                female = bool(re.search(r"\bfemale|woman|girl|lady\b", c))
                names_f = ("zira", "hazel", "susan", "heera", "aria", "jenny", "eva", "catherine", "linda")
                cand = [v for v in voices if any(f in v.lower() for f in names_f) == female]
                if cand:
                    vo["voice"] = cand[0]
                    changes.append(f"Voice: {cand[0]}")
            for v in voices:
                if any(w in c for w in v.lower().replace("microsoft", "").split() if len(w) > 3 and w != "desktop"):
                    vo["voice"] = v
                    changes.append(f"Voice: {v}")
                    break
            if re.search(r"\b(faster|quicker|speed up)\b", c):
                vo["rate"] = min(5, vo.get("rate", 0) + 2)
                changes.append("Voice speaks faster")
            elif re.search(r"\b(slower|slow down)\b", c):
                vo["rate"] = max(-5, vo.get("rate", 0) - 2)
                changes.append("Voice speaks slower")
            if re.search(r"\b(add|enable|turn on|use|with|include|want)\b", c) or len(changes) == before:
                vo["enabled"] = True
                filled = 0
                for s in sc:
                    if not s.get("narration") and s.get("text"):
                        s["narration"] = s["text"]
                        filled += 1
                if not any(s.get("narration") for s in sc):
                    from .planner import _sentences
                    from .sourcing import subject_of, wikipedia_research

                    lines = [l for l in _sentences(wikipedia_research(subject_of(plan.get("title", "")), lambda m: None))
                             if 4 <= len(l.split()) <= 22][:len(sc)]
                    for s, l in zip(sc, lines):
                        s["narration"] = l
                        filled += 1
                    if not lines:
                        raise ValueError("Voiceover needs words to say: write a Script, or ask e.g. narration for scene 1: \"...\"")
                    changes.append(f"Wrote narration for {filled} scene(s) from Wikipedia")
                changes.append("Voiceover on" + (f" (narrating {filled} scene(s))" if filled else ""))
            continue

        # ---------- transitions
        if re.search(r"transition|\bcuts?\b|cross ?fade|dissolve|fade to black|dip to black|\bflash\b", c):
            targets = [sc[i] for i in tg if i > 0] if tg else sc[1:]
            kind = next((t for p, t in TRANS_WORDS if re.search(p, c)), None)
            if kind:
                for s in targets:
                    s["transition"] = kind
                changes.append(f"Transitions -> {kind}" + (f" (scene {names})" if tg else ""))
            if re.search(r"\b(faster|quicker|shorter|snappier)\b", c):
                for s in targets:
                    s["transition_duration"] = max(0.15, s["transition_duration"] * 0.6)
                changes.append("Shorter transitions")
            elif re.search(r"\b(slower|longer|smoother|softer)\b", c):
                for s in targets:
                    s["transition_duration"] = min(1.4, s["transition_duration"] * 1.5)
                changes.append("Longer transitions")
            continue

        applied = False
        # ---------- text
        if re.search(r"\b(text|texts|captions?|titles?|subtitles?|words|heading|headline|font|lettering)\b", c):
            if re.search(r"\b(remove|delete|no|hide|clear|without|drop)\b", c):
                for s in on():
                    s["text"] = ""
                changes.append(f"Removed text" + (f" on scene {names}" if tg else " everywhere"))
                continue
            consumed = False
            if m := re.search(r"\b(top|cent(?:er|re)|middle|bottom|lower|upper)\b", c):
                pos = {"centre": "center", "middle": "center", "lower": "bottom", "upper": "top"}.get(m[1], m[1])
                for s in on():
                    s["text_position"] = pos
                changes.append(f"Text position -> {pos}")
                consumed = True
            if m := re.search(r"\b(neon|glow|box|boxed|minimal|clean|simple|bold|outline)\b", c):
                plan["text_style"] = {"glow": "neon", "boxed": "box", "clean": "minimal", "simple": "minimal", "outline": "bold"}.get(m[1], m[1])
                changes.append(f"Text style -> {plan['text_style']}")
                consumed = True
            if m := re.search(rf"\b({'|'.join(COLORS)})\b", c):
                plan["accent_color"] = COLORS[m[1]]
                if plan.get("text_style") in ("bold", "minimal") and not re.search(r"\bbox|neon|glow", c):
                    plan["text_style"] = "box"
                changes.append(f"Text colour -> {m[1]}")
                consumed = True
            if val and (quoted or not consumed) and re.search(r"\b(change|set|make|replace|put|add|write|say|update|edit|rename|use)\b|:", c):
                targets = tg or [0]
                for i in targets:
                    sc[i]["text"] = val
                changes.append(f"Text on scene {', '.join(str(i + 1) for i in targets)}: \"{val}\"")
                if not quoted:
                    continue
            applied = consumed or bool(val)

        # ---------- format
        m = re.search(r"(square|1:1|4:5|16:9|9:16|horizontal|landscape|widescreen|vertical|portrait)", c)
        if not m and re.search(r"\b(format|aspect|ratio|for|convert)\b", c):
            m = re.search(r"\b(youtube|tiktok|reels?|shorts|stories|instagram)\b", c)
        if m:
            word = m[1]
            plan["aspect"] = {"square": "1:1", "instagram": "4:5", "portrait": "4:5", "horizontal": "16:9", "landscape": "16:9",
                              "widescreen": "16:9", "youtube": "16:9"}.get(word, word if ":" in word else "9:16")
            changes.append(f"Format -> {plan['aspect']}")
            applied = True

        # ---------- colour look
        for p, f in FILTER_WORDS:
            if re.search(p, c):
                for s in on():
                    s["filter"] = f
                if not tg:
                    plan["filter"] = f
                changes.append(f"Look -> {f}" + (f" (scene {names})" if tg else ""))
                applied = True
                break

        # ---------- camera motion
        if re.search(r"ken burns|more (?:motion|movement|dynamic)", c):
            for k, s in enumerate(on()):
                s["motion"] = MOTION_CYCLE[k % len(MOTION_CYCLE)]
            changes.append("Varied camera motion")
            applied = True
        else:
            for p, mo in MOTION_WORDS:
                if re.search(p, c):
                    for s in on():
                        s["motion"] = mo
                    changes.append(f"Camera -> {mo.replace('_', ' ')}" + (f" (scene {names})" if tg else ""))
                    applied = True
                    break

        # ---------- playback speed of clips
        speed = None
        if re.search(r"slow[\s-]?mo(?:tion)?", c):
            speed = 0.5
        elif m := re.search(r"(\d(?:\.\d+)?)\s*x\b", c):
            speed = float(m[1])
        elif re.search(r"time[\s-]?lapse|fast[\s-]?forward|speed up the (?:clip|video|footage)", c):
            speed = 2.0
        elif re.search(r"normal speed|real[\s-]?time", c):
            speed = 1.0
        if speed:
            vids = [s for s in on() if by_id.get(s.get("asset_id"), {}).get("kind") == "video"]
            if not vids:
                raise ValueError("Speed changes only apply to video clips - none in " + (f"scene {names}" if tg else "this video"))
            for s in vids:
                s["speed"] = speed
            changes.append(f"Clip speed {speed}x on {len(vids)} clip(s)")
            applied = True

        # ---------- duration / pacing
        if m := re.search(r"(\d+(?:\.\d+)?)\s*(?:s|sec|secs|seconds?)\b", c):
            secs = float(m[1])
            if tg:
                for s in on():
                    s["duration"] = secs
                changes.append(f"Scene {names} -> {secs:g}s")
            else:
                if re.search(r"\b(under|less than|max|maximum|below)\b", c):
                    secs *= 0.95
                total = sum(s["duration"] for s in sc) - sum(s["transition_duration"] for s in sc[1:])
                f = secs / max(total, 0.1)
                for s in sc:
                    s["duration"] = max(0.6, s["duration"] * f)
                changes.append(f"Total length -> ~{secs:g}s")
            applied = True
        elif re.search(r"\b(faster|quicker|snappier|speed (?:it )?up|more energetic|shorter|tighter|punchier|fast[- ]paced)\b", c) and not speed:
            for s in on():
                s["duration"] = max(0.6, s["duration"] * 0.7)
                s["transition_duration"] = max(0.15, s["transition_duration"] * 0.7)
            changes.append("Faster pacing" + (f" (scene {names})" if tg else ""))
            applied = True
        elif re.search(r"\b(slower|longer|calmer|more relaxed|slow (?:it )?down|breathe)\b", c):
            for s in on():
                s["duration"] = s["duration"] * 1.35
            changes.append("Slower pacing" + (f" (scene {names})" if tg else ""))
            applied = True

        if not applied:
            raise ValueError(f"Didn't understand: \"{clause.strip()}\". " + HELP.split(". ", 1)[1])

    if not sc:
        raise ValueError("That would remove every scene.")
    if not changes:
        raise ValueError(HELP)
    return plan, changes
