<div align="center">

# ⚡ Warborn Music

### 🎵 Powered by Raiden Music Bot

A modern, high-performance Telegram music bot framework built for speed, stability, and a beautiful user experience.

[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![Platform](https://img.shields.io/badge/Platform-Telegram-26A5E4.svg)

⭐ If you enjoy this project, consider leaving a star!

</div>

---

# ✨ Features

- 🎵 High-quality audio playback
- 🔎 Fast YouTube search
- 📃 Interactive queue management
- ⏯️ Play, Pause, Resume & Skip
- 🔁 Loop support
- 🎚️ Volume control
- 🖼️ Beautiful media cards
- ⚡ Optimized performance
- 🔒 Stable and reliable
- 🌍 Multi-platform hosting support
- 🛠️ Regular updates
- 📦 Easy deployment

---

# 🚀 Getting Started

Follow these steps to set up **Warborn Music**.

---

## 1. Clone the Repository

```bash
git clone https://github.com/Void-Verser/Warborn-Music.git
cd Warborn-Music
```

---

## 2. Install Dependencies

Make sure **Python 3.10 or newer** is installed.

Install all required packages:

```bash
pip install -r requirements.txt
```

---

## 3. Create a Telegram Bot

1. Open **@BotFather**
2. Send:

```
/newbot
```

3. Follow the instructions.
4. Copy your **Bot Token**.

Example:

```
BOT_TOKEN=1234567890:AAxxxxxxxxxxxxxxxxxxxxxxxx
```

---

## 4. Get Telegram API Credentials

Visit:

```
https://my.telegram.org
```

Log in using your Telegram account.

Go to:

```
API Development Tools
```

Create a new application and copy:

- API_ID
- API_HASH

Example:

```
API_ID=12345678
API_HASH=0123456789abcdef0123456789abcdef
```

---

## 5. Generate a String Session

Generate a **Pyrogram String Session** using any trusted Pyrogram Session Generator compatible with your Pyrogram version.

Copy the generated session.

Example:

```
STRING_SESSION=AQFxxxxxxxxxxxxxxxxxxxxxxxx
```

---

## 6. Create a MongoDB Database

Create a free MongoDB Atlas cluster.

Copy your MongoDB connection URI.

Example:

```
MONGO_URI=mongodb+srv://username:password@cluster.mongodb.net/database
```

---

## 7. Configure Environment Variables

Create a file named:

```
.env
```

inside the project directory.

Paste the following:

```env
# Telegram
API_ID=
API_HASH=
BOT_TOKEN=
STRING_SESSION=

# Database
MONGO_URI=

# Owner
OWNER_ID=

# Optional
LOG_GROUP_ID=
SUPPORT_CHAT=
UPDATE_CHANNEL=
```

Fill in all required values before running the bot.

---

## 8. Run the Bot

```bash
python main.py
```

or

```bash
python3 main.py
```

If your project uses another startup file, replace **main.py** with the correct filename.

---

# ☁️ Hosting

Warborn Music is designed to run on a variety of hosting platforms.

### Officially Supported

- 🚄 Railway
- 💜 Heroku
- ☁️ Koyeb
- 🌐 Render
- 🐳 Docker
- 🖥️ VPS (Ubuntu/Debian recommended)
- 💻 Local Machine (Windows/Linux/macOS)
- ☁️ Any Linux server with Python support

Simply copy all values from your `.env` file into your hosting provider's **Environment Variables** section.

For Docker deployments, you can either use a `.env` file or pass the environment variables directly to your container.

---

## 📦 Deploy on Railway

1. Fork this repository.
2. Create a new Railway project.
3. Connect your GitHub repository.
4. Add all required Environment Variables.
5. Deploy the project.

---

## 💜 Deploy on Heroku

1. Fork this repository.
2. Create a new Heroku application.
3. Connect your GitHub repository.
4. Go to **Settings → Config Vars**.
5. Add all required Environment Variables.
6. Deploy the application.

---

## ☁️ Deploy on Koyeb

1. Create a Koyeb service.
2. Import your GitHub repository.
3. Configure the Environment Variables.
4. Deploy.

---

## 🌐 Deploy on Render

1. Create a new **Web Service**.
2. Connect your GitHub repository.
3. Configure the Environment Variables.
4. Deploy.

---

## 🖥️ Deploy on VPS

```bash
git clone https://github.com/Void-Verser/Warborn-Music.git
cd Warborn-Music

pip install -r requirements.txt

python main.py
```

For production deployments, it's recommended to use **systemd**, **PM2**, or **Docker** so the bot restarts automatically if it stops.

---

# 🔑 Environment Variables

| Variable | Description |
|-----------|-------------|
| API_ID | Telegram API ID |
| API_HASH | Telegram API Hash |
| BOT_TOKEN | Telegram Bot Token |
| STRING_SESSION | Pyrogram Assistant Session |
| MONGO_URI | MongoDB Database URI |
| OWNER_ID | Telegram User ID of the Bot Owner |
| LOG_GROUP_ID | Log Group ID (Optional) |
| SUPPORT_CHAT | Support Group Username (Optional) |
| UPDATE_CHANNEL | Updates Channel Username (Optional) |

---

# 🎧 Commands

| Command | Description |
|---------|-------------|
| `/play` | Play music |
| `/pause` | Pause playback |
| `/resume` | Resume playback |
| `/skip` | Skip current song |
| `/stop` | Stop playback |
| `/queue` | Show queue |
| `/loop` | Toggle loop mode |
| `/volume` | Adjust volume |
| `/ping` | Check bot latency |
| `/help` | Display help menu |

---

# 📂 Roadmap

Upcoming features include:

- 🎼 Spotify support
- 🎧 Apple Music support
- 📜 Lyrics
- ❤️ Favorites
- 📂 Playlists
- 🌍 Multi-language support
- 🖼️ Premium queue interface
- 🎨 Enhanced artwork generation
- 📊 Web Dashboard
- 🔔 Update notifier
- ⚡ Performance improvements

---

# 🤝 Contributing

Contributions are always welcome.

If you discover a bug, have a feature request, or would like to improve the project, feel free to open an **Issue** or submit a **Pull Request**.

---

# 🛠 Troubleshooting

### Bot doesn't start

- Verify Python version.
- Install all dependencies.
- Check every environment variable.
- Verify your MongoDB connection.
- Restart the bot after updating the configuration.

---

### Invalid BOT_TOKEN

Generate a new Bot Token using **@BotFather** and update your `.env` file.

---

### Invalid STRING_SESSION

Generate a new Pyrogram String Session using the same Telegram account that will act as the assistant account.

---

### Database Connection Failed

Check your MongoDB URI and ensure your database is accessible.

---

# 📜 License

This project is licensed under the **MIT License**.

See the **LICENSE** file for more information.

---

# ❤️ Credits

**Warborn Music** is maintained by **Ray**.

Powered by **Raiden Music Bot**.

Special thanks to the open-source community and everyone who contributes to improving this project.

---

<div align="center">

## ⭐ Star this repository if you find it useful!

Made with ❤️ for the Telegram community.

</div>- 🔒 Stable and reliable
- 🛠️ Regular updates

---

## 🚀 Installation

Clone the repository:

```bash
git clone https://github.com/Void-Verser/Raiden-Music-Bot.git
cd Raiden-Music-Bot
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Configure your environment variables and start the bot.

---

## ⚙️ Configuration

Create a `.env` file and add your credentials.

```env
API_ID=
API_HASH=
BOT_TOKEN=
STRING_SESSION=
MONGO_URI=
OWNER_ID=
```

---

## 🎧 Commands

| Command | Description |
|---------|-------------|
| `/play` | Play a song |
| `/pause` | Pause playback |
| `/resume` | Resume playback |
| `/skip` | Skip current song |
| `/stop` | Stop playback |
| `/queue` | Show queue |
| `/volume` | Change volume |
| `/ping` | Check bot latency |
| `/help` | Show help menu |

---

## 📂 Project Goals

Raiden Music Bot aims to provide a fast, elegant, and feature-rich music experience on Telegram while maintaining clean code and an easy-to-use interface.

Future updates may include:

- Smart recommendations
- Playlist support
- Lyrics
- Audio filters
- Web Dashboard
- Multi-language support
- Enhanced queue UI
- Better streaming performance

---

## 🤝 Contributing

Contributions, feature requests, and bug reports are welcome.

Feel free to open an Issue or submit a Pull Request.

---

## 📜 License

This project is licensed under the **MIT License**.

See the [LICENSE](LICENSE) file for details.

---

## ❤️ Credits

Developed and maintained by **Ray**.

Special thanks to everyone who supports the project.

---

<div align="center">

### ⭐ If you like this project, don't forget to leave a star!

Made with ❤️ for the Telegram community.

</div>

# 🚀 Getting Started

Follow these steps to set up and run Raiden Music Bot.

---

## 1. Clone the Repository

```bash
git clone https://github.com/Void-Verser/Raiden-Music-Bot.git
cd Raiden-Music-Bot
```

---

## 2. Install Dependencies

Make sure you have **Python 3.10 or newer** installed.

Install all required packages:

```bash
pip install -r requirements.txt
```

---

## 3. Create a Telegram Bot

1. Open **@BotFather** on Telegram.
2. Send `/newbot`.
3. Follow the instructions.
4. Copy the **Bot Token**.

Example:

```
BOT_TOKEN=1234567890:AA...
```

---

## 4. Get Telegram API Credentials

Visit:

https://my.telegram.org

Login using your Telegram account.

Go to:

**API Development Tools**

Create a new application and copy:

- API_ID
- API_HASH

Example:

```
API_ID=12345678
API_HASH=0123456789abcdef0123456789abcdef
```

---

## 5. Generate a String Session

Generate a Pyrogram String Session using any trusted session generator compatible with your Pyrogram version.

Copy the generated session.

Example:

```
STRING_SESSION=AQF...
```

---

## 6. Create a MongoDB Database

Create a free MongoDB cluster.

Copy your connection URI.

Example:

```
MONGO_URI=mongodb+srv://username:password@cluster.mongodb.net/database
```

---

## 7. Create the Environment File

Inside the project folder create a file named:

```
.env
```

Paste the following:

```env
# Telegram
API_ID=
API_HASH=
BOT_TOKEN=
STRING_SESSION=

# Database
MONGO_URI=

# Owner
OWNER_ID=

# Optional
LOG_GROUP_ID=
SUPPORT_CHAT=
UPDATE_CHANNEL=
```

Fill every value with your own credentials.

---

## 8. Start the Bot

Run:

```bash
python main.py
```

or

```bash
python3 main.py
```

If your project uses another startup file, replace `main.py` with the correct filename.

---

# ☁️ Hosting

Raiden Music Bot can be hosted on:

- VPS (Recommended)
- Railway
- Koyeb
- Render
- Pella
- Docker
- Local Machine (24/7 PC)

Simply copy the same environment variables from your `.env` file into your hosting provider's Environment Variables section.

---

# 🔑 Environment Variables

| Variable | Description |
|----------|-------------|
| API_ID | Telegram API ID |
| API_HASH | Telegram API Hash |
| BOT_TOKEN | Telegram Bot Token |
| STRING_SESSION | Pyrogram User Session |
| MONGO_URI | MongoDB Database URL |
| OWNER_ID | Telegram User ID of the Bot Owner |
| LOG_GROUP_ID | Group where bot logs are sent (Optional) |
| SUPPORT_CHAT | Support group username (Optional) |
| UPDATE_CHANNEL | Updates channel username (Optional) |

---

# 🛠 Troubleshooting

### Bot doesn't start

- Make sure Python version is supported.
- Install all requirements.
- Verify every environment variable.
- Ensure your MongoDB URI is valid.

---

### Invalid Bot Token

Create a new token from **@BotFather** and update your `.env` file.

---

### Database Error

Check your MongoDB URI and verify that your IP/network has access to the database.

---

### String Session Invalid

Generate a new String Session using the same Telegram account that will act as the assistant account.

---

# ❤️ Need Help?

If you encounter any issues while setting up the bot, open a GitHub Issue or join the support group for

---

<div align="center">

# 📘 Configuration Manual (Template Guide)

*Everything you can set up or customise — all through `.env` unless noted.*

</div>

> ℹ️ **About this build:** persistence in this template is **optional Redis** (or automatic local JSON) — **MongoDB is not used or required**. You can leave any database field blank and the bot still runs. Fill in the five required values below, add cookies and/or a proxy for reliable YouTube on cloud hosts, and you're live.

---

## 1️⃣ Required — the bot won't start without these

| Variable | Where to get it |
|----------|-----------------|
| `API_ID` | https://my.telegram.org → API development tools |
| `API_HASH` | same page as API_ID |
| `BOT_TOKEN` | [@BotFather](https://t.me/BotFather) → `/newbot` |
| `STRING_SESSION` | run `python3 scripts/session_gen.py` and log in with the **assistant** account |
| `OWNER_ID` | your Telegram numeric id (comma/space list allowed for multiple owners) |

> ⚠️ A `STRING_SESSION` gives **full access** to that Telegram account — use a spare/dedicated account for the assistant, and never share or commit it.

**Before running:** in @BotFather turn **Group Privacy → OFF**, and make the bot an **admin** in your group (manage voice chats + delete messages).

---

## 2️⃣ Branding & Links — make it *yours*

All optional. A link left blank simply hides that button — no dead buttons.

| Variable | Effect |
|----------|--------|
| `BOT_NAME` | The name shown on `/start`, `/help`, `/stats` (default `Warborn Music`) |
| `BOT_USERNAME` | Your bot's @username for the "Add me to your group" button (auto-detected if left blank) |
| `SUPPORT_CHAT` | Support button link — accepts a full URL, `@handle`, or `t.me/...` |
| `UPDATE_CHANNEL` | Updates button link |
| `OWNER_URL` | Owner button link |
| `START_IMAGE` | Banner image URL on `/start` |
| `HELP_IMAGE` | Banner image URL on `/help` |
| `WELCOME_BANNER_URL` | Background art for the welcome (join) card |
| `WELCOME_AVATAR_URL` | Fallback avatar when a joining user has no profile photo |
| `KILL_SUCCESS_MEDIA` / `KILL_FAILURE_MEDIA` | Media shown by the fun `/kill` command |
| `WAIFU_BRAND` | Optional heading line on the `/waifu` card |

### ✍️ Changing the start / help *text* (code, not `.env`)

The wording of the welcome and help messages lives in code so you can style them freely:

- **Start message:** edit `_start_caption()` in [`bot/plugins/start.py`](bot/plugins/start.py)
- **Help pages / command list:** edit the `HELP_PAGES` list in [`bot/plugins/help.py`](bot/plugins/help.py)

The bot name in those texts already pulls from `BOT_NAME`, so for a simple rename you only need the env var — edit the files only if you want to reword or restyle.

---

## 3️⃣ Cookies — for YouTube / Instagram downloads

On most cloud/datacenter IPs, YouTube and Instagram block anonymous access. Supply cookies exported (Netscape `cookies.txt` format) from a logged-in browser session.

| Variable | Use |
|----------|-----|
| `COOKIES_FILE` | Path to a `cookies.txt` on disk (VPS / Docker volume) |
| `COOKIES_CONTENT` | Paste the **raw** `cookies.txt` contents inline (for PaaS hosts that only allow env vars) |
| `INSTAGRAM_COOKIES_FILE` / `INSTAGRAM_COOKIES_CONTENT` | Same, for Instagram links |
| `COOKIES_DIR` | A folder of extra `*.txt` cookie jars for automatic health-based rotation |
| `COOKIE_CHECK_INTERVAL_MIN` | How often (minutes) the background health checker probes the active jar |
| `COOKIE_FORCE_REFRESH_HOURS` | Rotate a still-healthy jar once it's older than this |

- If both `*_FILE` and `*_CONTENT` are set, **`*_FILE` wins**.
- Browser cookies **expire in hours-to-days** — refresh them when playback starts failing. The built-in health-checker rotates between jars automatically but cannot create new ones.

---

## 4️⃣ Proxies — the most reliable fix for YouTube on cloud hosts

A **residential** proxy is the single best fix for "bot-check" / "format not available" errors on a datacenter/VPS IP. Single proxy or an auto-rotating pool are both supported.

| Variable | Use |
|----------|-----|
| `PROXY_URL` | One proxy for **both** Telegram + yt-dlp. `socks5://user:pass@host:port`, `socks4://…`, or `http://host:port` |
| `PROXIES_FILE` | A pool file (one proxy per line) for the Telegram clients — a random one is picked per start |
| `YT_DLP_PROXY` | A yt-dlp-**only** proxy (Telegram stays direct) |
| `YT_DLP_PROXY_LIST` | A rotating pool for yt-dlp — auto-rotates off a dead/failed proxy |
| `YT_DLP_PROXY_STRICT` | Set to refuse a direct fallback if all proxies fail (never leak the server's real IP) |

**Pool file format** (`PROXIES_FILE` / `YT_DLP_PROXY_LIST`) — one per line, either style:
```
socks5://user:pass@host:port
host:port:user:pass          # shorthand (defaults to http); blank lines and # comments ignored
```
Test a proxy list before deploying with: `python3 scripts/validate_proxies.py`

---

## 5️⃣ Audio source options (pick any — all optional)

The bot always **searches** YouTube cookielessly, then **fetches** the audio using whichever of these is available, falling back automatically:

| Variable | Use |
|----------|-----|
| `API_URL` / `API_KEY` | External YouTube audio-fetch gateway. When set, the server never hits YouTube's CDN directly — the most hands-off option on cloud hosts |
| `MEDIA_API_URL` / `MEDIA_API_KEY` | Optional microservice for Instagram/Pinterest downloads (falls back to local yt-dlp) |
| `MEDIA_API_INSTAGRAM_ENABLED` | Set `false` to skip the media API for Instagram and use the local fallback |
| `ALLOW_JIOSAAVN_FALLBACK` | Set `1` to allow a JioSaavn last-resort track when YouTube fetch fails (may play a different rendition) |

**No API? No problem.** Leave `API_URL`/`API_KEY` blank and the bot fetches via local **yt-dlp + your cookies** (and proxy, if set). See §3 and §4.

### Which combo should a forker use?

| Host type | Recommended setup |
|-----------|-------------------|
| Home PC / residential VPS | **Cookies only** — works great |
| Cloud (Railway/Heroku/Koyeb/Render) | **Cookies + residential `PROXY_URL`**, *or* an `API_URL` gateway |

---

## 6️⃣ Persistence — keep data across restarts (optional)

| Variable | Use |
|----------|-----|
| `REDIS_URL` | Redis/Upstash URL. Persists served chats, `/stats` reach, greetings, sudoers, blacklist, gban, and the log channel across redeploys. Free tier at [console.upstash.com](https://console.upstash.com) |
| `REDIS_PREFIX` | Key namespace (default `warborn`) |

Leave `REDIS_URL` blank and the bot uses local JSON files instead — everything still works, but that data **resets on every redeploy** on ephemeral hosts.

---

## 7️⃣ Other optional settings

| Variable | Use |
|----------|-----|
| `LOG_GROUP_ID` | Channel/group id for event logs (start / add / download). Add the bot there as admin. Can also be set at runtime with `/setlog` |
| `SUDO_USERS` | Extra delegated sudo user ids (comma/space list) — powers without full owner rights |
| `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` | Resolve Spotify links ([developer.spotify.com](https://developer.spotify.com/dashboard)) |
| `USERBOT_START_DELAY` | Seconds to wait for an old instance to shut down on rolling-deploy hosts (Railway). Default 25; set 0 to disable |
| `WELCOME_POLL_MAX_MEMBERS` | Groups larger than this aren't polled for welcome/farewell (keeps API usage modest) |

📄 **The complete, commented list of every variable is in [`.env.example`](.env.example)** — copy it to `.env` and fill in what you need.

---

## ✅ Minimum to go live

```env
API_ID=12345678
API_HASH=your_api_hash
BOT_TOKEN=123456:your_bot_token
STRING_SESSION=your_assistant_session
OWNER_ID=your_user_id
# recommended for YouTube on a cloud host:
COOKIES_CONTENT=...          # or COOKIES_FILE=/path/cookies.txt
# PROXY_URL=socks5://user:pass@host:port
```
Then: `pip install -r requirements.txt && python main.py` — or `bash setup.sh` to auto-install FFmpeg + dependencies and start.

---

<div align="center">

# 🖼️ Changing the Bot's Images

*How to swap the picture the bot sends on `/start` (and every other image) for your own.*

</div>

The bot's images come from **two places**. Some are just a URL you set in `.env` (easiest — no code, no redeploy of files), and some are picture files committed inside the repo that you replace directly.

---

## 🟢 Type A — images set by a URL in `.env` (easiest)

For these, upload your image anywhere that gives a **direct image link** (e.g. [imgbb](https://imgbb.com), [Catbox](https://catbox.moe), or a Telegram-hosted URL), then paste that link into the matching variable. Leave a variable blank to keep the built-in default.

| What you see | Variable | Where |
|--------------|----------|-------|
| 🎬 The photo sent on **`/start`** | `START_IMAGE` | on the welcome card |
| 📚 The photo sent on **`/help`** | `HELP_IMAGE` | on the help menu |
| 👋 The **welcome (join) card** background | `WELCOME_BANNER_URL` | shown when a new member joins |
| 🧑 Fallback **avatar** on the welcome card | `WELCOME_AVATAR_URL` | used when the joiner has no profile photo |
| 💀 `/kill` result media | `KILL_SUCCESS_MEDIA` / `KILL_FAILURE_MEDIA` | the fun kill command |

**Example — change the `/start` image:**
```env
START_IMAGE=https://i.ibb.co/your-own-image.jpg
HELP_IMAGE=https://i.ibb.co/your-help-image.jpg
```
Save `.env`, restart the bot, and `/start` now sends **your** image. ✅

> Tip: use a direct link that ends in `.jpg` / `.png` (opening it in a browser should show only the image). A normal webpage link won't work.

---

## 🔵 Type B — image *files* stored inside the repo

These are actual files committed under **`bot/assets/`**. To change them, just replace the file with your own (keep the **same filename**), then commit/redeploy.

| What it is | File to replace |
|------------|-----------------|
| 🎵 The **"Now Playing" card** template (background of the song card) | `bot/assets/now_playing_template.png` |
| ✨ `/aura` videos | any file in `bot/assets/aura/` |
| 🖐️ `/pat` GIFs | any file in `bot/assets/pat/` |
| 💗 `/waifu` fallback pictures | `bot/assets/waifu/fallback_1.jpg`, `fallback_2.jpg` |

**Notes:**
- `/aura` and `/pat` pick a **random** file from their folder each time — so you can freely **add, remove, or replace** files there. New files are picked up automatically; no code change needed.
- For `now_playing_template.png`, keep it a **PNG** with similar dimensions so the song title/artwork still line up.
- To keep the same look but a different file name, that's fine for the `aura`/`pat`/`waifu` folders; for `now_playing_template.png` keep the exact name (it's referenced directly).

---

## Which one do I need?

- **"I want a different picture on `/start` / `/help` / welcome"** → **Type A**, set the URL in `.env`. No files to touch.
- **"I want different `/aura`, `/pat`, `/waifu`, or Now-Playing artwork"** → **Type B**, replace the files in `bot/assets/`.

Either way, **you never have to modify the Python code** to change images — env vars for the URLs, file replacement for the assets.

---

<div align="center">

# 🎨 Managing Banner Images & Assets

*A complete reference for putting your own banners/artwork into the bot and managing every bundled asset to your liking.*

</div>

The bot ships with ready-made artwork so it looks good out of the box, but everything is yours to swap. There are **two kinds** of visuals, and you manage them differently:

- **URL images** — set an image link in `.env`; no files, no redeploy of code.
- **Asset files** — real image/video files committed under **`bot/assets/`**; replace the file to change them.

---

## 🖼️ A. Banner images set via `.env` (URL — easiest)

Upload your image to any host that gives a **direct link** (e.g. [imgbb](https://imgbb.com), [Catbox](https://catbox.moe)) — the link should open the raw image and ideally end in `.jpg`/`.png`. Then set it in `.env` (leave blank to keep the default):

| Shown on | Variable |
|----------|----------|
| `/start` banner | `START_IMAGE` |
| `/help` banner | `HELP_IMAGE` |
| Welcome (join) card background | `WELCOME_BANNER_URL` |
| Welcome fallback avatar | `WELCOME_AVATAR_URL` |
| `/kill` result media | `KILL_SUCCESS_MEDIA` / `KILL_FAILURE_MEDIA` |

```env
START_IMAGE=https://your-host/your-start-banner.jpg
HELP_IMAGE=https://your-host/your-help-banner.jpg
```
Save, restart — done. No code changes.

---

## 📁 B. Asset files under `bot/assets/` (replace the file)

These are committed image/video files. To use your own, **replace the file with the same name**, then commit & redeploy. Full asset map:

| Asset file | Used for | Type / tips |
|------------|----------|-------------|
| `bot/assets/now_playing_template.png` | Background of the **audio "Now Playing"** card | PNG; keep similar dimensions so the title/artwork stay aligned |
| `bot/assets/vplay_image.jpg` | Banner on the **`/vplay` (video)** Now-Playing & Added-to-Queue cards | JPG; use a wide banner image |
| `bot/assets/mp4_default_art.jpg` | Default cover art for **MP4/video** tracks that have no thumbnail | JPG; square works best |
| `bot/assets/waifu/fallback_1.jpg`, `fallback_2.jpg` | Fallback pictures for **`/waifu`** | JPG |
| `bot/assets/aura/*.mp4` | Random clip pool for **`/aura`** | MP4; see pool note below |
| `bot/assets/pat/*.mp4` | Random GIF/clip pool for **`/pat`** | MP4; see pool note below |

### How to replace a single banner (example: your own `/vplay` banner)
```bash
# from the repo root
cp /path/to/your-banner.jpg bot/assets/vplay_image.jpg
git add bot/assets/vplay_image.jpg
git commit -m "Use my own /vplay banner"
git push
```
Redeploy (or restart) and the bot uses it immediately.

### Managing the `/aura` and `/pat` pools
These folders are **random pools** — the bot picks one file at random each time, so you can shape them freely:
- **Add** clips: drop new `.mp4` files into `bot/assets/aura/` or `bot/assets/pat/` (any filename).
- **Remove** clips: delete the ones you don't want.
- **Replace** clips: swap files in place.

No code edit is needed — new files are detected automatically. Just make sure each folder has **at least one** file so the command always has something to show.

> **Naming rule:** for the single fixed banners (`now_playing_template.png`, `vplay_image.jpg`, `mp4_default_art.jpg`, `waifu/fallback_1.jpg`, `waifu/fallback_2.jpg`) keep the **exact filename** — they're referenced directly in code. For the `aura/` and `pat/` **pools**, any filename works.

---

## Quick decision guide

- **Change `/start`, `/help`, or welcome image →** set the URL in `.env` (Section A).
- **Change the Now-Playing / `/vplay` / MP4 default artwork →** replace the file in `bot/assets/` (Section B).
- **Curate `/aura` or `/pat` clips →** add/remove/replace files in their folders (Section B).

Either way, **no Python code changes are required** to make the bot use your own banners and assets.
