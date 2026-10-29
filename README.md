# ReelForge

**Type a prompt, get an Instagram-style reel.** ReelForge is a free desktop app that runs on your own Windows PC. It writes the
script, finds photos, designs title cards, animates cartoon skits, narrates with natural voices, adds word-by-word captions,
composes music and sound effects, and renders a finished MP4. You can then change the video just by typing what you want changed.

- Works **without any paid service or API key**. A Claude key is optional and makes the "AI director" much smarter.
- Everything is stored locally in the app folder. Nothing is uploaded except the web searches and voice requests listed below.

---

## What it can do

| Feature | Details |
|---|---|
| Prompt-only videos | "A 30 second reel about the history of the Taj Mahal": researches the topic, writes narration, finds photos, adds a title card |
| Your own media | Drop in photos, phone videos, music, scripts (.txt / .pdf). Select them and they are used first |
| Cartoon skits | "A funny reel where a hiring platform logo kills an ATS": 2D characters, robots, logo mascots, speech bubbles, punches, explosions |
| Designed cards | Title, big-number stat, quote, bullet list and end cards |
| Narration | Natural neural voices (free, needs internet), or offline Windows voices |
| Captions | Animated word-by-word captions synced to the voice (reel style) |
| Sound | Music composed to match the mood (cinematic, upbeat, calm, dramatic, quirky) + whooshes, hits, pops, booms, or your own music |
| Looks | Cinematic film look (black bars + film grain), colour grades, Ken Burns camera moves, 19 transitions |
| Formats | 9:16 reels/shorts, 16:9 YouTube, 1:1 square, 4:5 feed |
| Edit by prompt | "make it faster, cinematic look, change scene 1 text to 'Hello'". Every edit is saved as a new version |
| History | Gallery of all videos with play, edit, download, delete and delete all |
| Auto-clean | Downloaded photos and generated cards are removed after each video, so the folder doesn't fill up |

---

## Requirements

- **Windows 10 or 11** (uses Windows fonts and voices)
- **Python 3.10 or newer**, from <https://www.python.org/downloads/>. **Tick "Add python.exe to PATH"** in the installer.
- About **1 GB of free disk space** and an internet connection for setup
- Any normal laptop works. No graphics card is needed.

## Install

1. Get the code:
   - **With Git:** `git clone https://github.com/tusharsharma0605/ReelForge.git`
   - **Without Git:** on the GitHub page click **Code > Download ZIP**, then unzip it.
2. Open the `ReelForge` folder and double-click **`install.bat`**.
   It creates a private Python environment (`.venv`), installs everything including FFmpeg (5-10 minutes the first time) and puts a
   **ReelForge** shortcut on your Desktop.
3. Double-click the **ReelForge** Desktop icon (or `ReelForge.bat`). Your browser opens at <http://127.0.0.1:8765>.
   The first start can take about 20 seconds.

To stop the app, click **Quit** in the top-right corner of the page.

---

## How to use

### 1. Make a video from just a prompt
1. Leave the media library empty (or with nothing selected).
2. Type a prompt, for example:
   - `A 30 second cinematic documentary about how hard drives are made`
   - `A funny reel where a hiring platform logo kills an ATS`
   - `5 surprising facts about black holes`
3. Pick a format, length, voice, captions style, look, and so on (the defaults are fine), then click **Generate video**.

### 2. Make a video from your own photos and clips
1. Drag files into the **Media library** (photos, videos, music, .txt/.pdf scripts).
2. Click the items to use. The numbers show the order.
3. Write a prompt (and optionally a script), then click **Generate video**.

### 3. Change a video by typing
Under the player, use **Edit with a prompt**. Examples (you can combine several in one sentence):

```
make it faster                      make it 15 seconds              make scene 2 5 seconds
remove scene 3                      swap scenes 1 and 2             move scene 4 to the start
change scene 1 text to "Goa 2026"   move text to the top            neon captions / yellow captions
cinematic look / filmography look   black and white                 hard cuts / fade transitions
slow motion on the clip             zoom in on scene 2              make it square / convert for youtube
dramatic music / funny music        music quieter / no music        no sound effects
add voiceover / female voice        word by word captions           no captions
add a photo of a city at night at the end
add an end card saying Follow for more
add a scene where a hiring platform logo kills the ATS
add the selected photos at the end  replace scene 2 with the selected photo
```

Each edit creates a new version in **History**, so the original is never lost. **Edit plan (advanced)** lets you edit the
raw scene list (JSON) directly.

