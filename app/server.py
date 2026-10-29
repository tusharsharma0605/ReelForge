import json
import logging
import os
import shutil
import threading
import time
import traceback
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import planner, renderer, sourcing, tts
from .media import extract_text, kind_of, load_image, make_thumbnail, probe, run_ffmpeg

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
UPLOADS, THUMBS, OUTPUTS, WORK = (DATA / d for d in ("uploads", "thumbs", "outputs", "work"))
for d in (UPLOADS, THUMBS, OUTPUTS, WORK):
    d.mkdir(parents=True, exist_ok=True)
ASSETS_FILE = DATA / "assets.json"
SETTINGS_FILE = DATA / "settings.json"
DEFAULT_SETTINGS = {"anthropic_api_key": "", "workspace_id": "", "model": planner.DEFAULT_MODEL, "pexels_api_key": "", "auto_clean": True}
RETIRED_MODELS = {"claude-sonnet-4-5"}

log = logging.getLogger("reelforge")
app = FastAPI(title="ReelForge")
_lock = threading.Lock()
_render_lock = threading.Lock()
JOBS: dict[str, dict] = {}


# ---------------------------------------------------------------- storage
def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def get_assets() -> list[dict]:
    return load_json(ASSETS_FILE, [])


def get_settings() -> dict:
    s = {**DEFAULT_SETTINGS, **load_json(SETTINGS_FILE, {})}
    if not s["anthropic_api_key"]:
        s["anthropic_api_key"] = os.environ.get("ANTHROPIC_API_KEY", "")
    if s["model"] in RETIRED_MODELS or not s["model"]:
        s["model"] = planner.DEFAULT_MODEL
    return s


def is_generated(a):
    """Web downloads, designed cards and animations (anything the app made/fetched itself, not user uploads)."""
    return a.get("source") not in (None, "upload")


def remove_assets(ids):
    ids = set(ids)
    if not ids:
        return 0
    with _lock:
        assets = get_assets()
        for a in assets:
            if a["id"] in ids:
                Path(a["path"]).unlink(missing_ok=True)
                (THUMBS / f"{a['id']}.jpg").unlink(missing_ok=True)
        save_json(ASSETS_FILE, [a for a in assets if a["id"] not in ids])
    return len(ids)


def _size(paths):
    return sum(p.stat().st_size for p in paths if p.is_file())


def public(a):
    return {k: v for k, v in a.items() if k != "path"} | {"thumb": f"/api/assets/{a['id']}/thumb" if a.get("has_thumb") else None}


# ---------------------------------------------------------------- assets
@app.get("/api/assets")
def list_assets():
    return [public(a) for a in get_assets()]


class Store:
    """Asset registry used by uploads and by the web/design media finder."""

    @staticmethod
    def new_path(ext):
        aid = uuid.uuid4().hex[:8]
        return aid, UPLOADS / f"{aid}{ext.lower()}"

    @staticmethod
    def ids():
        return {a["id"] for a in get_assets()}

    @staticmethod
    def get(aid):
        return next((a for a in get_assets() if a["id"] == aid), None) if aid else None

    @staticmethod
    def build(aid, dest: Path, name, extra=None):
        kind = (extra or {}).get("kind") or kind_of(dest.name)
        a = {"id": aid, "name": name, "kind": kind, "path": str(dest), "size": dest.stat().st_size,
             "duration": 0.0, "width": 0, "height": 0, "has_audio": False, "has_thumb": False, "added": time.time(), **(extra or {})}
        try:
            if kind == "anim":
                from .animator import preview

                preview(a["anim"], 270, 480, THUMBS / f"{aid}.jpg")
                a["has_thumb"] = True
                return a
            if kind == "image":
                a["width"], a["height"] = load_image(dest).size
            elif kind in ("video", "audio"):
                a.update(probe(dest))
            a["has_thumb"] = make_thumbnail(dest, kind, a, THUMBS / f"{aid}.jpg")
        except Exception as e:
            log.warning("asset processing failed for %s: %s", name, e)
            if kind == "image":
                a["kind"] = "other"
        return a

    @classmethod
    def register(cls, aid, dest, name, extra=None):
        a = cls.build(aid, dest, name, extra)
        with _lock:
            save_json(ASSETS_FILE, get_assets() + [a])
        return a


