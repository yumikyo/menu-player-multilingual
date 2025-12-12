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
st.set_page_config(page_title="Multilingual Menu Generator", layout="wide")

# CSSでボタンのスタイル調整
st.markdown("""
<style>
    div[data-testid="column"] { margin-bottom: 10px; }
</style>
""", unsafe_allow_html=True)

# --- 辞書ファイルの管理 ---
DICT_FILE = "my_dictionary.json"

def load_dictionary():
    if os.path.exists(DICT_FILE):
        try:
            with open(DICT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}

def save_dictionary(new_dict):
    with open(DICT_FILE, "w", encoding="utf-8") as f:
        json.dump(new_dict, f, ensure_ascii=False, indent=2)

# --- 定数・辞書設定 ---
LANG_SETTINGS = {
    "Japanese": {
        "code": "ja",
        "voice_gender": ["女性 (七海)", "男性 (慶太)"],
        "voice_ids": ["ja-JP-NanamiNeural", "ja-JP-KeitaNeural"],
        "rate_value": "+10%",
        "ui": {
            "title": "カテゴリー", "text": "説明", "loading": "読み込み中...", "speed": "速度", 
            "map_btn": "🗺️ 地図・アクセス (Google Map)", "intro": "こんにちは。", "toc": "目次です。",
            "outro": "それではどうぞ。", "file_code": "ja", "currency": "円"
        }
    },
    "English (UK)": {
        "code": "en",
        "voice_gender": ["Female (Sonia - UK)", "Male (Ryan - UK)"],
        "voice_ids": ["en-GB-SoniaNeural", "en-GB-RyanNeural"],
        "rate_value": "+0%",
        "ui": {
            "title": "Category", "text": "Description", "loading": "Loading...", "speed": "Speed",
            "map_btn": "🗺️ Open Map (Google Map)", "intro": "Hello.", "toc": "Here is the table of contents.",
            "outro": "Please enjoy.", "file_code": "en", "currency": "Yen"
        }
    },
    "Chinese": {
        "code": "zh",
        "voice_gender": ["女性 (晓晓)", "男性 (云希)"],
        "voice_ids": ["zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural"],
        "rate_value": "+0%",
        "ui": {
            "title": "类别", "text": "描述", "loading": "加载中...", "speed": "速度",
            "map_btn": "🗺️ 打开地图 (Google Map)", "intro": "你好。", "toc": "这是目录。",
            "outro": "请慢用。", "file_code": "zh", "currency": "日元"
        }
    },
    "Korean": {
        "code": "ko",
        "voice_gender": ["여성 (선희)", "남성 (인준)"],
        "voice_ids": ["ko-KR-SunHiNeural", "ko-KR-InJoonNeural"],
        "rate_value": "+0%",
        "ui": {
            "title": "카테고리", "text": "설명", "loading": "로딩 중...", "speed": "속도",
            "map_btn": "🗺️ 지도 보기 (Google Map)", "intro": "안녕하세요。", "toc": "목차입니다。",
            "outro": "천천히 골라주세요。", "file_code": "ko", "currency": "엔"
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
    if voice_code.startswith("ja"):
        try:
            def gtts_task():
                tts = gTTS(text=text, lang='ja')
                tts.save(filename)
            await asyncio.to_thread(gtts_task)
            return True
        except:
            return False
    return False

async def process_all_tracks_fast(menu_data, output_dir, voice_code, rate_value, progress_bar, lang_key):
    tasks = []
    track_info_list = []
    
    for i, track in enumerate(menu_data):
        safe_title = sanitize_filename(track['title'])
        filename = f"{i:02}_{safe_title}.mp3"
        save_path = os.path.join(output_dir, filename)
        speech_text = track['text']
        
        if i > 0:
            if lang_key == "Japanese":
                speech_text = f"{i}、{track['title']}。\n{track['text']}"
            elif lang_key == "English (UK)":
                speech_text = f"Chapter {i}, {track['title']}.\n{track['text']}"
            else:
                speech_text = f"{i}, {track['title']}.\n{track['text']}"

        tasks.append(generate_single_track_fast(speech_text, save_path, voice_code, rate_value))
        track_info_list.append({"title": track['title'], "path": save_path})
    
    total = len(tasks)
    completed = 0
    for task in asyncio.as_completed(tasks):
        await task
        completed += 1
        progress_bar.progress(completed / total)
    return track_info_list

# HTMLテンプレート (f文字列を使わない)
HTML_TEMPLATE_RAW = """<!DOCTYPE html>
<html lang="__LANG_CODE__"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>__STORE_NAME__ __UI_TITLE__</title>
<style>
body{font-family:sans-serif;background:#f4f4f4;margin:0;padding:20px;line-height:1.6;}
.c{max-width:600px;margin:0 auto;background:#fff;padding:20px;border-radius:15px;box-shadow:0 2px 10px rgba(0,0,0,0.1);}
h1{text-align:center;font-size:1.5em;color:#333;margin-bottom:10px;}
h2{font-size:1.2em;color:#555;margin-top:20px;margin-bottom:10px;border-bottom:2px solid #eee;padding-bottom:5px;}
.box{background:#fff5f5;border:2px solid #ff4b4b;border-radius:10px;padding:15px;text-align:center;margin-bottom:20px;}
.ti{font-size:1.3em;font-weight:bold;color:#b71c1c;}
.ctrl{display:flex;gap:15px;margin:20px 0;justify-content:center;}
button{
    flex:1; padding:15px 0; font-size:1.8em; font-weight:bold; color:#fff; background:#ff4b4b; border:none; border-radius:8px; cursor:pointer; min-height:60px;
    display:flex; justify-content:center; align-items:center; transition:background 0.2s;
}
button:hover{background:#e04141;}
button:focus, .map-btn:focus, select:focus, .itm:focus{outline:3px solid #333; outline-offset: 2px;}
.map-btn{display:inline-block; padding:12px 20px; background-color:#4285F4; color:white; text-decoration:none; border-radius:8px; font-weight:bold; box-shadow:0 2px 5px rgba(0,0,0,0.2);}
.lst{border-top:1px solid #eee;padding-top:10px;}
.itm{padding:15px;border-bottom:1px solid #eee;cursor:pointer; font-size:1.1em;}
.itm:hover{background:#f9f9f9;}
.itm.active{background:#ffecec;color:#b71c1c;font-weight:bold;border-left:5px solid #ff4b4b;}
</style></head>
<body>
<main class="c" role="main">
    <h1>🎧 __STORE_NAME__</h1>
    __MAP_BUTTON__
    <section aria-label="__UI_LOADING__">
        <div class="box"><div class="ti" id="ti" aria-live="polite">__UI_LOADING__</div></div>
    </section>
    <audio id="au" style="width:100%" aria-label="__UI_TITLE__ __UI_TEXT__ Player"></audio>
    <section class="ctrl" aria-label="Controls">
        <button onclick="prev()" aria-label="Previous">⏮</button>
        <button onclick="toggle()" id="pb" aria-label="Play">▶</button>
        <button onclick="next()" aria-label="Next">⏭</button>
    </section>
    <div style="text-align:center;margin-bottom:20px;">
        <label for="sp" style="font-weight:bold; margin-right:5px;">__UI_SPEED__:</label>
        <select id="sp" onchange="csp()" style="font-size:1rem; padding:5px;">
            <option value="0.8">0.8</option>
            <option value="1.0" selected>1.0</option>
            <option value="1.2">1.2</option>
            <option value="1.5">1.5</option>
        </select>
    </div>
    <h2>📜 __UI_TOC__</h2>
    <div id="ls" class="lst" role="list" aria-label="List"></div>
</main>
<script>
const pl = __PLAYLIST_JSON__;
let idx = 0;
const au = document.getElementById('au');
const ti = document.getElementById('ti');
const pb = document.getElementById('pb');
const langKey = "__LANG_KEY__";

function init(){ ren(); ld(0); csp(); }

function ld(i){
    idx = i;
    au.src = pl[idx].src;
    ti.innerText = pl[idx].title;
    ren();
    csp();
}

function toggle(){
    if(au.paused){
        au.play();
        pb.innerText = "⏸";
    } else {
        au.pause();
        pb.innerText = "▶";
    }
}

function next(){
    if(idx < pl.length - 1){
        ld(idx + 1);
        au.play();
        pb.innerText = "⏸";
    }
}

function prev(){
    if(idx > 0){
        ld(idx - 1);
        au.play();
        pb.innerText = "⏸";
    }
}

function csp(){
    au.playbackRate = parseFloat(document.getElementById('sp').value);
}

au.onended = function(){
    if(idx < pl.length - 1){
        next();
    } else {
        pb.innerText = "▶";
    }
};

function getLabel(t, i){
    if (i === 0) return t.title;
    if (langKey === 'Japanese') return i + "、" + t.title;
    if (langKey === 'English (UK)') return "Chapter " + i + ". " + t.title;
    return i + ". " + t.title;
}

function ren(){
    const d = document.getElementById('ls');
    d.innerHTML = "";
    pl.forEach((t, i) => {
        const m = document.createElement('div');
        m.className = "itm " + (i === idx ? "active" : "");
        m.setAttribute("role", "listitem");
        m.setAttribute("tabindex", "0");
        let label = getLabel(t, i);
        m.innerText = label;
        m.onclick = () => { ld(i); au.play(); pb.innerText = "⏸"; };
        m.onkeydown = (e) => { if(e.key === 'Enter' || e.key === ' '){ e.preventDefault(); m.click(); } };
        d.appendChild(m);
    });
}
init();
</script></body></html>"""

# HTMLプレイヤー生成 (安全な置換方式)
def create_standalone_html_player(store_name, menu_data, map_url="", lang_key="Japanese"):
    ui = LANG_SETTINGS[lang_key]["ui"]
    
    playlist_js = []
    for track in menu_data:
        file_path = track['path']
        if os.path.exists(file_path):
            with open(file_path, "rb") as f:
                b64_data = base64.b64encode(f.read()).decode()
                playlist_js.append({"title": track['title'], "src": f"data:audio/mp3;base64,{b64_data}"})
    playlist_json_str = json.dumps(playlist_js, ensure_ascii=False)
    
    map_button_html = ""
    if map_url:
        map_button_html = f"""
        <div style="text-align:center; margin-bottom: 15px;">
            <a href="{map_url}" target="_blank" role="button" aria-label="{ui['map_btn'].replace('🗺️ ', '')}" class="map-btn">
                {ui['map_btn']}
            </a>
        </div>
        """
    
    # 文字列置換で埋め込み（f文字列を使わないので安全）
    html = HTML_TEMPLATE_RAW
    html = html.replace("__LANG_CODE__", LANG_SETTINGS[lang_key]['code'])
    html = html.replace("__STORE_NAME__", store_name)
    html = html.replace("__UI_TITLE__", ui['title'])
    html = html.replace("__UI_TEXT__", ui['text'])
    html = html.replace("__UI_LOADING__", ui['loading'])
    html = html.replace("__UI_SPEED__", ui['speed'])
    html = html.replace("__UI_TOC__", ui['toc'])
    html = html.replace("__MAP_BUTTON__", map_button_html)
    html = html.replace("__PLAYLIST_JSON__", playlist_json_str)
    html = html.replace("__LANG_KEY__", lang_key)
    
    return html

# プレビュー用プレイヤー (シンプル版)
def render_preview_player(tracks, lang_key):
    ui = LANG_SETTINGS[lang_key]["ui"]
    playlist_data = []
    for track in tracks:
        if os.path.exists(track['path']):
            with open(track['path'], "rb") as f:
                b64_data = base64.b64encode(f.read()).decode()
                playlist_data.append({"title": track['title'],"src": f"data:audio/mp3;base64,{b64}"})
    playlist_json = json.dumps(playlist_data)
    
    # プレビュー用HTMLも同様にRaw文字列で定義
    preview_html = """
    <!DOCTYPE html><html><head><style>
    body{margin:0;padding:0;font-family:sans-serif;}
    .p-box{border:2px solid #e0e0e0;border-radius:12px;padding:15px;background:#fcfcfc;text-align:center;}
    .t-ti{font-size:18px;font-weight:bold;color:#333;margin-bottom:10px;padding:10px;background:#fff;border-radius:8px;border-left:5px solid #ff4b4b;}
    .ctrls{display:flex; gap:10px; margin:15px 0;}
    button { flex: 1; background-color: #ff4b4b; color: white; border: none; border-radius: 8px; font-size: 24px; padding: 10px 0; cursor: pointer; }
    .lst{text-align:left;max-height:150px;overflow-y:auto;border-top:1px solid #eee;margin-top:10px;padding-top:5px;}
    .it{padding:8px;border-bottom:1px solid #eee;cursor:pointer;font-size:14px;}
    .it.active{color:#b71c1c;font-weight:bold;background:#ffecec;}
    </style></head><body>
    <div class="p-box">
        <div id="ti" class="t-ti">...</div>
        <audio id="au" controls style="width:100%;height:30px;"></audio>
        <div class="ctrls">
            <button onclick="pv()">⏮</button>
            <button onclick="tg()" id="pb">▶</button>
            <button onclick="nx()">⏭</button>
        </div>
        <div id="ls" class="lst"></div>
    </div>
    <script>
    const pl = __PLAYLIST__;
    let idx = 0;
    const au = document.getElementById('au');
    const ti = document.getElementById('ti');
    const pb = document.getElementById('pb');
    const ls = document.getElementById('ls');
    
    function init(){ ren(); ld(0); }
    function ld(i){ idx = i; au.src = pl[idx].src; ti.innerText = pl[idx].title; ren(); }
    function tg(){ if(au.paused){ au.play(); pb.innerText="⏸"; } else { au.pause(); pb.innerText="▶"; } }
    function nx(){ if(idx < pl.length - 1){ ld(idx+1); au.play(); pb.innerText="⏸"; } }
    function pv(){ if(idx > 0){ ld(idx-1); au.play(); pb.innerText="⏸"; } }
    au.onended = function(){ if(idx < pl.length - 1) nx(); else pb.innerText="▶"; };
    
    function ren(){
        ls.innerHTML = "";
        pl.forEach((t, i) => {
            const d = document.createElement('div');
            d.className = "it " + (i === idx ? "active" : "");
            d.innerText = (i === 0 ? "" : i + ". ") + t.title;
            d.onclick = () => { ld(i); au.play(); pb.innerText="⏸"; };
            ls.appendChild(d);
        });
    }
    init();
    </script></body></html>
    """
    
    preview_html = preview_html.replace("__PLAYLIST__", playlist_json)
    components.html(preview_html, height=450)

# --- UI ---
user_dict = load_dictionary()

with st.sidebar:
    st.header("🔧 設定 / Settings")
    if "GEMINI_API_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_API_KEY"]
        st.success("🔑 APIキー認証済み")
    else:
        api_key = st.text_input("Gemini APIキー", type="password")
    
    valid_models = []
    target_model_name = None
    if api_key:
        try:
            genai.configure(api_key=api_key)
            all_models = list(genai.list_models())
            valid_models = [m.name for m in all_models if 'generateContent' in m.supported_generation_methods]
            default_idx = next((i for i, n in enumerate(valid_models) if "flash" in n), 0)
            target_model_name = st.selectbox("使用するAIモデル", valid_models, index=default_idx)
        except: pass
    
    st.divider()

    st.subheader("🌐 言語 / Language")
    selected_lang = st.selectbox("作成する言語を選んでください", list(LANG_SETTINGS.keys()), index=0)
    current_lang_config = LANG_SETTINGS[selected_lang]
    
    st.subheader("🗣️ 音声設定")
    voice_label = st.selectbox("声の種類", current_lang_config["voice_gender"])
    voice_idx = current_lang_config["voice_gender"].index(voice_label)
    voice_code = current_lang_config["voice_ids"][voice_idx]
    
    rate_value = current_lang_config["rate_value"]

    if selected_lang == "Japanese":
        st.divider()
        st.subheader("📖 辞書登録")
        st.caption("よく間違える読み方を登録すると、AIが学習します。")
        with st.form("dict_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            new_word = c1.text_input("単語", placeholder="辛口")
            new_read = c2.text_input("読み", placeholder="からくち")
            if st.form_submit_button("➕ 追加") and new_word and new_read:
                user_dict[new_word] = new_read
                save_dictionary(user_dict)
                st.success("登録しました")
                st.rerun()

st.title("🎧 Multilingual Menu Player Generator")
st.caption(f"アクセシビリティに配慮した音声メニューを{selected_lang}で作成します。")

if 'retake_index' not in st.session_state: st.session_state.retake_index = None
if 'captured_images' not in st.session_state: st.session_state.captured_images = []
if 'generated_result' not in st.session_state: st.session_state.generated_result = None
if 'show_camera' not in st.session_state: st.session_state.show_camera = False

st.markdown("### 1. お店情報の入力")
c1, c2 = st.columns(2)
with c1: store_name = st.text_input("🏠 店舗名（必須）", placeholder="例：カフェタナカ")
with c2: menu_title = st.text_input("📖 今回のメニュー名 （任意）", placeholder="例：ランチ")
map_url = st.text_input("📍 GoogleマップのURL（任意）", placeholder="例：https://maps.app.goo.gl/...")

st.markdown("---")
st.markdown("### 2. メニューの登録")
input_method = st.radio("方法", ("📂 アルバムから", "📷 その場で撮影", "🌐 URL入力"), horizontal=True)

final_image_list = []
target_url = None

if input_method == "📂 アルバムから":
    uploaded_files = st.file_uploader("写真を選択", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)
    if uploaded_files: final_image_list.extend(uploaded_files)

elif input_method == "📷 その場で撮影":
    # 再撮影ロジック
    if st.session_state.retake_index is not None:
        target_idx = st.session_state.retake_index
        st.warning(f"No.{target_idx + 1} の画像を再撮影中...")
        # 再撮影は頻度が低いのでキーを変えても許容（確実に更新するため）
        retake_key = f"retake_{target_idx}_{int(time.time())}"
        cam = st.camera_input("再撮影", key=retake_key)
        
        rc1, rc2 = st.columns(2)
        with rc1:
            if cam and st.button("✅ 決定", key="confirm_retake", use_container_width=True):
                st.session_state.captured_images[target_idx] = cam
                st.session_state.retake_index = None
                st.rerun()
        with rc2:
            if st.button("❌ キャンセル", key="cancel_retake", use_container_width=True):
                st.session_state.retake_index = None
                st.rerun()

    # 通常撮影ロジック
    elif not st.session_state.show_camera:
        if st.button("📷 カメラ起動", type="primary"):
            st.session_state.show_camera = True
            st.rerun()
    else:
        # ★カメラIDを固定して再アクセスを防ぐ★
        cam = st.camera_input("撮影", key="menu_camera_fixed")
        
        # すでにリストにある最後の画像と同じかチェック（連打防止）
        is_new = True
        if cam is not None and st.session_state.captured_images:
            if st.session_state.captured_images[-1].getvalue() == cam.getvalue():
                is_new = False
        
        if cam is not None:
            c1, c2 = st.columns(2)
            with c1:
                if st.button("⬇️ 追加して次を撮る", type="primary", use_container_width=True):
                    if is_new:
                        st.session_state.captured_images.append(cam)
                        st.success("追加しました！次の写真を撮影してください。")
                        time.sleep(1) # メッセージを見せる
                        st.rerun()
                    else:
                        st.warning("同じ写真です。新しい写真を撮影してください。")
            with c2:
                if st.button("✅ 追加して終了", type="primary", use_container_width=True):
                    if is_new:
                        st.session_state.captured_images.append(cam)
                    st.session_state.show_camera = False
                    st.rerun()
        else:
             if st.button("❌ 撮影を中止", use_container_width=True):
                st.session_state.show_camera = False
                st.rerun()

    # 撮影済み画像リストへの追加（カメラモード中はここには表示せず、下の確認エリアで表示）
    if not st.session_state.show_camera and st.session_state.captured_images:
         final_image_list.extend(st.session_state.captured_images)
    
    # 全削除ボタン（カメラ外）
    if st.session_state.captured_images and not st.session_state.show_camera and st.session_state.retake_index is None:
        if st.button("🗑️ 全て削除"):
            st.session_state.captured_images = []
            st.rerun()

elif input_method == "🌐 URL入力":
    target_url = st.text_input("URL", placeholder="https://...")

# 画像一覧表示（カメラ起動中は、撮影済みのものを下に表示して確認できるようにする）
current_images = final_image_list if input_method != "📷 その場で撮影" else st.session_state.captured_images

if current_images and st.session_state.retake_index is None:
    st.markdown("###### ▼ 画像確認")
    cols = st.columns(3)
    for i, img in enumerate(current_images):
        with cols[i % 3]:
            st.image(img, caption=f"No.{i+1}", use_container_width=True)
            # カメラモードかつ一覧表示中なら削除・再撮影ボタンを出す
            if input_method == "📷 その場で撮影":
                c_retake, c_del = st.columns(2)
                with c_retake:
                    if st.button("🔄", key=f"retake_btn_{i}"):
                        st.session_state.retake_index = i
                        st.session_state.show_camera = False # 再撮影モードへ
                        st.rerun()
                with c_del:
                    if st.button("🗑️", key=f"del_btn_{i}"):
                        st.session_state.captured_images.pop(i)
                        st.rerun()

st.markdown("---")
st.markdown("### 3. 音声メニューの作成")
disable_create = (st.session_state.retake_index is not None) or (st.session_state.show_camera)
if st.button("🎙️ 作成開始", type="primary", use_container_width=True, disabled=disable_create):
    if not (api_key and target_model_name and store_name):
        st.error("設定や店舗名を確認してください"); st.stop()
    if not (current_images or target_url):
        st.warning("画像かURLを入力してください"); st.stop()

    output_dir = os.path.abspath("menu_audio_album")
    if os.path.exists(output_dir): shutil.rmtree(output_dir)
    os.makedirs(output_dir)

    with st.spinner('解析中...'):
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(target_model_name)
            parts = []
            
            lang_instruction = ""
            currency = current_lang_config["ui"]["currency"]
            dict_prompt = ""
            
            if selected_lang == "Japanese":
                lang_instruction = f"出力は全て日本語で行ってください。価格の数字には必ず「{currency}」をつけて読み上げる。"
                user_dict_str = json.dumps(user_dict, ensure_ascii=False)
                dict_prompt = f"★重要：以下の固有名詞・読み方辞書を必ず守ってください。\n{user_dict_str}\n"
            elif selected_lang == "English (UK)":
                lang_instruction = f"Translate all output into British English (UK). Group prices with {currency}."
            elif selected_lang == "Chinese":
                lang_instruction = f"Translate all output into Simplified Chinese. Group prices with {currency}."
            elif selected_lang == "Korean":
                lang_instruction = f"Translate all output into Korean. Group prices with {currency}."

            prompt = f"""
            You are a professional menu accessibility expert.
            Analyze the menu images/text and organize them into 5-8 major categories.
            1. {lang_instruction}
            2. Group items intelligently.
            3. The 'text' field should be a reading script suitable for customers.
            4. Allergens, spice level, notes must be included.
            {dict_prompt}
            Output MUST be valid JSON only:
            [
              {{"title": "Category Name", "text": "Reading script..."}},
              {{"title": "Category Name", "text": "Reading script..."}}
            ]
            """
            
            # 画像リストは current_images を使う
            if current_images:
                parts.append(prompt)
                for f in current_images:
                    f.seek(0)
                    parts.append({"mime_type": f.type if hasattr(f, 'type') else 'image/jpeg', "data": f.getvalue()})
            elif target_url:
                web_text = fetch_text_from_url(target_url)
                if not web_text: st.error("URLエラー"); st.stop()
                parts.append(prompt + f"\n\n{web_text[:30000]}")

            resp = None
            for _ in range(3):
                try: resp = model.generate_content(parts); break
                except exceptions.ResourceExhausted: time.sleep(5)
                except: pass

            if not resp: st.error("失敗しました"); st.stop()

            text_resp = resp.text
            start = text_resp.find('[')
            end = text_resp.rfind(']') + 1
            if start == -1: st.error("解析エラー"); st.stop()
            menu_data = json.loads(text_resp[start:end])

            ui = current_lang_config["ui"]
            intro_t = f"{ui['intro']} {store_name}."
            if menu_title: intro_t += f" {menu_title}."
            
            for i, tr in enumerate(menu_data):
                if selected_lang == "Japanese": intro_t += f" {i+1}、{tr['title']}。"
                else: intro_t += f" {i+1}, {tr['title']}."
            intro_t += f" {ui['outro']}"
            menu_data.insert(0, {"title": ui['toc'], "text": intro_t})

            progress_bar = st.progress(0)
            st.info(f"音声を生成しています... ({selected_lang})")
            generated_tracks = asyncio.run(process_all_tracks_fast(menu_data, output_dir, voice_code, rate_value, progress_bar, selected_lang))

            html_str = create_standalone_html_player(store_name, generated_tracks, map_url, selected_lang)
            
            d_str = datetime.now().strftime('%Y%m%d')
            s_name = sanitize_filename(store_name)
            file_code = current_lang_config["ui"]["file_code"]
            zip_name = f"{s_name}_{file_code}_{d_str}.zip"
            zip_path = os.path.abspath(zip_name)
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
                for root, dirs, files in os.walk(output_dir):
                    for file in files: z.write(os.path.join(root, file), file)

            with open(zip_path, "rb") as f:
                zip_data = f.read()

            st.session_state.generated_result = {
                "zip_data": zip_data,
                "zip_name": zip_name,
                "html_content": html_str, 
                "html_name": f"{s_name}_{file_code}_player.html",
                "tracks": generated_tracks,
                "lang_key": selected_lang
            }
            st.balloons()
        except Exception as e: st.error(f"エラー: {e}")

if st.session_state.generated_result:
    res = st.session_state.generated_result
    st.divider()
    st.subheader(f"▶️ プレビュー ({res['lang_key']})")
    render_preview_player(res["tracks"], res["lang_key"])
    st.divider()
    st.subheader("📥 保存")
    c1, c2 = st.columns(2)
    with c1: st.download_button(f"🌐 Webプレイヤー ({res['html_name']})", res['html_content'], res['html_name'], "text/html", type="primary")
    with c2: st.download_button(f"📦 ZIPファイル ({res['zip_name']})", data=res["zip_data"], file_name=res['zip_name'], mime="application/zip")
