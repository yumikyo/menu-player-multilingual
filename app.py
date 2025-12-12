import streamlit as st
import os
import asyncio
import json
import nest_asyncio
import time
import shutil
import zipfile
import re
import base64
from datetime import datetime
from gtts import gTTS
import google.generativeai as genai
from google.api_core import exceptions
import requests
from bs4 import BeautifulSoup
import edge_tts
import streamlit.components.v1 as components
from PIL import Image

# 非同期処理の適用
nest_asyncio.apply()

# ページ設定
st.set_page_config(page_title="Menu Player Generator (Multi-Lang)", layout="wide")

# --- 言語設定・定数 ---
LANG_CONFIG = {
    "日本語": {
        "voice": "ja-JP-NanamiNeural",
        "prompt_target": "日本語",
        "currency": "円",
        "intro_template": "こんにちは、{store}です。ただいまより{title}をご紹介します。",
        "ui": {
            "loading": "読み込み中...", "chapter": "チャプター一覧", "speed": "読み上げ速度",
            "map": "地図・アクセス (Google Map)", "play": "再生", "pause": "一時停止",
            "prev": "前へ", "next": "次へ", "slow": "ゆっくり", "normal": "標準", "fast": "速く"
        }
    },
    "English": {
        "voice": "en-US-AriaNeural",
        "prompt_target": "英語 (English)",
        "currency": "yen",
        "intro_template": "Hello, this is {store}. We would like to introduce our {title} menu.",
        "ui": {
            "loading": "Loading...", "chapter": "Chapters", "speed": "Speed",
            "map": "Map & Access (Google Map)", "play": "Play", "pause": "Pause",
            "prev": "Prev", "next": "Next", "slow": "Slow", "normal": "Normal", "fast": "Fast"
        }
    },
    "中文 (简体)": {
        "voice": "zh-CN-XiaoxiaoNeural",
        "prompt_target": "中国語 (Simplified Chinese)",
        "currency": "日元",
        "intro_template": "你好，这里是{store}。现在为您介绍{title}。",
        "ui": {
            "loading": "加载中...", "chapter": "章节列表", "speed": "语速",
            "map": "地图 (Google Map)", "play": "播放", "pause": "暂停",
            "prev": "上一个", "next": "下一个", "slow": "慢速", "normal": "标准", "fast": "快速"
        }
    },
    "한국어": {
        "voice": "ko-KR-SunHiNeural",
        "prompt_target": "韓国語 (Korean)",
        "currency": "엔",
        "intro_template": "안녕하세요, {store}입니다. 지금부터 {title}를 소개해 드리겠습니다.",
        "ui": {
            "loading": "로딩 중...", "chapter": "챕터 목록", "speed": "재생 속도",
            "map": "지도 (Google Map)", "play": "재생", "pause": "일시 정지",
            "prev": "이전", "next": "다음", "slow": "느리게", "normal": "보통", "fast": "빠르게"
        }
    }
}

# --- 関数定義 ---
def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", name).replace(" ", "_").replace("　", "_")

