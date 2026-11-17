[app]
title = Parya Rubika Music Bot
package.name = paryarubikamusicbot
package.domain = ir.parya.rubikabot
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,db,json
version = 1.0.0

requirements = python3,kivy==2.3.0,aiohttp,certifi,openssl,charset-normalizer,idna,multidict,yarl,aiosignal,frozenlist,async-timeout

orientation = portrait
fullscreen = 0

android.permissions = INTERNET,ACCESS_NETWORK_STATE,RECORD_AUDIO,MODIFY_AUDIO_SETTINGS,WAKE_LOCK,FOREGROUND_SERVICE
android.api = 34
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a,armeabi-v7a
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 1
