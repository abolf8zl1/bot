import os
import re
import logging
import tempfile
import shutil
import asyncio

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

import yt_dlp

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------
# تنظیمات
# -----------------------------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "PUT-YOUR-TOKEN-HERE")

# حداکثر حجم فایلی که تلگرام اجازه ارسال می‌دهد
MAX_FILE_SIZE_MB = 49

# مسیر فایل کوکی (اختیاری) - برای پست‌های خصوصی یا محدودشده لازم می‌شه
COOKIES_FILE = os.environ.get("COOKIES_FILE", "cookies.txt")

INSTAGRAM_RE = re.compile(r"instagram\.com", re.IGNORECASE)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام! 👋\n\nلینک پست/ریلز اینستاگرام رو برام بفرست تا دانلودش کنم."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    url_match = re.search(r"https?://\S+", text)
    if not url_match:
        await update.message.reply_text("لطفاً یک لینک معتبر اینستاگرام بفرست.")
        return

    url = url_match.group(0)
    if not INSTAGRAM_RE.search(url):
        await update.message.reply_text("فقط لینک‌های اینستاگرام پشتیبانی می‌شن.")
        return

    await process_download(update.message, url)


async def process_download(message, url: str):
    status = await message.reply_text("⏳ در حال دانلود...")

    tmp_dir = tempfile.mkdtemp(prefix="dl_")
    try:
        filepath, error = await download_with_ytdlp(url, tmp_dir)

        if filepath is None:
            await status.edit_text(f"❌ دانلود انجام نشد.\n\nجزئیات خطا:\n{error}")
            return

        size_mb = os.path.getsize(filepath) / (1024 * 1024)
        if size_mb > MAX_FILE_SIZE_MB:
            await status.edit_text(
                f"❌ فایل {size_mb:.1f} مگابایته و بزرگ‌تر از محدودیت "
                f"{MAX_FILE_SIZE_MB} مگابایتی تلگرامه."
            )
            return

        await status.edit_text("📤 در حال ارسال...")

        ext = os.path.splitext(filepath)[1].lower()
        if ext in (".mp4", ".mov", ".webm"):
            await message.reply_video(video=open(filepath, "rb"), supports_streaming=True)
        elif ext in (".jpg", ".jpeg", ".png", ".webp"):
            await message.reply_photo(photo=open(filepath, "rb"))
        else:
            await message.reply_document(document=open(filepath, "rb"))

        await status.delete()

    except Exception as e:
        logger.exception("خطا در دانلود")
        await status.edit_text(f"❌ خطا: {e}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


async def download_with_ytdlp(url: str, out_dir: str):
    outtmpl = os.path.join(out_dir, "%(title).80s.%(ext)s")

    ydl_opts = {
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": f"best[filesize<{MAX_FILE_SIZE_MB}M]/best",
    }

    if os.path.exists(COOKIES_FILE):
        ydl_opts["cookiefile"] = COOKIES_FILE

    def _run():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if "entries" in info:
                info = info["entries"][0]
            filename = ydl.prepare_filename(info)
            return filename

    loop = asyncio.get_event_loop()
    try:
        filename = await loop.run_in_executor(None, _run)
        return filename, None
    except Exception as e:
        logger.exception("yt-dlp failed")
        return None, str(e)


def main():
    if BOT_TOKEN == "PUT-YOUR-TOKEN-HERE":
        print("⚠️  لطفاً توکن ربات رو در فایل بات یا متغیر محیطی BOT_TOKEN قرار بده.")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ ربات روشن شد و در حال اجراست... (برای توقف Ctrl+C بزن)")
    app.run_polling()


if __name__ == "__main__":
    main()