def fetch_text_from_url(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        response.encoding = response.apparent_encoding
        soup = BeautifulSoup(response.text, 'html.parser')
        for s in soup(["script", "style", "header", "footer", "nav"]): s.extract()
        text = soup.get_text(separator="\n")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(lines)
    except: return None

async def generate_single_track_fast(text, filename, voice_code, rate_value):
    for attempt in range(3):
        try:
            comm = edge_tts.Communicate(text, voice_code, rate=rate_value)
            await comm.save(filename)
            if os.path.exists(filename) and os.path.getsize(filename) > 0:
                return True
        except:
            await asyncio.sleep(1)
    # gTTS fallback (multilingual support)
    try:
        lang_code = voice_code[:2].lower() # ja, en, zh, ko
        def gtts_task():
            tts = gTTS(text=text, lang=lang_code)
            tts.save(filename)
        await asyncio.to_thread(gtts_task)
        return True
    except:
        return False

async def process_all_tracks_fast(menu_data, output_dir, voice_code, rate_value, progress_bar):
    tasks = []
    track_info_list = []
    for i, track in enumerate(menu_data):
        safe_title = sanitize_filename(track['title'])
        filename = f"{i+1:02}_{safe_title}.mp3"
        save_path = os.path.join(output_dir, filename)
        speech_text = track['text']
        # 2トラック目以降はタイトルを含める（多言語対応のため番号の読み上げは言語に任せるかシンプルに）
        if i > 0: speech_text = f"{track['title']}.\n{track['text']}"
        tasks.append(generate_single_track_fast(speech_text, save_path, voice_code, rate_value))
        track_info_list.append({"title": track['title'], "path": save_path})
    
    total = len(tasks)
    completed = 0
    for task in asyncio.as_completed(tasks):
        await task
        completed += 1
        progress_bar.progress(completed / total)
    return track_info_list

# HTMLプレイヤー生成（多言語UI対応）
def create_standalone_html_player(store_name, menu_data, lang_settings, map_url=""):
    playlist_js = []
    for track in menu_data:
        file_path = track['path']
        if os.path.exists(file_path):
            with open(file_path, "rb") as f:
                b64_data = base64.b64encode(f.read()).decode()
                playlist_js.append({"title": track['title'], "src": f"data:audio/mp3;base64,{b64_data}"})
    playlist_json_str = json.dumps(playlist_js, ensure_ascii=False)
    
    ui = lang_settings["ui"]
    
    map_button_html = ""
    if map_url:
        map_button_html = f"""
        <div style="text-align:center; margin-bottom: 15px;">
            <a href="{map_url}" target="_blank" role="button" aria-label="{ui['map']}" class="map-btn">
                🗺️ {ui['map']}
            </a>
        </div>
        """

    html_template = f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{store_name}</title>
<style>
body{{font-family:sans-serif;background:#f4f4f4;margin:0;padding:20px;line-height:1.6;}}
.c{{max-width:600px;margin:0 auto;background:#fff;padding:20px;border-radius:15px;box-shadow:0 2px 10px rgba(0,0,0,0.1);}}
h1{{text-align:center;font-size:1.5em;color:#333;margin-bottom:10px;}}
h2{{font-size:1.2em;color:#555;margin-top:20px;margin-bottom:10px;border-bottom:2px solid #eee;padding-bottom:5px;}}
.box{{background:#fff5f5;border:2px solid #ff4b4b;border-radius:10px;padding:15px;text-align:center;margin-bottom:20px;}}
.ti{{font-size:1.3em;font-weight:bold;color:#b71c1c;}}
.ctrl{{display:flex;gap:15px;margin:20px 0;justify-content:center;}}
button{{
    flex:1; padding:15px 0; font-size:1.8em; font-weight:bold; color:#fff;
    background:#ff4b4b; border:none; border-radius:8px; cursor:pointer;
    min-height:60px; display:flex; justify-content:center; align-items:center;
    transition:background 0.2s;
}}
button:hover{{background:#e04141;}}
button:focus, .map-btn:focus, select:focus, .itm:focus{{outline:3px solid #333; outline-offset: 2px;}}
.map-btn{{display:inline-block; padding:12px 20px; background-color:#4285F4; color:white; text-decoration:none; border-radius:8px; font-weight:bold; box-shadow:0 2px 5px rgba(0,0,0,0.2);}}
.lst{{border-top:1px solid #eee;padding-top:10px;}}
.itm{{padding:15px;border-bottom:1px solid #eee;cursor:pointer; font-size:1.1em;}}
.itm:hover{{background:#f9f9f9;}}
.itm.active{{background:#ffecec;color:#b71c1c;font-weight:bold;border-left:5px solid #ff4b4b;}}
</style></head>
<body>
<main class="c" role="main">
    <h1>🎧 {store_name}</h1>
    {map_button_html}
    <section aria-label="Status">
        <div class="box"><div class="ti" id="ti" aria-live="polite">{ui['loading']}</div></div>
    </section>
    <audio id="au" style="width:100%" aria-label="Audio Player"></audio>
    <section class="ctrl" aria-label="Controls">
        <button onclick="prev()"
