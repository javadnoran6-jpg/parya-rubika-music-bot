#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ماژول ورود واقعی ربات به ویس‌چت گروهی روبیکا و پخش زنده صدا (Userbot RTC Streamer)
سازنده: پریا چش رنگی

چرا به این ماژول نیاز است؟
- Bot API رسمی روبیکا (botapi.rubika.ir/v3) متدی برای ورود به ویس‌چت گروه ندارد و فقط پیام و فایل می‌فرستد.
- برای اینکه ربات دقیقاً مانند BATMAN BOT در گروه بنویسد: «... یک گفتگوی گروهی را شروع کرد»
  و صدای واقعی آهنگ را داخل ویسکال روبیکا پخش کند، باید از سشن Userbot (کتابخانه rubpy[rtc] + aiortc + ffmpeg) استفاده شود.

پیش‌نیاز نصب:
  pip install -U "rubpy[rtc]" aiohttp av yt-dlp
  (و نصب ffmpeg روی سیستم یا Termux)

اجرای همگام با پنل (پیشنهادی):
  python3 rubika_userbot_vc.py --server "https://remix-remix-2138-619317218080.us-east1.run.app" --session "parya_userbot"
"""

import argparse
import asyncio
import os
import re
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import quote

import aiohttp

try:
    from aiortc import RTCPeerConnection, RTCSessionDescription
    from aiortc.contrib.media import MediaPlayer
except ImportError:
    RTCPeerConnection = None  # type: ignore
    RTCSessionDescription = None  # type: ignore
    MediaPlayer = None  # type: ignore

try:
    from rubpy import Client, filters, utils
except ImportError:
    Client = None  # type: ignore
    filters = None  # type: ignore
    utils = None  # type: ignore


DEFAULT_SERVER_URL = os.getenv("PARYA_BRIDGE_URL", "https://remix-remix-2138-619317218080.us-east1.run.app").rstrip("/")
DEFAULT_SESSION = os.getenv("RUBIKA_USERBOT_SESSION", "parya_userbot")


class RubikaLiveVoiceStreamer:
    def __init__(self, server_url: str, session_name: str) -> None:
        self.server_url = server_url.rstrip("/")
        self.session_name = session_name
        self.client: Any = None
        self.http: Optional[aiohttp.ClientSession] = None
        self.pc: Any = None
        self.player: Any = None
        self.active_chat_guid: Optional[str] = None
        self.active_vc_id: Optional[str] = None
        self.current_track_label: str = ""
        self.account_name: str = "Userbot"
        self.daily_counts: Dict[str, int] = {}

    async def report_status(self, connected: bool = True, last_error: str = "") -> None:
        if not self.http:
            return
        try:
            payload = {
                "connected": connected,
                "sessionName": self.session_name,
                "accountName": self.account_name,
                "activeVoiceChatId": self.active_vc_id or "",
                "activeChatGuid": self.active_chat_guid or "",
                "streamingTrack": self.current_track_label,
                "participantCount": 1 if self.active_vc_id else 0,
                "lastError": last_error,
            }
            async with self.http.post(
                f"{self.server_url}/api/userbot/status",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=6),
            ):
                pass
        except Exception:
            pass

    async def call_vc_method(self, *method_names: str, **kwargs: Any) -> Any:
        for name in method_names:
            fn = getattr(self.client, name, None)
            if callable(fn):
                try:
                    return await fn(**kwargs)
                except TypeError:
                    return await fn(*kwargs.values())
        # Fallback to raw rubpy builder call if present
        builder = getattr(self.client, "builder", None)
        if callable(builder):
            raw_name = "".join(w.capitalize() for w in method_names[0].split("_"))
            try:
                return await builder(raw_name, input=kwargs)
            except Exception as exc:
                raise RuntimeError(f"Rubika RPC {raw_name} failed: {exc}") from exc
        raise RuntimeError(f"روش‌های {method_names} در نسخه نصب‌شده rubpy یافت نشدند.")

    async def close_webrtc(self) -> None:
        if self.player:
            try:
                if getattr(self.player, "audio", None):
                    self.player.audio.stop()
            except Exception:
                pass
            self.player = None
        if self.pc:
            try:
                await self.pc.close()
            except Exception:
                pass
            self.pc = None

    async def speaking_loop(self, chat_guid: str, vc_id: str) -> None:
        while True:
            try:
                await self.call_vc_method(
                    "send_group_voice_chat_activity",
                    chat_guid=chat_guid,
                    voice_chat_id=vc_id,
                )
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(2.0)

    async def heartbeat_loop(self, chat_guid: str, vc_id: str) -> None:
        while True:
            try:
                await self.call_vc_method(
                    "get_group_voice_chat_updates",
                    chat_guid=chat_guid,
                    voice_chat_id=vc_id,
                )
                await asyncio.sleep(9.0)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(4.0)

    async def ensure_and_stream(
        self,
        chat_guid: str,
        stream_url: Optional[str] = None,
        track_title: str = "",
        track_artist: str = "",
    ) -> None:
        if RTCPeerConnection is None or MediaPlayer is None:
            raise RuntimeError("پکیج aiortc یا FFmpeg نصب نیست: pip install -U 'rubpy[rtc]' aiortc av")

        await self.close_webrtc()

        # 1) Create group voice chat (posts «... یک گفتگوی گروهی را شروع کرد» in Rubika)
        if not self.active_vc_id or self.active_chat_guid != chat_guid:
            res = await self.call_vc_method(
                "create_group_voice_chat",
                "createGroupVoiceChat",
                group_guid=chat_guid,
            )
            vc_obj = (res or {}).get("group_voice_chat_update", {}) if isinstance(res, dict) else {}
            vc_id = (
                vc_obj.get("voice_chat_id")
                or (res or {}).get("voice_chat_id")
                or (vc_obj.get("voice_chat") or {}).get("voice_chat_id")
                or (res.find_keys("voice_chat_id") if hasattr(res, "find_keys") else None)
            )
            if not vc_id and hasattr(res, "voice_chat_id"):
                vc_id = res.voice_chat_id
            self.active_chat_guid = chat_guid
            self.active_vc_id = str(vc_id or "")

        if not stream_url:
            await self.report_status(True)
            return

        # 2) Open live WebRTC RTCPeerConnection + FFmpeg MediaPlayer
        self.pc = RTCPeerConnection()
        self.player = MediaPlayer(stream_url, decode=True)
        if self.player.audio:
            self.pc.addTrack(self.player.audio)

        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)

        # 3) Join Rubika Group Voice Chat with SDP Offer & apply SDP Answer + Unmute + Activity loops
        join_res = await self.call_vc_method(
            "join_voice_chat",
            "joinGroupVoiceChat",
            chat_guid=chat_guid,
            voice_chat_id=self.active_vc_id,
            sdp_offer_data=self.pc.localDescription.sdp,
        )
        sdp_answer = ""
        if isinstance(join_res, dict):
            sdp_answer = join_res.get("sdp_answer_data") or ""
        elif hasattr(join_res, "sdp_answer_data"):
            sdp_answer = getattr(join_res, "sdp_answer_data") or ""

        try:
            await self.call_vc_method(
                "set_voice_chat_state",
                chat_guid=chat_guid,
                voice_chat_id=self.active_vc_id,
                action="Unmute",
            )
        except Exception:
            pass

        if sdp_answer:
            await self.pc.setRemoteDescription(
                RTCSessionDescription(sdp=sdp_answer, type="answer")
            )

        asyncio.create_task(self.speaking_loop(chat_guid, self.active_vc_id))
        asyncio.create_task(self.heartbeat_loop(chat_guid, self.active_vc_id))

        self.current_track_label = f"{track_title} — {track_artist}".strip(" —")
        await self.report_status(True)
        print(f"[VoiceChat] در حال خواندن در ویسکال {chat_guid}: {self.current_track_label}")

    async def stop_voice_chat(self) -> None:
        await self.close_webrtc()
        if self.active_chat_guid and self.active_vc_id:
            try:
                await self.call_vc_method(
                    "discard_voice_chat",
                    "leave_group_voice_chat",
                    object_guid=self.active_chat_guid,
                    voice_chat_id=self.active_vc_id,
                )
            except Exception:
                pass
        self.active_vc_id = None
        self.current_track_label = ""
        await self.report_status(True)

    async def search_itunes(self, query: str) -> Optional[Dict[str, str]]:
        assert self.http is not None
        url = f"https://itunes.apple.com/search?term={quote(query)}&media=music&entity=song&limit=5"
        async with self.http.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                data = await resp.json(content_type=None)
                for item in data.get("results", []):
                    if item.get("previewUrl"):
                        return {
                            "title": item.get("trackName", query),
                            "artist": item.get("artistName", "ناشناس"),
                            "url": item["previewUrl"],
                        }
        return None

    async def poll_bridge_tasks(self) -> None:
        assert self.http is not None
        tick = 0
        while True:
            try:
                async with self.http.get(
                    f"{self.server_url}/api/userbot/next-task",
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        task = data.get("task")
                        if task:
                            action = task.get("action")
                            chat_guid = task.get("rubikaChatId", "")
                            if action == "start_call" and chat_guid:
                                await self.ensure_and_stream(chat_guid)
                            elif action in {"play_in_vc", "resume_vc"} and chat_guid:
                                await self.ensure_and_stream(
                                    chat_guid,
                                    task.get("streamUrl"),
                                    task.get("trackTitle", ""),
                                    task.get("trackArtist", ""),
                                )
                            elif action in {"stop_vc", "pause_vc"}:
                                await self.stop_voice_chat()
                tick += 1
                if tick % 8 == 0:
                    await self.report_status(True)
            except Exception as exc:
                await self.report_status(True, str(exc))
            await asyncio.sleep(1.1)

    async def run(self) -> None:
        if Client is None:
            raise SystemExit("کتابخانه rubpy نصب نیست. اجرا کنید: pip install -U 'rubpy[rtc]' aiortc av")

        async with aiohttp.ClientSession() as http:
            self.http = http
            async with Client(name=self.session_name) as client:
                self.client = client
                try:
                    me = await client.get_me()
                    user_obj = (me or {}).get("user", {}) if isinstance(me, dict) else {}
                    self.account_name = (
                        f"{user_obj.get('first_name', '')} {user_obj.get('last_name', '')}".strip()
                        or getattr(me, "first_name", "")
                        or self.session_name
                    )
                except Exception:
                    self.account_name = self.session_name

                await self.report_status(True)
                print(f"[Userbot] متصل شد: {self.account_name} | Bridge: {self.server_url}")

                @client.on_message_updates()
                async def on_group_msg(message: Any) -> None:
                    text = (getattr(message, "raw_text", None) or getattr(message, "text", None) or "").strip()
                    chat_guid = getattr(message, "object_guid", "")
                    if not text or not chat_guid:
                        return
                    play_m = re.match(r"^(پخش آهنگ|پخش موزیک|آهنگ|موزیک)\s+(.+)$", text)
                    if play_m:
                        q = play_m.group(2).strip()
                        track = await self.search_itunes(q)
                        if not track:
                            await message.reply(f"❌ نتیجه‌ای برای «{q}» پیدا نشد.")
                            return
                        today_key = f"{chat_guid}:{datetime.now().strftime('%Y-%m-%d')}"
                        self.daily_counts[today_key] = self.daily_counts.get(today_key, 0) + 1
                        cnt = self.daily_counts[today_key]
                        await message.reply(
                            f"🎶 پخش آغاز شد\n🎵 {track['title']} — {track['artist']} 320\n📊 سهمیهٔ امروز: {cnt}/10"
                        )
                        await self.ensure_and_stream(chat_guid, track["url"], track["title"], track["artist"])
                    elif text in {"قطع ویسکال", "Kill", "Kill ⚔️", "خروج"}:
                        await self.stop_voice_chat()
                        await message.reply("⏹ گفتگوی گروهی و پخش زنده پایان یافت.")

                bridge_task = asyncio.create_task(self.poll_bridge_tasks())
                try:
                    await client.run_until_disconnected()
                finally:
                    bridge_task.cancel()
                    await self.stop_voice_chat()
                    await self.report_status(False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rubika Live Voice Chat Userbot Streamer")
    parser.add_argument("--server", default=DEFAULT_SERVER_URL, help="آدرس سرور پنل وب")
    parser.add_argument("--session", default=DEFAULT_SESSION, help="نام فایل سشن Userbot")
    args = parser.parse_args()
    asyncio.run(RubikaLiveVoiceStreamer(args.server, args.session).run())