@app.post("/api/assets")
def upload(files: list[UploadFile] = File(...)):
    added = []
    for f in files:
        name = Path(f.filename or "file").name
        aid, dest = Store.new_path(Path(name).suffix)
        with open(dest, "wb") as out:
            shutil.copyfileobj(f.file, out, 1024 * 1024)
        added.append(Store.build(aid, dest, name, {"source": "upload"}))
    with _lock:
        save_json(ASSETS_FILE, get_assets() + added)
    return [public(a) for a in added]


@app.get("/api/assets/{aid}/thumb")
def thumb(aid: str):
    p = THUMBS / f"{aid}.jpg"
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p)


@app.get("/api/assets/{aid}/file")
def asset_file(aid: str):
    a = next((a for a in get_assets() if a["id"] == aid), None)
    if not a:
        raise HTTPException(404)
    return FileResponse(a["path"], filename=a["name"])


@app.delete("/api/assets/{aid}")
def delete_asset(aid: str):
    with _lock:
        assets = get_assets()
        for a in assets:
            if a["id"] == aid:
                Path(a["path"]).unlink(missing_ok=True)
                (THUMBS / f"{aid}.jpg").unlink(missing_ok=True)
        save_json(ASSETS_FILE, [a for a in assets if a["id"] != aid])
    return {"ok": True}


# ---------------------------------------------------------------- settings
class SettingsIn(BaseModel):
    anthropic_api_key: str | None = None
    pexels_api_key: str | None = None
    workspace_id: str | None = None
    model: str | None = None
    auto_clean: bool | None = None


@app.get("/api/settings")
def read_settings():
    s = get_settings()
    k, p = s["anthropic_api_key"], s.get("pexels_api_key", "")
    return {"model": s["model"], "has_key": bool(k), "key_hint": f"...{k[-4:]}" if k else "",
            "has_pexels": bool(p), "pexels_hint": f"...{p[-4:]}" if p else "", "auto_clean": bool(s.get("auto_clean", True)),
            "workspace_id": s.get("workspace_id", "")}


@app.post("/api/settings")
def write_settings(body: SettingsIn):
    s = {**DEFAULT_SETTINGS, **load_json(SETTINGS_FILE, {})}
    if body.anthropic_api_key is not None:
        s["anthropic_api_key"] = body.anthropic_api_key.strip()
    if body.pexels_api_key is not None:
        s["pexels_api_key"] = body.pexels_api_key.strip()
    if body.auto_clean is not None:
        s["auto_clean"] = body.auto_clean
    if body.workspace_id is not None:
        s["workspace_id"] = body.workspace_id.strip()
    if body.model:
        s["model"] = body.model.strip()
    save_json(SETTINGS_FILE, s)
    return read_settings()


@app.post("/api/settings/test")
def test_key():
    s = get_settings()
    if not s["anthropic_api_key"]:
        return {"ok": False, "error": "No API key saved"}
    try:
        r = planner.make_client(s).messages.create(model=s["model"], max_tokens=20, messages=[{"role": "user", "content": "Reply with: OK"}])
        return {"ok": True, "model": s["model"], "reply": "".join(b.text for b in r.content if b.type == "text")[:40]}
    except Exception as e:
        msg = str(e)
        if "anthropic-workspace-id" in msg:
            msg = ("This key isn't scoped to a workspace. Paste your Workspace ID (Claude Console > Settings > Workspaces, "
                   "looks like wrkspc_...) into the Workspace ID field, or create a key inside a workspace.")
        return {"ok": False, "error": msg[:400]}


@app.get("/api/models")
def models():
    items, live = planner.list_models(get_settings())
    return {"models": items, "live": live, "current": get_settings()["model"]}


@app.get("/api/voices")
def voices():
    return list(tts.list_voices())


# ---------------------------------------------------------------- jobs
class JobIn(BaseModel):
    prompt: str = ""
    script: str = ""
    direction: str = ""
    asset_ids: list[str] = []
    aspect: str = "9:16"
    target_duration: float = 0
    voiceover: bool = False
    voice: str = ""
    voice_rate: int = 0
    text_style: str = "auto"
    music_asset_id: str | None = None
    use_ai: bool = True
    auto_media: bool = True
    research: bool = True
    captions: str = "karaoke"
    look: str = "auto"
    sfx: bool = True
    model: str = ""
    plan: dict | None = None
    edit_instruction: str = ""
    parent: str = ""


