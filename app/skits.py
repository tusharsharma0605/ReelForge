"""Built-in skit writer: turns prompts like 'a hiring platform logo killing an ATS' into a cartoon fight scene."""
import re

VERBS = (r"killing|kills|kill|beating|beats|beat|defeating|defeats|defeat|destroying|destroys|destroy|vs\.?|versus|"
         r"fighting|fights|fight|punching|punches|punch|crushing|crushes|crush|replacing|replaces|smashing|smashes|"
         r"knocking out|knocks out|knock out|roasting|roasts|taking down|takes down|beating up|beats up|vs")
PERSON = r"\b(man|woman|guy|girl|boy|hero|recruiter|candidate|employee|boss|manager|developer|student|hr|ceo|intern|founder|person|kid)\b"
MACHINE = r"\b(ats|ai|bot|robot|algorithm|system|software|machine|tracking|filter|automation|spam|virus|bug)\b"
HIRING = r"hir|resume|cv\b|job|candidate|recruit|interview|ats\b|talent|career"


def _clean(name):
    name = re.sub(r"(?i)^.*?\b(where|showing|in which|about|of how|when)\s+", "", name.strip())
    name = re.sub(r"(?i)^(make|create|generate)\s+(an?\s+)?(video|reel|short|clip|skit|animation|cartoon)s?\s+(of|about|with)?\s*", "", name)
    name = re.sub(r"(?i)^(an?|the|some)\s+", "", name)
    name = re.sub(r"(?i)^(cartoon\s+|animated\s+)?(logo|mascot|character|brand|company|icon)\s+(of|for|called|named)\s+(an?\s+|the\s+)?", "", name)
    name = re.sub(r"(?i)\s+(logo|mascot|brand)$", "", name)
    name = re.split(r"(?i)[,.;!?]| and | with | in | while | because | for | using | on | at | after | before | then ", name)[0]
    return " ".join(name.split()[:3]).strip(" '\"")


def _label(name):
    return name.upper() if len(name) <= 4 else " ".join(w if w.isupper() else w.capitalize() for w in name.split())


def parse(prompt):
    m = re.search(rf"(?i)(.+?)\s+(?:is\s+|are\s+)?(?:{VERBS})\s+(?:an?\s+|the\s+)?(.+)", prompt.strip())
    if not m:
        return None
    hero, villain = _clean(m[1]), _clean(m[2])
    if not hero or not villain or len(hero) > 30 or len(villain) > 30:
        return None
    return hero, villain


def _kind(name, raw, default):
    if re.search(MACHINE, name.lower()):
        return "robot"
    if re.search(PERSON, name.lower()):
        return "character"
    if re.search(r"logo|brand|platform|app|company|startup|\.com", (raw + " " + name).lower()):
        return "logo"
    return default


def skit(prompt):
    """-> (anim_spec, beats) or None. beats: narration lines for title / skit / outro."""
    p = parse(prompt)
    if not p:
        return None
    hero, villain = p
    H, V = _label(hero), _label(villain)
    hk, vk = _kind(hero, prompt, "logo"), _kind(villain, prompt, "robot")
    hiring = bool(re.search(HIRING, prompt.lower()))
    taunt = "Missing ONE keyword? REJECTED!" if hiring else "Nobody can stop me!"
    comeback = "Real skills beat keywords!" if hiring else "Hold my coffee."
    actors = [
        {"id": "villain", "kind": vk, "label": V, "color": "#5A6472" if vk == "robot" else "#E63946", "x": 0.68, "y": 0.6,
         "expression": "evil", "facing": -1},
        {"id": "hero", "kind": hk, "label": H, "color": "#0A66C2", "x": 0.3, "y": 0.6, "expression": "angry", "limbs": True},
    ]
    actions = [
        {"t": 0.0, "actor": "villain", "do": "pop_in"},
        {"t": 0.5, "actor": "villain", "do": "say", "text": taunt, "dur": 2.0},
    ]
    if hiring:
        actors.append({"id": "cv", "kind": "icon", "icon": "document", "color": "#7C5CFF", "x": 0.5, "y": 0.27, "size": 0.6,
                       "face": True, "expression": "scared"})
        actions += [{"t": 0.3, "actor": "cv", "do": "drop_in"}, {"t": 2.0, "actor": "cv", "do": "cry", "dur": 1.2}]
    actions += [
        {"t": 2.7, "actor": "hero", "do": "enter_left"},
        {"t": 3.4, "actor": "hero", "do": "shout", "text": comeback, "dur": 1.3},
        {"t": 4.8, "actor": "hero", "do": "punch", "target": "villain"},
        {"t": 5.05, "actor": "villain", "do": "hit"},
        {"t": 5.6, "actor": "villain", "do": "explode"},
        {"t": 6.3, "actor": "hero", "do": "celebrate", "dur": 1.6},
    ]
    if hiring:
        actions.append({"t": 6.3, "actor": "cv", "do": "expression", "value": "happy"})
        actions.append({"t": 6.4, "actor": "cv", "do": "jump"})
    spec = {"background": {"style": "arena"}, "actors": actors, "actions": actions,
            "fx": [{"t": 5.6, "kind": "explosion", "x": 0.68, "y": 0.52}, {"t": 6.3, "kind": "confetti"},
                   {"t": 6.4, "kind": "text_pop", "x": 0.5, "y": 0.16, "text": "K.O.!", "dur": 1.5}],
            "camera": {"zoom": "in"}}
    if hiring:
        beats = [f"What happens when {H} meets the {V}?",
                 f"The {V} rejects great people over one missing keyword. Then {H} shows up.",
                 f"Hire for skills, not keywords. Follow for more."]
        outro = f"{H}: hire for skills, not keywords"
    else:
        beats = [f"{H} versus {V}.", f"{V} thought it was unstoppable. {H} had other plans.", "Follow for more."]
        outro = f"Team {H} wins"
    return spec, beats, f"{H} vs {V}", outro
