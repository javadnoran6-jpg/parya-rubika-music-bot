#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
اپلیکیشن اندروید ربات موزیکال روبیکا (ساخت APK با Buildozer & GitHub Actions)
سازنده: پریا چش رنگی
"""

import os
import threading
import asyncio

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

from rubika_music_bot import RubikaMusicBot

Window.clearcolor = (0.043, 0.059, 0.09, 1)


class ParyaRubikaApp(App):
    def build(self):
        self.title = "Rubika Music Bot - پریا چش رنگی"
        self.bot = None
        self.bot_thread = None

        root = BoxLayout(orientation="vertical", padding=16, spacing=12)

        header = Label(
            text="Parya Rubika Music Bot\nToken Ready | Voice Call & Group Controller",
            size_hint=(1, 0.14),
            color=(0.06, 0.72, 0.50, 1),
            font_size="18sp",
            bold=True,
        )
        root.add_widget(header)

        self.token_input = TextInput(
            text=os.getenv("RUBIKA_BOT_TOKEN", ""),
            multiline=False,
            size_hint=(1, 0.09),
            background_color=(0.08, 0.11, 0.16, 1),
            foreground_color=(0.95, 0.97, 1, 1),
        )
        root.add_widget(self.token_input)

        btn_row = BoxLayout(size_hint=(1, 0.1), spacing=10)
        self.start_btn = Button(
            text="Start Rubika Bot",
            background_color=(0.06, 0.72, 0.50, 1),
            on_press=self.start_bot,
        )
        self.stop_btn = Button(
            text="Stop Bot",
            background_color=(0.86, 0.15, 0.15, 1),
            on_press=self.stop_bot,
        )
        btn_row.add_widget(self.start_btn)
        btn_row.add_widget(self.stop_btn)
        root.add_widget(btn_row)

        self.log_label = Label(
            text="Ready to connect to Rubika Bot API v3...\n",
            size_hint_y=None,
            halign="left",
            valign="top",
            color=(0.85, 0.89, 0.94, 1),
        )
        self.log_label.bind(texture_size=self.log_label.setter("size"))
        scroll = ScrollView(size_hint=(1, 0.67))
        scroll.add_widget(self.log_label)
        root.add_widget(scroll)
        return root

    def append_log(self, msg: str):
        Clock.schedule_once(lambda dt: setattr(self.log_label, "text", self.log_label.text + msg + "\n"))

    def start_bot(self, _instance):
        if self.bot and self.bot.running:
            self.append_log("[Info] Bot is already running.")
            return
        os.environ["RUBIKA_BOT_TOKEN"] = self.token_input.text.strip()
        self.bot = RubikaMusicBot()

        def _runner():
            try:
                self.append_log("[Start] Connecting to botapi.rubika.ir/v3 ...")
                asyncio.run(self.bot.run())
            except Exception as e:
                self.append_log(f"[Error] {e}")

        self.bot_thread = threading.Thread(target=_runner, daemon=True)
        self.bot_thread.start()

    def stop_bot(self, _instance):
        if self.bot:
            self.bot.running = False
            self.append_log("[Stop] Bot polling stopped.")


if __name__ == "__main__":
    ParyaRubikaApp().run()
