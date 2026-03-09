import os

# ---------- FILE PATHS & CONSTANTS ----------
SOURCE = "source.mkv"
SCREENSHOT = "grid_preview.jpg"
LOG_FILE = "encode_log.txt"

# ---------- TELEGRAM CREDENTIALS ----------
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = int(os.getenv("CHAT_ID", "0")) if os.getenv("CHAT_ID") else 0
FILE_NAME = os.getenv("FILE_NAME", "output.mkv")
SESSION_NAME = os.getenv("SESSION_NAME", "enc_session")

# ---------- USER SETTINGS ----------
USER_RES = os.getenv("USER_RES")
USER_CRF = os.getenv("USER_CRF")
USER_PRESET = os.getenv("USER_PRESET")
USER_GRAIN = os.getenv("USER_GRAIN", "0")
AUDIO_MODE = os.getenv("AUDIO_MODE", "opus")
AUDIO_BITRATE = os.getenv("AUDIO_BITRATE", "128k")
RUN_VMAF = os.getenv("RUN_VMAF", "true").lower() == "true"

# ---------- CLOUDFLARE KV (for /p progress command) ----------
# These allow main.py (running in GitHub Actions) to push live progress
# snapshots into the same KV_STORE that the Cloudflare Worker reads.
# Get CF_KV_TOKEN from: Cloudflare Dashboard → My Profile → API Tokens
# Scope it to: Account / Workers KV Storage / Edit
CF_ACCOUNT_ID     = os.getenv("CF_ACCOUNT_ID", "")
CF_KV_NAMESPACE_ID = os.getenv("CF_KV_NAMESPACE_ID", "")
CF_KV_TOKEN       = os.getenv("CF_KV_TOKEN", "")

# Unique key per run so parallel encodes don't collide.
# GitHub Actions always sets GITHUB_RUN_ID automatically.
GITHUB_RUN_ID = os.getenv("GITHUB_RUN_ID", "local")

# ---------- GLOBAL STATE ----------
CANCELLED = False
