import os
import re
import logging
import tempfile
import shutil

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
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
# توکن ربات را یا مستقیم اینجا بگذارید یا با متغیر محیطی BOT_TOKEN ست کنید
BOT_TOKEN = os.environ.get("BOT_TOKEN", "PUT-YOUR-TOKEN-HERE")

# حداکثر حجم فایلی که تلگرام اجازه ارسال می‌دهد (برای ربات معمولی ۵۰ مگابایت)
MAX_FILE_SIZE_MB = 49

# مسیر فایل کوکی (اختیاری) برای دور زدن محدودیت "sign in to confirm you're not a bot" یوتیوب
# نحوه ساختش تو README توضیح داده شده
COOKIES_FILE = os.environ.get("COOKIES_FILE", "cookies.txt")

YOUTUBE_RE = re.compile(r"(youtube\.com|youtu\.be)", re.IGNORECASE)
TWITTER_RE = re.compile(r"(twitter\.com|x\.com)", re.IGNORECASE)
INSTAGRAM_RE = re.compile(r"instagram\.com", re.IGNORECASE)


def detect_platform(url: str) -> str:
    if YOUTUBE_RE.search(url):
        return "youtube"
    if TWITTER_RE.search(url):
        return "twitter"
    if INSTAGRAM_RE.search(url):
        return "instagram"
    return "unknown"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام! 👋\n\n"
        "لینک ویدیو/پست از یوتیوب، اینستاگرام یا توییتر(X) رو برام بفرست "
        "تا برات دانلودش کنم.\n\n"
        "برای یوتیوب می‌تونی انتخاب کنی که ویدیو بگیری یا فقط صدا (MP3)."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    url_match = re.search(r"https?://\S+", text)
    if not url_match:
        await update.message.reply_text("لطفاً یک لینک معتبر بفرست.")
        return

    url = url_match.group(0)
    platform = detect_platform(url)

    if platform == "unknown":
        await update.message.reply_text(
            "این لینک پشتیبانی نمیشه. فقط یوتیوب، اینستاگرام و توییتر(X) پشتیبانی میشن."
        )
        return

    if platform == "youtube":
        # برای یوتیوب گزینه ویدیو / صدا بده
        keyboard = [
            [
                InlineKeyboardButton("🎬 ویدیو", callback_data=f"yt_video|{url}"),
                InlineKeyboardButton("🎵 فقط صدا (MP3)", callback_data=f"yt_audio|{url}"),
            ]
        ]
        await update.message.reply_text(
            "چه فرمتی می‌خوای؟", reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # اینستاگرام و توییتر مستقیم دانلود می‌شن
    await process_download(update.message, url, platform)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, url = query.data.split("|", 1)

    if action == "yt_video":
        await process_download(query.message, url, "youtube", audio_only=False)
    elif action == "yt_audio":
        await process_download(query.message, url, "youtube", audio_only=True)


async def process_download(message, url: str, platform: str, audio_only: bool = False):
    status = await message.reply_text("⏳ در حال دانلود...")

    tmp_dir = tempfile.mkdtemp(prefix="dl_")
    try:
        filepath, error = await download_with_ytdlp(url, tmp_dir, audio_only=audio_only)

        if filepath is None:
            await status.edit_text(f"❌ دانلود انجام نشد.\n\nجزئیات خطا:\n{error}")
            return

        size_mb = os.path.getsize(filepath) / (1024 * 1024)
        if size_mb > MAX_FILE_SIZE_MB:
            await status.edit_text(
                f"❌ فایل {size_mb:.1f} مگابایته و بزرگ‌تر از محدودیت "
                f"{MAX_FILE_SIZE_MB} مگابایتی تلگرامه. کیفیت پایین‌تر رو امتحان کن."
            )
            return

        await status.edit_text("📤 در حال ارسال...")
        if audio_only:
            await message.reply_audio(audio=open(filepath, "rb"))
        else:
            await message.reply_video(video=open(filepath, "rb"), supports_streaming=True)

        await status.delete()

    except Exception as e:
        logger.exception("خطا در دانلود")
        await status.edit_text(f"❌ خطا: {e}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


async def download_with_ytdlp(url: str, out_dir: str, audio_only: bool = False):
    outtmpl = os.path.join(out_dir, "%(title).80s.%(ext)s")

    ydl_opts = {
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }

    # اگه فایل کوکی موجود باشه (برای دور زدن محدودیت ربات‌دیتکشن یوتیوب) ازش استفاده کن
    if os.path.exists(COOKIES_FILE):
        ydl_opts["cookiefile"] = COOKIES_FILE

    if audio_only:
        ydl_opts.update(
            {
                "format": "bestaudio/best",
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }
                ],
            }
        )
    else:
        # حجم رو زیر محدودیت تلگرام نگه داریم
        ydl_opts["format"] = (
            f"best[filesize<{MAX_FILE_SIZE_MB}M]/"
            "bestvideo[height<=720]+bestaudio/best[height<=720]/best"
        )

    def _run():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if "entries" in info:  # اگر پلی‌لیست بود، اولین آیتم
                info = info["entries"][0]
            filename = ydl.prepare_filename(info)
            if audio_only:
                base, _ = os.path.splitext(filename)
                filename = base + ".mp3"
            return filename

    import asyncio

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
    app.add_handler(CallbackQueryHandler(button_handler))

    print("✅ ربات روشن شد و در حال اجراست... (برای توقف Ctrl+C بزن)")
    app.run_polling()


if __name__ == "__main__":
    main()