### 4. History and storage
- The **History** button shows all videos with play, edit, download and delete options, plus **Delete all**.
- **Clean up** (above the library) removes downloaded and generated items. Your uploads and videos are kept.
- Videos are saved in `ReelForge\data\outputs` (**Open output folder** button). If web photos were used, a
  `.credits.txt` file sits next to the video. Please credit the photographers when you post (most images are Creative Commons).

---

## Optional: add your own keys (Settings)

ReelForge works without any keys. You can add your own in **Settings**. They are saved only on your PC
(`data\settings.json`) and are never included when you share the app.

| Key | What it adds | Cost |
|---|---|---|
| **Claude API key** (Anthropic) | A real AI director: writes better scripts, looks at your photos, researches with web search, writes cartoon skits, and understands any edit request | Paid per use. Get a key at <https://console.anthropic.com> |
| **Workspace ID** | Only needed if your Claude key is *not scoped to a workspace* (you'll see an error saying so). Find it in Claude Console > Settings > Workspaces | - |
| **Pexels API key** | High-quality stock **video clips** and photos | Free at <https://www.pexels.com/api/> |

After adding a Claude key, click **Test key**. Then choose a **model** (the **Refresh** button loads the list your key can use):
- *Sonnet*: best balance (recommended)
- *Opus*: smarter, slower
- *Fable*: deepest reasoning, slowest and most expensive
- *Haiku*: fastest and cheapest

You can also pick a model for a single video in the Create panel.

You can also set the key with the environment variable `ANTHROPIC_API_KEY` instead of the Settings screen.

---

## What goes over the internet

| Service | Used for | Can I avoid it? |
|---|---|---|
| Wikipedia / Wikimedia Commons / Openverse | Topic research and free photos | Untick "Find photos" and "Research", or use your own media |
| Microsoft Edge read-aloud voices | Natural narration | Pick an "Offline:" voice in the Voice list |
| Anthropic (only if you add a key) | AI director | Don't add a key |
| Pexels (only if you add a key) | Stock clips/photos | Don't add a key |

Music, sound effects, cards, animations and rendering are all done locally on your PC.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `install.bat` says Python not found | Install Python from python.org and tick **Add python.exe to PATH**, then run `install.bat` again |
| Browser doesn't open | Go to <http://127.0.0.1:8765> yourself. It can take about 20 seconds the first time |
| "Neural voice unavailable" in the log | No internet connection. The offline Windows voice is used automatically |
| Claude errors about `anthropic-workspace-id` | Paste your Workspace ID in Settings, or create the key inside a workspace |
| A video failed | The error is shown in the log box. Details are in `data\app.log` |
| Port 8765 already in use | ReelForge is already running. The icon just opens it again |
| Start fresh | Close the app and delete the `data` folder (this removes your videos, uploads and keys) |

---

## Sharing ReelForge with others

- **GitHub:** the included `.gitignore` already excludes your `data` folder (keys, videos, uploads) and `.venv`.
  Upload the folder with Git, GitHub Desktop or the GitHub website ("Add file > Upload files").
- **ZIP:** double-click `make_share_zip.bat`. It creates `ReelForge-share.zip` containing only the app files, with no keys and no videos.

The person you share it with just runs `install.bat` and then uses their own optional keys.

---

## Project layout (for developers)

```
ReelForge/
  install.bat / ReelForge.bat   setup and launcher (Windows)
  launcher.pyw                  starts the local server and opens the browser
  make_shortcut.py              creates the icon and Desktop shortcut
  app/
    server.py      FastAPI web server, jobs, library, history, settings
    planner.py     the "director": Claude prompt + built-in rule-based director
    editor.py      built-in prompt editor ("make it faster", "remove scene 2", ...)
    sourcing.py    Wikipedia research and free photo/clip search
    designer.py    designed title/stat/quote/list cards
    animator.py    2D cartoon engine (characters, robots, logos, bubbles, effects)
    skits.py       built-in skit writer ("X kills Y")
    renderer.py    FFmpeg rendering, captions, transitions, film look, audio mix
    audio.py       composed music and sound effects (numpy)
    tts.py         neural and offline voices with word timings
    media.py       probing, thumbnails, FFmpeg helpers
    static/        the web interface (index.html)
  data/            created on first run, never committed
```

Run in development mode: `.venv\Scripts\python -m uvicorn app.server:app --port 8765 --reload`
