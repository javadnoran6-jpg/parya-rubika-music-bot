#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ربات موزیکال پیشرفته روبیکا (کاربر محور)
سازنده: پریا چش رنگی
پشتیبانی از Bot API v3 و کلاینت Userbot (rubpy) برای مدیریت ویسکال گروهی
"""

import asyncio
import json
import os
import random
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import aiohttp

# تنظیمات اصلی ربات
BOT_TOKEN = os.getenv("RUBIKA_BOT_TOKEN", "PUT_YOUR_RUBIKA_TOKEN_HERE")
CREATOR_NAME = "پریا چش رنگی"
CREATOR_ID = os.getenv("RUBIKA_CREATOR_ID", "creator")
API_BASE = f"https://botapi.rubika.ir/v3/{BOT_TOKEN}"
DB_PATH = os.getenv("BOT_DB_PATH", "parya_music_bot.db")

HELP_TEXT = f"""🎵 راهنمای ربات موزیکال پیشرفته روبیکا
👑 سازنده: {CREATOR_NAME}

🔍 جستجوی آهنگ:
• آهنگ {{نام موسیقی}}  (مثال: آهنگ لری)

🔗 پخش از لینک مستقیم:
• پخش ویسکال {{لینک دانلود}}

⏹ توقف پخش و ذخیره آهنگ:
• قطع ویسکال / توقف آهنگ / خروج / توقف

▶️ ادامه آهنگ متوقف‌شده:
• ادامه آهنگ

🔄 پخش با ریپلای:
• روی فایل صوتی یا لینک ریپلای کنید و ارسال کنید: پخش ریپلای

🎲 پخش تصادفی:
• پخش رندوم

📋 مدیریت صف و تاریخچه:
• بعدی — پخش آهنگ بعدی از صف
• قبلی — پخش آهنگ قبلی از تاریخچه
• صف / لیست پخش — نمایش لیست صف
• اضافه به صف (+ ریپلای یا لینک)
• پاک کردن صف — خالی کردن کل صف
• حذف از صف {{شماره}} — حذف آهنگ از صف
• تاریخچه آهنگها — نمایش ۵ آهنگ آخر پخش شده

⚡ پخش فوری:
• پخش فوری (+ ریپلای یا لینک)

🔊 کنترل صدا:
• تنظیم صدا {{0-100}}
• بیصدا — سکوت در کال با ادامه پخش
• باصدا — باز کردن صدا در کال

👑 مدیریت گروه و دسترسی:
• مالک گروه — نمایش شناسه مالک
• ویژه (+ ریپلای) — ویژه کردن کاربر
• حذف ویژه (+ ریپلای) — حذف ویژه بودن کاربر
• تنظیم مالک (+ ریپلای) — تعیین مالک (فقط سازنده)
• دسترسی عموم باز / دسترسی عموم قفل باشد
• مقام — نمایش مقام شما در گروه