def run_job(job, req: dict):
    def jlog(msg):
        job["log"].append(f"[{time.strftime('%H:%M:%S')}] {msg}")
        log.info(msg)

    def progress(pct, msg):
        job["progress"], job["stage"] = pct, msg
        jlog(msg)

    job["status"] = "queued"
    with _render_lock:
        work = WORK / job["id"]
        try:
            job["status"] = "planning"
            progress(2, "Directing the edit")
            settings = get_settings()
            if req.get("model"):
                settings["model"] = req["model"]
            all_assets = {a["id"]: a for a in get_assets()}
            ids = req["asset_ids"] or ([] if req.get("auto_media", True) else list(all_assets))
            assets = [all_assets[i] for i in ids if i in all_assets]
            if req.get("music_asset_id") in all_assets and all_assets[req["music_asset_id"]] not in assets:
                assets.append(all_assets[req["music_asset_id"]])
            context = "\n\n".join(f"--- {a['name']} ---\n{extract_text(a['path'])}"
                                  for a in assets if a["kind"] == "text")

            def resolver(p):
                aspect = p.get("aspect") if p.get("aspect") in renderer.ASPECTS else req.get("aspect", "9:16")
                if aspect not in renderer.ASPECTS:
                    aspect = "9:16"
                for s in p.get("scenes", []):
                    a = all_assets.get(s.get("asset_id"))
                    if a and a.get("source") == "design" and a.get("aspect") != aspect:
                        s["source"] = a["card"]
                        s.pop("asset_id")
                if any(isinstance(s.get("source"), dict) and s.get("asset_id") not in all_assets for s in p.get("scenes", [])):
                    progress(6, "Collecting photos, clips & designing cards")
                finder = sourcing.Finder(settings, aspect, jlog, Store)
                p, new = sourcing.resolve(p, finder, renderer.ASPECTS[aspect], jlog, Store, aspect)
                all_assets.update({a["id"]: a for a in new})
                created.extend(a["id"] for a in new)
                return p, new

            created = []

            instruction = req.get("edit_instruction", "").strip()
            library = list(all_assets.values())
            if req.get("plan") and instruction:
                progress(3, "Applying your change")
                plan, job["director"], job["changes"] = planner.revise(req["plan"], instruction, req, library, settings, jlog, resolver)
                for c in job["changes"]:
                    jlog(f"  - {c}")
            elif req.get("plan"):
                plan, job["director"] = planner._finish(req["plan"], req, library, resolver, True), "manual"
            else:
                plan, job["director"] = planner.make_plan(req, assets, settings, context, jlog, resolver)
            if not plan["scenes"]:
                raise ValueError("The director produced no usable scenes. Try a more specific prompt.")
            job["plan"] = json.loads(json.dumps(plan))
            jlog(f"Plan ready: {len(plan['scenes'])} scenes ({job['director']} director)")
            job["status"] = "rendering"
            slug = "".join(c if c.isalnum() else "_" for c in plan["title"])[:40].strip("_") or "reel"
            out = OUTPUTS / f"{time.strftime('%Y%m%d_%H%M%S')}_{slug}{'_edit' if instruction else ''}.mp4"
            total = renderer.render(plan, all_assets, work, out, progress)
            credits = list(dict.fromkeys(all_assets[s["asset_id"]].get("credit") for s in plan["scenes"]
                                         if all_assets[s["asset_id"]].get("credit")))
            job["credits"] = credits
            if credits:
                out.with_suffix(".credits.txt").write_text("Media credits:\n" + "\n".join(credits) + "\n", encoding="utf-8")
            save_json(out.with_suffix(".json"), {"plan": job["plan"], "instruction": instruction, "changes": job.get("changes", []),
                                                 "parent": req.get("parent", ""), "credits": credits, "duration": round(total, 1),
                                                 "request": {k: v for k, v in req.items() if k != "plan"}})
            job["name"] = out.name
            try:
                run_ffmpeg(["-ss", min(1.5, total / 3), "-i", out, "-frames:v", 1, "-vf", "scale=240:-2", out.with_suffix(".jpg")])
            except Exception as e:
                log.warning("thumbnail failed: %s", e)
            if settings.get("auto_clean", True):
                temp = set(created) | {s["asset_id"] for s in plan["scenes"] if is_generated(all_assets.get(s["asset_id"], {}))}
                if remove_assets(temp):
                    jlog(f"Auto-clean: removed {len(temp)} downloaded/generated item(s) from the library (your uploads are kept)")
            job.update(status="done", output=f"/outputs/{out.name}", duration=round(total, 1))
        except Exception as e:
            log.error(traceback.format_exc())
            job.update(status="error", error=str(e))
            jlog(f"ERROR: {e}")
        finally:
            shutil.rmtree(work, ignore_errors=True)


