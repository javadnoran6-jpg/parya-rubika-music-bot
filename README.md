# ربات موزیکال پیشرفته روبیکا (سازنده: پریا چش رنگی)

این مخزن شامل **ربات کامل پایتون روبیکا** به همراه **ساخت خودکار فایل نصب اندروید (APK) در گیت‌هاب** است.

## ۱. اجرای مستقیم ربات پایتون
```bash
cd bot
pip install -r requirements.txt
export RUBIKA_BOT_TOKEN="PUT_YOUR_RUBIKA_TOKEN_HERE"
python3 rubika_music_bot.py
```

## ۲. ساخت فایل APK رایگان با GitHub Actions
1. یک مخزن جدید (Repository) در گیت‌هاب خود بسازید.
2. فایل‌های همین پکیج را به مخزن پوش (Push) یا آپلود کنید.
3. وارد تب **Actions** در گیت‌هاب شوید و روی **Build Android APK (Parya Rubika Music Bot)** کلیک کنید و گزینه **Run workflow** را بزنید.
4. پس از اتمام ساخت (~۸ دقیقه)، از بخش **Artifacts** فایل `ParyaRubikaMusicBot-APK` را دانلود و روی گوشی اندروید نصب کنید.
