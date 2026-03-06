import asyncio
import os
import subprocess
import time
import shutil
from datetime import datetime, timezone, timedelta
from pyrogram import Client, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient

import config
from media import get_video_info, get_crop_params, select_params, async_generate_grid, get_vmaf, upload_to_cloud
from ui import format_time, upload_progress, get_failure_ui


# ---------------------------------------------------------------------------
# MONGODB REPORTER
# Writes directly to Atlas via pymongo. Non-blocking via executor.
# ---------------------------------------------------------------------------
MONGO_URI = os.getenv("MONGO_URI", "")
MONGO_DB  = os.getenv("MONGO_DB",  "av1")
MONGO_COL = os.getenv("MONGO_COL", "jobs")

_mongo_client = None

def get_col():
    global _mongo_client
    if not MONGO_URI:
        return None
    if _mongo_client is None:
        _mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    return _mongo_client[MONGO_DB][MONGO_COL]


def push_progress(payload: dict):
    col = get_col()
    if col is None:
        return
    try:
        is_done   = payload.get("phase") in ("done", "error")
        expire_at = datetime.now(timezone.utc) + timedelta(hours=24 if is_done else 6)
        col.update_one(
            {"run_id": payload["run_id"]},
            {"$set": {**payload, "updated_at": datetime.now(timezone.utc), "expire_at": expire_at}},
            upsert=True,
        )
    except Exception as e:
        print(f"[mongo] push failed: {e}")