@app.post("/api/jobs")
def create_job(body: JobIn):
    jid = uuid.uuid4().hex[:10]
    job = {"id": jid, "status": "queued", "progress": 0, "stage": "Queued", "log": [], "plan": None, "changes": [],
           "output": None, "name": None, "error": None, "created": time.time()}
    JOBS[jid] = job
    threading.Thread(target=run_job, args=(job, body.model_dump()), daemon=True).start()
    return job


@app.get("/api/jobs/{jid}")
def get_job(jid: str):
    if jid not in JOBS:
        raise HTTPException(404)
    return JOBS[jid]


@app.get("/api/outputs")
def outputs():
    items = []
    for p in sorted(OUTPUTS.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
        meta = load_json(p.with_suffix(".json"), {})
        if not p.with_suffix(".jpg").exists():
            try:
                run_ffmpeg(["-ss", 1, "-i", p, "-frames:v", 1, "-vf", "scale=240:-2", p.with_suffix(".jpg")])
            except Exception:
                pass
        items.append({"name": p.name, "url": f"/outputs/{p.name}", "size": p.stat().st_size, "duration": meta.get("duration"),
                      "thumb": f"/outputs/{p.with_suffix('.jpg').name}" if p.with_suffix(".jpg").exists() else None,
                      "created": p.stat().st_mtime, "title": (meta.get("plan") or {}).get("title", p.stem),
                      "plan": meta.get("plan"), "request": meta.get("request"), "instruction": meta.get("instruction", ""),
                      "changes": meta.get("changes", []), "parent": meta.get("parent", ""), "credits": meta.get("credits", [])})
    return items


def _delete_video(p: Path):
    for f in (p, p.with_suffix(".json"), p.with_suffix(".credits.txt"), p.with_suffix(".jpg")):
        f.unlink(missing_ok=True)


@app.delete("/api/outputs/{name}")
def delete_output(name: str):
    _delete_video(OUTPUTS / Path(name).name)
    return {"ok": True}


@app.delete("/api/outputs")
def delete_all_outputs():
    vids = list(OUTPUTS.glob("*.mp4"))
    for p in vids:
        _delete_video(p)
    return {"ok": True, "deleted": len(vids)}


@app.post("/api/cleanup")
def cleanup():
    """Remove everything the app downloaded/generated (web photos, design cards, animations) + temp work files."""
    n = remove_assets(a["id"] for a in get_assets() if is_generated(a))
    if not _render_lock.locked():
        for d in WORK.iterdir():
            shutil.rmtree(d, ignore_errors=True)
    return {"ok": True, "removed": n}


@app.get("/api/storage")
def storage():
    assets = get_assets()
    gen = [Path(a["path"]) for a in assets if is_generated(a)]
    mine = [Path(a["path"]) for a in assets if not is_generated(a)]
    return {"videos": len(list(OUTPUTS.glob("*.mp4"))), "videos_bytes": _size(OUTPUTS.iterdir()),
            "uploads": len(mine), "uploads_bytes": _size(mine), "generated": len(gen), "generated_bytes": _size(gen)}


@app.post("/api/open-folder")
def open_folder():
    os.startfile(OUTPUTS)
    return {"ok": True}


@app.post("/api/shutdown")
def shutdown():
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return {"ok": True}


@app.get("/api/health")
def health():
    return {"ok": True}


app.mount("/outputs", StaticFiles(directory=OUTPUTS), name="outputs")
app.mount("/", StaticFiles(directory=ROOT / "app" / "static", html=True), name="static")
