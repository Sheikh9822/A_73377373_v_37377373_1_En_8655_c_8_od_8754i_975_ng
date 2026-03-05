"""
upload.py — Phase 3: Upload to Telegram
Runs after encode_phase. Expects the encoded file to already exist as FILE_NAME.
Handles: remux, screenshot grid, Gofile upload, VMAF (if needed), TG send.
"""
import asyncio
import os
import subprocess

from pyrogram import Client, enums
from pyrogram.errors import FloodWait
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import config
from media import async_generate_grid, get_video_info, get_vmaf, upload_to_cloud
from ui import format_time, upload_progress, get_failure_ui
import ui as _ui


async def main():
    if not os.path.exists(config.FILE_NAME):
        print(f"❌ Encoded file not found: {config.FILE_NAME}")
        return

    async with Client(config.SESSION_NAME, api_id=config.API_ID, api_hash=config.API_HASH, bot_token=config.BOT_TOKEN) as app:

        # ── Status message ────────────────────────────────────────────────────
        try:
            status = await app.send_message(
                config.CHAT_ID,
                f"📡 <b>[ UPLINK PHASE ] Preparing: {config.FILE_NAME}</b>",
                parse_mode=enums.ParseMode.HTML
            )
        except FloodWait as e:
            await asyncio.sleep(e.value + 2)
            status = await app.send_message(
                config.CHAT_ID,
                f"📡 <b>[ UPLINK PHASE ] Preparing: {config.FILE_NAME}</b>",
                parse_mode=enums.ParseMode.HTML
            )

        # ── Remux ─────────────────────────────────────────────────────────────
        await app.edit_message_text(
            config.CHAT_ID, status.id,
            "🛠️ <b>[ SYSTEM.OPTIMIZE ] Finalizing Metadata...</b>",
            parse_mode=enums.ParseMode.HTML
        )
        fixed_file = f"FIXED_{config.FILE_NAME}"
        source = "source.mkv" if os.path.exists("source.mkv") else config.FILE_NAME
        subprocess.run(
            ["mkvmerge", "-o", fixed_file, config.FILE_NAME,
             "--no-video", "--no-audio", "--no-subtitles", "--no-attachments", source],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        if os.path.exists(fixed_file):
            os.remove(config.FILE_NAME)
            os.rename(fixed_file, config.FILE_NAME)

        final_size = os.path.getsize(config.FILE_NAME) / (1024 * 1024)

        # ── Gofile + grid concurrently ────────────────────────────────────────
        await app.edit_message_text(
            config.CHAT_ID, status.id,
            "☁️ <b>[ SYSTEM.CLOUD ] Uploading to Gofile...</b>",
            parse_mode=enums.ParseMode.HTML
        )

        try:
            duration, width, height, is_hdr, _, _, fps_val = get_video_info()
        except Exception:
            duration, width, height, is_hdr, fps_val = 0, 0, 0, False, 24.0

        grid_task  = asyncio.create_task(async_generate_grid(duration, config.FILE_NAME))
        cloud_task = asyncio.create_task(upload_to_cloud(config.FILE_NAME))

        if config.RUN_VMAF and duration > 0:
            vmaf_val, ssim_val = await get_vmaf(config.FILE_NAME, None, width, height, duration, fps_val)
        else:
            vmaf_val, ssim_val = "N/A", "N/A"

        await grid_task
        cloud = await cloud_task

        # ── Build buttons ─────────────────────────────────────────────────────
        btn_row = []
        if cloud["source"] == "gofile":
            if cloud.get("page"):
                btn_row.append(InlineKeyboardButton("☁️ Gofile", url=cloud["page"]))
            if cloud.get("direct"):
                btn_row.append(InlineKeyboardButton("🔗 Direct", url=cloud["direct"]))
        elif cloud["source"] == "litterbox" and cloud.get("direct"):
            btn_row.append(InlineKeyboardButton("☁️ Litterbox", url=cloud["direct"]))
        buttons = InlineKeyboardMarkup([btn_row]) if btn_row else None

        # ── Size overflow ─────────────────────────────────────────────────────
        if final_size > 2000:
            await app.edit_message_text(
                config.CHAT_ID, status.id,
                "⚠️ <b>[ SIZE OVERFLOW ]</b> File too large for Telegram. Cloud link below.",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=buttons
            )
            return

        # ── Screenshot grid ───────────────────────────────────────────────────
        photo_msg = None
        if os.path.exists(config.SCREENSHOT):
            photo_msg = await app.send_photo(
                config.CHAT_ID, config.SCREENSHOT,
                caption=f"🖼 <b>PROXIMITY GRID:</b> <code>{config.FILE_NAME}</code>",
                parse_mode=enums.ParseMode.HTML
            )

        # ── Report ────────────────────────────────────────────────────────────
        report = (
            f"✅ <b>MISSION ACCOMPLISHED</b>\n\n"
            f"📄 <b>FILE:</b> <code>{config.FILE_NAME}</code>\n"
            f"📦 <b>SIZE:</b> <code>{final_size:.2f} MB</code>\n"
            f"📊 <b>QUALITY:</b> VMAF: <code>{vmaf_val}</code> | SSIM: <code>{ssim_val}</code>\n\n"
            f"🛠 <b>SPECS:</b>\n"
            f"└ <b>CRF:</b> {config.USER_CRF} | <b>Preset:</b> {config.USER_PRESET}\n"
            f"└ <b>Audio:</b> {config.AUDIO_MODE.upper()} @ {config.AUDIO_BITRATE}"
        )

        # Reset upload progress trackers
        _ui.last_up_pct = -1; _ui.last_up_update = 0; _ui.up_start_time = 0

        await app.edit_message_text(
            config.CHAT_ID, status.id,
            "🚀 <b>[ SYSTEM.UPLINK ] Transmitting Final Video...</b>",
            parse_mode=enums.ParseMode.HTML
        )

        await app.send_document(
            chat_id=config.CHAT_ID,
            document=config.FILE_NAME,
            caption=report,
            parse_mode=enums.ParseMode.HTML,
            reply_to_message_id=photo_msg.id if photo_msg else None,
            reply_markup=buttons,
            progress=upload_progress,
            progress_args=(app, config.CHAT_ID, status, config.FILE_NAME)
        )

        # ── Cleanup ───────────────────────────────────────────────────────────
        try: await status.delete()
        except: pass
        for f in [config.FILE_NAME, config.SCREENSHOT]:
            if os.path.exists(f): os.remove(f)


if __name__ == "__main__":
    asyncio.run(main())