📞 کال و اشتراک:
• ساخت کال — ایجاد ویس چت در گروه
• وضعیت — نمایش تاریخ خرید، انقضا و دسترسی"""


class BotDatabase:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self) -> None:
        cur = self.conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS groups (
                chat_id TEXT PRIMARY KEY,
                title TEXT,
                owner_id TEXT,
                public_access TEXT DEFAULT 'open',
                volume INTEGER DEFAULT 80,
                is_muted INTEGER DEFAULT 0,
                is_playing INTEGER DEFAULT 0,
                voice_call_active INTEGER DEFAULT 0,
                current_track TEXT,
                paused_track TEXT,
                queue_json TEXT DEFAULT '[]',
                history_json TEXT DEFAULT '[]',
                purchased_at TEXT,
                expires_at TEXT,
                auto_shutdown_time TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS members (
                chat_id TEXT,
                user_id TEXT,
                role TEXT DEFAULT 'member',
                PRIMARY KEY (chat_id, user_id)
            )
        """)
        self.conn.commit()

    def ensure_group(self, chat_id: str, title: str = "گروه موزیکال اصلی") -> sqlite3.Row:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM groups WHERE chat_id = ?", (chat_id,))
        row = cur.fetchone()
        if not row:
            now = datetime.now()
            expires = now + timedelta(days=30)
            cur.execute(
                """
                INSERT INTO groups (chat_id, title, owner_id, public_access, purchased_at, expires_at)
                VALUES (?, ?, ?, 'open', ?, ?)
                """,
                (chat_id, title, CREATOR_ID, now.strftime("%Y-%m-%d"), expires.strftime("%Y-%m-%d")),
            )
            self.conn.commit()
            cur.execute("SELECT * FROM groups WHERE chat_id = ?", (chat_id,))
            row = cur.fetchone()
        return row

    def get_role(self, chat_id: str, user_id: str) -> str:
        if user_id == CREATOR_ID:
            return "creator"
        grp = self.ensure_group(chat_id)
        if grp["owner_id"] == user_id:
            return "owner"
        cur = self.conn.cursor()
        cur.execute("SELECT role FROM members WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        r = cur.fetchone()
        return r["role"] if r else "member"

    def set_role(self, chat_id: str, user_id: str, role: str) -> None:
        self.conn.execute(
            "INSERT INTO members (chat_id, user_id, role) VALUES (?, ?, ?) "
            "ON CONFLICT(chat_id, user_id) DO UPDATE SET role = excluded.role",
            (chat_id, user_id, role),
        )
        self.conn.commit()

    def update_group(self, chat_id: str, **fields: Any) -> None:
        cols = ", ".join(f"{k} = ?" for k in fields.keys())
        vals = list(fields.values()) + [chat_id]
        self.conn.execute(f"UPDATE groups SET {cols} WHERE chat_id = ?", vals)
        self.conn.commit()


class RubikaMusicBot:
    def __init__(self) -> None:
        self.db = BotDatabase(DB_PATH)
        self.offset: Optional[str] = None
        self.session: Optional[aiohttp.ClientSession] = None
        self.running = False

    async def api_call(self, method: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        assert self.session is not None
        url = f"{API_BASE}/{method}"
        async with self.session.post(url, json=payload or {}, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            try:
                return await resp.json()
            except Exception:
                return {"status": "ERROR", "raw": await resp.text()}

    async def send_text(self, chat_id: str, text: str, reply_to: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_to:
            payload["reply_to_message_id"] = reply_to
        return await self.api_call("sendMessage", payload)

    async def search_music(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        assert self.session is not None
        url = f"https://itunes.apple.com/search?term={quote(query)}&media=music&entity=song&limit={limit}"
        try:
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    results = []
                    for item in data.get("results", []):
                        if item.get("previewUrl"):
                            results.append({
                                "title": item.get("trackName", query),
                                "artist": item.get("artistName", "ناشناس"),
                                "url": item["previewUrl"],
                                "duration": max(30, round(item.get("trackTimeMillis", 30000) / 1000)),
                            })
                    return results
        except Exception as e:
            print(f"[SearchError] {e}")
        return []

    def has_permission(self, chat_id: str, user_id: str) -> bool:
        grp = self.db.ensure_group(chat_id)
        if grp["public_access"] == "open":
            return True
        return self.db.get_role(chat_id, user_id) in {"creator", "owner", "admin", "vip"}

    async def handle_message(self, msg: Dict[str, Any]) -> None:
        chat_id = str(msg.get("chat_id", ""))
        sender_id = str(msg.get("sender_id", ""))
        message_id = str(msg.get("message_id", ""))
        text = (msg.get("text") or "").strip()
        if not chat_id or not text:
            return

        grp = self.db.ensure_group(chat_id)
        role = self.db.get_role(chat_id, sender_id)
        reply_msg = msg.get("reply_to_message") or {}
        reply_sender_id = str(reply_msg.get("sender_id", ""))
        reply_text = (reply_msg.get("text") or "").strip()
        reply_file = reply_msg.get("file_inline") or {}

        # دستورات عمومی و راهنما
        if text in {"راهنما", "راهنمای ربات", "/start", "/help"}:
            await self.send_text(chat_id, HELP_TEXT, message_id)
            return

        if text == "مقام":
            role_labels = {
                "creator": f"سازنده ربات ({CREATOR_NAME})",
                "owner": "مالک گروه",
                "admin": "ادمین گروه",
                "vip": "کاربر ویژه",
                "member": "کاربر عادی",
            }
            await self.send_text(chat_id, f"🔵 مقام شما در این گروه: {role_labels.get(role, 'عادی')}", message_id)
            return

        if text == "مالک گروه":
            await self.send_text(chat_id, f"🟢 شناسه مالک فعلی گروه: {grp['owner_id']}", message_id)
            return

        if text == "وضعیت":
            exp = datetime.strptime(grp["expires_at"], "%Y-%m-%d")
            days_left = max(0, (exp - datetime.now()).days)
            access_fa = "باز برای همه اعضا" if grp["public_access"] == "open" else "قفل (فقط ویژه و ادمین)"
            status_msg = (
                f"🔐 وضعیت اشتراک ربات موزیکال\n"
                f"📅 تاریخ خرید: {grp['purchased_at']}\n"
                f"⏳ تاریخ انقضا: {grp['expires_at']}\n"
                f"📆 روزهای باقیمانده: {days_left} روز\n"
                f"🔓 دسترسی عمومی: {access_fa}\n"
                f"👑 سازنده: {CREATOR_NAME}"
            )
            await self.send_text(chat_id, status_msg, message_id)
            return

        # دستورات مدیریت مالکیت و دسترسی
        if text == "تنظیم مالک":
            if role != "creator":
                await self.send_text(chat_id, "⛔ فقط سازنده ربات مجاز به تعیین مالک گروه است.", message_id)
                return
            if not reply_sender_id:
                await self.send_text(chat_id, "⚠ لطفاً روی پیام کاربر مورد نظر ریپلای کنید.", message_id)
                return
            self.db.update_group(chat_id, owner_id=reply_sender_id)
            self.db.set_role(chat_id, reply_sender_id, "owner")
            await self.send_text(chat_id, f"👑 کاربر {reply_sender_id} به عنوان مالک گروه تنظیم شد.", message_id)
            return

        if text == "ویژه":
            if role not in {"creator", "owner", "admin"}:
                await self.send_text(chat_id, "⛔ فقط مالک یا ادمین گروه مجاز است.", message_id)
                return
            if not reply_sender_id:
                await self.send_text(chat_id, "⚠ لطفاً روی پیام کاربر ریپلای کنید و ارسال کنید: ویژه", message_id)
                return
            self.db.set_role(chat_id, reply_sender_id, "vip")
            await self.send_text(chat_id, f"⭐ کاربر {reply_sender_id} با موفقیت ویژه شد.", message_id)
            return

        if text == "حذف ویژه":
            if role not in {"creator", "owner"}:
                await self.send_text(chat_id, "⛔ فقط مالک گروه یا سازنده ربات می‌تواند ویژه را حذف کند.", message_id)
                return
            if not reply_sender_id:
                await self.send_text(chat_id, "⚠ روی پیام کاربر ریپلای کنید.", message_id)
                return
            self.db.set_role(chat_id, reply_sender_id, "member")
            await self.send_text(chat_id, f"🗑 وضعیت ویژه کاربر {reply_sender_id} حذف شد.", message_id)
            return

        if text == "دسترسی عموم باز":
            if role not in {"creator", "owner", "admin"}:
                await self.send_text(chat_id, "⛔ دسترسی تغییر تنظیمات ندارید.", message_id)
                return
            self.db.update_group(chat_id, public_access="open")
            await self.send_text(chat_id, "🔓 دسترسی عمومی باز شد. همه اعضا می‌توانند از ربات استفاده کنند.", message_id)
            return

        if text == "دسترسی عموم قفل باشد":
            if role not in {"creator", "owner", "admin"}:
                await self.send_text(chat_id, "⛔ دسترسی تغییر تنظیمات ندارید.", message_id)
                return
            self.db.update_group(chat_id, public_access="locked")
            await self.send_text(chat_id, "🔒 دسترسی عمومی قفل شد. فقط کاربران ویژه و ادمین‌ها دسترسی دارند.", message_id)
            return

        # بررسی دسترسی برای دستورات پخش موسیقی
        if not self.has_permission(chat_id, sender_id):
            await self.send_text(chat_id, "🔒 دسترسی عمومی قفل است. فقط کاربران ویژه و ادمین‌ها مجاز هستند.", message_id)
            return

        queue: List[Dict[str, Any]] = json.loads(grp["queue_json"] or "[]")
        history: List[Dict[str, Any]] = json.loads(grp["history_json"] or "[]")
        current = json.loads(grp["current_track"]) if grp["current_track"] else None
        paused = json.loads(grp["paused_track"]) if grp["paused_track"] else None

        if text == "ساخت کال":
            self.db.update_group(chat_id, voice_call_active=1)
            await self.send_text(chat_id, "📞 ویس‌چت (کال) گروه فعال شد. ربات آماده پخش موسیقی در کال است.", message_id)
            return

        if text == "بیصدا":
            self.db.update_group(chat_id, is_muted=1)
            await self.send_text(chat_id, "🟣 ربات در کال بی‌صدا شد (آهنگ در پس‌زمینه در حال پخش است).", message_id)
            return

        if text == "باصدا":
            self.db.update_group(chat_id, is_muted=0)
            await self.send_text(chat_id, "🟠 ربات از حالت بی‌صدا خارج شد و آهنگ در حال پخش است ✅", message_id)
            return

        vol_match = re.match(r"^تنظیم صدا\s+(\d{1,3})$", text)
        if vol_match:
            vol = max(0, min(100, int(vol_match.group(1))))
            self.db.update_group(chat_id, volume=vol)
            await self.send_text(chat_id, f"🔊 صدای پخش روی {vol} درصد تنظیم شد.", message_id)
            return

        if text in {"قطع ویسکال", "توقف آهنگ", "خروج", "توقف"}:
            if current:
                self.db.update_group(chat_id, paused_track=json.dumps(current, ensure_ascii=False), current_track=None, is_playing=0)
                await self.send_text(chat_id, f"⏹ پخش آهنگ «{current['title']}» متوقف و برای ادامه ذخیره شد.", message_id)
            else:
                self.db.update_group(chat_id, is_playing=0, voice_call_active=0)
                await self.send_text(chat_id, "⏹ ویسکال متوقف شد.", message_id)
            return

        if text == "ادامه آهنگ":
            if paused:
                self.db.update_group(chat_id, current_track=json.dumps(paused, ensure_ascii=False), paused_track=None, is_playing=1, voice_call_active=1)
                await self.send_text(chat_id, f"▶️ ادامه پخش آهنگ «{paused['title']}» در ویسکال.", message_id)
            else:
                await self.send_text(chat_id, "⚠ آهنگ متوقف‌شده‌ای برای ادامه وجود ندارد.", message_id)
            return

        if text in {"صف", "لیست پخش"}:
            if not queue:
                await self.send_text(chat_id, "📋 صف پخش در حال حاضر خالی است.", message_id)
                return
            lines = [f"{i+1}. {t['title']} - {t.get('artist', '')}" for i, t in enumerate(queue)]
            await self.send_text(chat_id, "📋 لیست صف پخش:\n" + "\n".join(lines), message_id)
            return

        if text == "پاک کردن صف":
            self.db.update_group(chat_id, queue_json="[]")
            await self.send_text(chat_id, "🗑 کل صف پخش پاک شد.", message_id)
            return

        del_match = re.match(r"^حذف از صف\s+(\d+)$", text)
        if del_match:
            idx = int(del_match.group(1)) - 1
            if 0 <= idx < len(queue):
                removed = queue.pop(idx)
                self.db.update_group(chat_id, queue_json=json.dumps(queue, ensure_ascii=False))
                await self.send_text(chat_id, f"🗑 آهنگ «{removed['title']}» از صف حذف شد.", message_id)
            else:
                await self.send_text(chat_id, "⚠ شماره آهنگ در صف معتبر نیست.", message_id)
            return

        if text == "تاریخچه آهنگها":
            last5 = history[-5:][::-1]
            if not last5:
                await self.send_text(chat_id, "📜 تاریخچه آهنگ‌ها خالی است.", message_id)
                return
            lines = [f"{i+1}. {t['title']} - {t.get('artist', '')}" for i, t in enumerate(last5)]
            await self.send_text(chat_id, "📜 ۵ آهنگ آخر پخش‌شده:\n" + "\n".join(lines), message_id)
            return

        if text == "بعدی":
            if not queue:
                await self.send_text(chat_id, "⚠ صف خالی است.", message_id)
                return
            if current:
                history.append(current)
            nxt = queue.pop(0)
            self.db.update_group(
                chat_id,
                current_track=json.dumps(nxt, ensure_ascii=False),
                queue_json=json.dumps(queue, ensure_ascii=False),
                history_json=json.dumps(history[-20:], ensure_ascii=False),
                is_playing=1,
                voice_call_active=1,
            )
            await self.send_text(chat_id, f"⏭ پخش آهنگ بعدی: {nxt['title']}", message_id)
            return

        if text == "قبلی":
            if not history:
                await self.send_text(chat_id, "⚠ آهنگی در تاریخچه وجود ندارد.", message_id)
                return
            prev_track = history.pop()
            if current:
                queue.insert(0, current)
            self.db.update_group(
                chat_id,
                current_track=json.dumps(prev_track, ensure_ascii=False),
                queue_json=json.dumps(queue, ensure_ascii=False),
                history_json=json.dumps(history, ensure_ascii=False),
                is_playing=1,
                voice_call_active=1,
            )
            await self.send_text(chat_id, f"⏮ بازگشت به آهنگ قبلی: {prev_track['title']}", message_id)
            return

        if text in {"پخش رندوم", "پخش رندوم شاد", "پخش شاد", "آهنگ شاد", "پخش رندوم غمگین", "پخش غمگین", "آهنگ غمگین"}:
            happy_seeds = ["بهنام بانی", "ماکان بند", "پازل بند", "اندی", "سندی", "شهرام شب پره", "بنیامین بهادری", "محسن ابراهیم زاده", "آهنگ شاد ایرانی"]
            sad_seeds = ["محسن چاوشی", "محسن یگانه", "مرتضی پاشایی", "مجید خراطها", "رضا بهرام", "داریوش", "هایده", "مهستی", "علی یاسینی", "احسان خواجه امیری"]
            if "شاد" in text:
                pool = await self.search_music(random.choice(happy_seeds), 50)
            elif "غمگین" in text:
                pool = await self.search_music(random.choice(sad_seeds), 50)
            else:
                pool = queue or history or await self.search_music(random.choice(happy_seeds + sad_seeds), 50)
            if not pool:
                await self.send_text(chat_id, "⚠ آهنگی برای پخش تصادفی یافت نشد.", message_id)
                return
            chosen = random.choice(pool)
            if current:
                history.append(current)
            self.db.update_group(
                chat_id,
                current_track=json.dumps(chosen, ensure_ascii=False),
                history_json=json.dumps(history[-20:], ensure_ascii=False),
                is_playing=1,
                voice_call_active=1,
            )
            await self.send_text(chat_id, f"🎲 پخش تصادفی در ویسکال: {chosen['title']} - {chosen.get('artist', '')}", message_id)
            return

        # پخش با لینک مستقیم، ریپلای، اضافه به صف یا پخش فوری
        url_match = re.search(r"(https?://\S+)", text) or re.search(r"(https?://\S+)", reply_text)
        if text.startswith("پخش ویسکال ") or text in {"پخش ریپلای", "پخش فوری", "اضافه به صف"} or text.startswith("پخش فوری ") or text.startswith("اضافه به صف "):
            track_url = url_match.group(1) if url_match else reply_file.get("file_id", "")
            track_title = reply_file.get("file_name") or text.replace("پخش ویسکال", "").strip() or "موزیک مستقیم"
            if not track_url:
                await self.send_text(chat_id, "⚠ لینک مستقیم یا ریپلای روی فایل صوتی یافت نشد.", message_id)
                return
            new_track = {"title": track_title, "artist": "لینک مستقیم", "url": track_url}
            if text.startswith("اضافه به صف"):
                queue.append(new_track)
                self.db.update_group(chat_id, queue_json=json.dumps(queue, ensure_ascii=False))
                await self.send_text(chat_id, f"➕ آهنگ «{new_track['title']}» به صف اضافه شد (شماره {len(queue)}).", message_id)
                return
            if current:
                history.append(current)
            self.db.update_group(
                chat_id,
                current_track=json.dumps(new_track, ensure_ascii=False),
                history_json=json.dumps(history[-20:], ensure_ascii=False),
                is_playing=1,
                voice_call_active=1,
            )
            mode_label = "⚡ پخش فوری" if "فوری" in text else "🎧 پخش در ویسکال"
            await self.send_text(chat_id, f"{mode_label}: {new_track['title']}", message_id)
            return

        if text.startswith("آهنگ "):
            query = text[len("آهنگ "):].strip()
            results = await self.search_music(query)
            if not results:
                await self.send_text(chat_id, f"❌ آهنگی با عنوان «{query}» پیدا نشد.", message_id)
                return
            chosen = results[0]
            if current:
                history.append(current)
            self.db.update_group(
                chat_id,
                current_track=json.dumps(chosen, ensure_ascii=False),
                history_json=json.dumps(history[-20:], ensure_ascii=False),
                is_playing=1,
                voice_call_active=1,
            )
            await self.send_text(
                chat_id,
                f"🎵 در حال پخش در ویسکال:\n🎶 {chosen['title']} — {chosen['artist']}\n🔗 {chosen['url']}",
                message_id,
            )

        if text.startswith("تنظیم خاموشی ") or text.startswith("خاموشی خودکار "):
            if role not in {"creator", "owner", "admin"}:
                await self.send_text(chat_id, "⛔ فقط مالک، ادمین یا سازنده مجاز به تنظیم تایمر است.", message_id)
                return
            t_str = text.split()[-1].strip()
            if not re.match(r"^([01]?\d|2[0-3]):[0-5]\d$", t_str):
                await self.send_text(chat_id, "⚠ فرمت ساعت اشتباه است. مثال: تنظیم خاموشی 23:30", message_id)
                return
            self.db.update_group(chat_id, auto_shutdown_time=t_str)
            await self.send_text(chat_id, f"⏰ تایمر قطع خودکار ویسکال روی ساعت {t_str} تنظیم شد.", message_id)
            return

        if text in {"لغو خاموشی", "لغو تایمر"}:
            self.db.update_group(chat_id, auto_shutdown_time=None)
            await self.send_text(chat_id, "⏰ تایمر خاموشی خودکار ویسکال لغو شد.", message_id)
            return

    async def check_auto_shutdowns(self) -> None:
        now_hm = datetime.now().strftime("%H:%M")
        cur = self.db.conn.cursor()
        cur.execute("SELECT * FROM groups WHERE auto_shutdown_time = ?", (now_hm,))
        for grp in cur.fetchall():
            chat_id = grp["chat_id"]
            self.db.update_group(chat_id, is_playing=0, voice_call_active=0, auto_shutdown_time=None)
            await self.send_text(chat_id, f"⏰ زمان خودکار ({now_hm}) فرا رسید: ویسکال قطع شد و ربات متوقف گردید.")

    async def run(self) -> None:
        self.running = True
        async with aiohttp.ClientSession() as session:
            self.session = session
            me = await self.api_call("getMe")
            print(f"[RubikaMusicBot] سازنده: {CREATOR_NAME} | وضعیت توکن: {me}")
            while self.running:
                try:
                    await self.check_auto_shutdowns()
                    payload = {"limit": 50}
                    if self.offset:
                        payload["offset_id"] = self.offset
                    res = await self.api_call("getUpdates", payload)
                    updates = res.get("data", {}).get("updates", []) if isinstance(res.get("data"), dict) else []
                    for upd in updates:
                        self.offset = upd.get("next_offset_id") or self.offset
                        if upd.get("new_message"):
                            await self.handle_message(upd["new_message"])
                except Exception as exc:
                    print(f"[PollingError] {exc}")
                await asyncio.sleep(1.5)


if __name__ == "__main__":
    bot = RubikaMusicBot()
    asyncio.run(bot.run())