async def push_async(payload: dict):
    payload["run_id"] = config.GITHUB_RUN_ID
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, push_progress, payload)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
async def main():
    # 1. PRE-FLIGHT DISK CHECK
    if os.path.exists(config.SOURCE):
        total, used, free = shutil.disk_usage("/")
        source_size = os.path.getsize(config.SOURCE)
        if (source_size * 2.1) > free:
            print(f"⚠️ DISK WARNING: {source_size/(1024**3):.2f}GB source might exceed {free/(1024**3):.2f}GB free space.")

    # 2. METADATA EXTRACTION
    try:
        duration, width, height, is_hdr, total_frames, channels, fps_val = get_video_info()
    except Exception as e:
        print(f"Metadata error: {e}")
        await push_async({"phase": "error", "file": config.FILE_NAME, "error_snippet": str(e)})
        return

    # 3. PARAMETER CONFIGURATION
    def_crf, def_preset = select_params(height)
    final_crf    = config.USER_CRF if (config.USER_CRF and config.USER_CRF.strip()) else def_crf
    final_preset = config.USER_PRESET if (config.USER_PRESET and config.USER_PRESET.strip()) else def_preset

    res_label = config.USER_RES if config.USER_RES else "1080"
    crop_val  = get_crop_params(duration)

    vf_filters = ["hqdn3d=1.5:1.2:3:3"]
    if crop_val: vf_filters.append(f"crop={crop_val}")
    vf_filters.append(f"scale=-1:{res_label}")
    video_filters = ["-vf", ",".join(vf_filters)]

    audio_cmd           = ["-af", "aformat=channel_layouts=stereo", "-c:a", "libopus", "-b:a", "32k", "-vbr", "on"]
    final_audio_bitrate = "32k"
    svtav1_tune         = "tune=0:film-grain=0:enable-overlays=1:aq-mode=1"
    hdr_label           = "HDR10" if is_hdr else "SDR"

    # 4. PUSH INITIAL STATE — no Telegram touch at all
    await push_async({
        "phase": "active", "file": config.FILE_NAME,
        "percent": 0, "elapsed": 0, "eta": 0, "speed": 0, "fps": 0, "size_mb": 0,
        "crf": final_crf, "preset": final_preset, "res": res_label,
        "hdr": hdr_label, "audio_bitrate": final_audio_bitrate,
    })

    # 5. ENCODING — Telegram client NOT open during this phase
    cmd = [
        "ffmpeg", "-i", config.SOURCE,
        "-map", "0:v:0", "-map", "0:a?", "-map", "0:s?",
        *video_filters,
        "-c:v", "libsvtav1", "-pix_fmt", "yuv420p10le",
        "-crf", str(final_crf), "-preset", str(final_preset),
        "-svtav1-params", svtav1_tune, "-threads", "0",
        *audio_cmd, "-c:s", "copy", "-map_chapters", "0",
        "-progress", "pipe:1", "-nostats", "-y", config.FILE_NAME
    ]

    start_time     = time.time()
    last_push_time = 0
    last_push_pct  = -1

    with open(config.LOG_FILE, "w") as f_log:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)

        for line in process.stdout:
            f_log.write(line)
            if config.CANCELLED:
                break

            if "out_time_ms" in line:
                try:
                    curr_sec = int(line.split("=")[1]) / 1_000_000
                    percent  = (curr_sec / duration) * 100
                    elapsed  = time.time() - start_time
                    speed    = curr_sec / elapsed if elapsed > 0 else 0
                    fps      = (percent / 100 * total_frames) / elapsed if elapsed > 0 else 0
                    eta      = (elapsed / percent) * (100 - percent) if percent > 0 else 0
                    size_mb  = os.path.getsize(config.FILE_NAME) / (1024 * 1024) if os.path.exists(config.FILE_NAME) else 0

                    now = time.time()
                    if int(percent) > last_push_pct or (now - last_push_time) >= 10:
                        last_push_pct  = int(percent)
                        last_push_time = now
                        await push_async({
                            "phase": "active", "file": config.FILE_NAME,
                            "percent": round(percent, 1), "elapsed": int(elapsed),
                            "eta": int(eta), "speed": round(speed, 2),
                            "fps": round(fps, 1), "size_mb": round(size_mb, 1),
                            "crf": final_crf, "preset": final_preset, "res": res_label,
                            "hdr": hdr_label, "audio_bitrate": final_audio_bitrate,
                        })
                except Exception:
                    continue

    process.wait()
    total_mission_time = time.time() - start_time

    # 6. OPEN TELEGRAM — only now, encode is done, no flood wait risk
    async with Client(config.SESSION_NAME, api_id=config.API_ID, api_hash=config.API_HASH, bot_token=config.BOT_TOKEN) as app:

        # 7. ERROR
        if process.returncode != 0:
            error_snippet = "".join(open(config.LOG_FILE).readlines()[-20:]) if os.path.exists(config.LOG_FILE) else "Unknown crash."
            await push_async({"phase": "error", "file": config.FILE_NAME, "elapsed": int(total_mission_time), "error_snippet": error_snippet})
            await app.send_message(config.CHAT_ID, get_failure_ui(config.FILE_NAME, error_snippet), parse_mode=enums.ParseMode.HTML)
            await app.send_document(config.CHAT_ID, config.LOG_FILE, caption="📑 <b>FULL ENCODE LOG</b>", parse_mode=enums.ParseMode.HTML)
            return

        # 8. REMUX
        fixed_file = f"FIXED_{config.FILE_NAME}"
        subprocess.run(["mkvmerge", "-o", fixed_file, config.FILE_NAME, "--no-video", "--no-audio", "--no-subtitles", "--no-attachments", config.SOURCE])
        if os.path.exists(fixed_file):
            os.remove(config.FILE_NAME)
            os.rename(fixed_file, config.FILE_NAME)

        final_size = os.path.getsize(config.FILE_NAME) / (1024 * 1024)

        # 9. VMAF + GRID + CLOUD
        await push_async({"phase": "vmaf", "file": config.FILE_NAME, "elapsed": int(total_mission_time)})

        grid_task  = asyncio.create_task(async_generate_grid(duration, config.FILE_NAME))
        cloud_task = asyncio.create_task(upload_to_cloud(config.FILE_NAME))

        if config.RUN_VMAF:
            vmaf_val, ssim_val = await get_vmaf(config.FILE_NAME, crop_val, width, height, duration, fps_val)
        else:
            vmaf_val, ssim_val = "N/A", "N/A"

        await grid_task
        cloud = await cloud_task

        # 10. PUSH DONE
        await push_async({
            "phase": "done", "file": config.FILE_NAME,
            "elapsed": int(total_mission_time), "final_size_mb": round(final_size, 2),
            "vmaf": vmaf_val, "ssim": ssim_val,
            "crf": final_crf, "preset": final_preset, "res": res_label,
            "hdr": hdr_label, "audio_bitrate": final_audio_bitrate,
            "gofile_url": cloud.get("page"), "direct_url": cloud.get("direct"),
        })

        # 11. BUILD TG BUTTONS
        btn_row = []
        if cloud["source"] == "gofile":
            if cloud.get("page"):   btn_row.append(InlineKeyboardButton("☁️ Gofile",   url=cloud["page"]))
            if cloud.get("direct"): btn_row.append(InlineKeyboardButton("🔗 Direct",   url=cloud["direct"]))
        elif cloud["source"] == "litterbox" and cloud.get("direct"):
            btn_row.append(InlineKeyboardButton("☁️ Litterbox", url=cloud["direct"]))
        buttons = InlineKeyboardMarkup([btn_row]) if btn_row else None

        # 12. FINAL TG — one message per job, sent only after encode is done
        if final_size > 2000:
            await app.send_message(
                config.CHAT_ID,
                f"⚠️ <b>[ SIZE OVERFLOW ]</b> File too large for Telegram.\n<code>{config.FILE_NAME}</code>",
                parse_mode=enums.ParseMode.HTML, reply_markup=buttons
            )
        else:
            crop_label = " | Cropped" if crop_val else ""
            report = (
                f"✅ <b>MISSION ACCOMPLISHED</b>\n\n"
                f"📄 <b>FILE:</b> <code>{config.FILE_NAME}</code>\n"
                f"⏱ <b>TIME:</b> <code>{format_time(total_mission_time)}</code>\n"
                f"📦 <b>SIZE:</b> <code>{final_size:.2f} MB</code>\n"
                f"📊 <b>QUALITY:</b> VMAF: <code>{vmaf_val}</code> | SSIM: <code>{ssim_val}</code>\n\n"
                f"🛠 <b>SPECS:</b>\n"
                f"└ Preset: {final_preset} | CRF: {final_crf}\n"
                f"└ Video: {res_label}{crop_label} | {hdr_label}\n"
                f"└ Audio: OPUS @ {final_audio_bitrate}"
            )
            import ui as _ui; _ui.last_up_pct = -1; _ui.last_up_update = 0; _ui.up_start_time = 0
            thumb = config.SCREENSHOT if os.path.exists(config.SCREENSHOT) else None
            await app.send_document(
                chat_id=config.CHAT_ID, document=config.FILE_NAME,
                thumb=thumb, caption=report, parse_mode=enums.ParseMode.HTML,
                reply_markup=buttons, progress=upload_progress,
                progress_args=(app, config.CHAT_ID, None, config.FILE_NAME)
            )

    # CLEANUP
    if _mongo_client:
        _mongo_client.close()
    for f in [config.SOURCE, config.FILE_NAME, config.LOG_FILE, config.SCREENSHOT]:
        if os.path.exists(f): os.remove(f)


if __name__ == "__main__":
    asyncio.run(main())
