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

# CSSでボタンのスタイル調整（間隔確保）
st.markdown("""
<style>
    div[data-testid="column"] {
        margin-bottom: 10px;
    }
</style>
""", unsafe_allow_html=True)

# --- 辞書ファイルの管理 ---
DICT_FILE = "my_dictionary.json"

def load_dictionary():
    if os.path.exists(DICT_FILE):
        with open(DICT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_dictionary(new_dict):
    with open(DICT_FILE, "w", encoding="utf-8") as f:
        json.dump(new_dict, f, ensure_ascii=False, indent=2)

# --- 言語設定・定数 ---
LANG_CONFIG = {
    "日本語": {
        "voice": "ja-JP-NanamiNeural",
        "prompt_target": "日本語",
        "currency": "円",
        "intro_template": "こんにちは、{store}です。ただいまより{title}をご紹介します。",
        "intro_index_msg": "このメニューは、全部で{count}つのカテゴリーに分かれています。まずは目次です。",
        "intro_closing": "それではどうぞ。",
        "intro_title": "はじめに・目次",
        "ui": {"loading": "読み込み中...", "chapter": "チャプター一覧", "speed": "読み上げ速度", "map": "地図・アクセス", "play": "再生", "pause": "一時停止", "prev": "前へ", "next": "次へ", "slow": "ゆっくり", "normal": "標準", "fast": "速く"}
    },
    "English": {  # 表示はEnglish、中身はUK
        "voice": "en-GB-SoniaNeural", 
        "prompt_target": "English (UK Style)",
        "currency": "yen",
        "intro_template": "Hello, this is {store}. We would like to introduce our {title} menu.",
        "intro_index_msg": "This menu is divided into {count} categories. First, here is the index.",
        "intro_closing": "Please enjoy.",
        "intro_title": "Introduction & Index",
        "ui": {"loading": "Loading...", "chapter": "Chapters", "speed": "Speed", "map": "Map", "play": "Play", "pause": "Pause", "prev": "Prev", "next": "Next", "slow": "Slow", "normal": "Normal", "fast": "Fast"}
    },
    "中文 (简体)": {
        "voice": "zh-CN-XiaoxiaoNeural",
        "prompt_target": "中国語 (Simplified Chinese)",
        "currency": "日元",
        "intro_template": "你好，这里是{store}。现在为您介绍{title}。",
        "intro_index_msg": "菜单共分为{count}个类别。首先是目录。",
        "intro_closing": "请慢慢听。",
        "intro_title": "简介与目录",
        "ui": {"loading": "加载中...", "chapter": "章节列表", "speed": "语速", "map": "地图", "play": "播放", "pause": "暂停", "prev": "上一个", "next": "下一个", "slow": "慢速", "normal": "标准", "fast": "快速"}
    },
    "한국어": {
        "voice": "ko-KR-SunHiNeural",
        "prompt_target": "韓国語 (Korean)",
        "currency": "엔",
        "intro_template": "안녕하세요, {store}입니다. 지금부터 {title}를 소개해 드리겠습니다.",
        "intro_index_msg": "메뉴는 총 {count}개의 카테고리로 나누어져 있습니다. 먼저 목차입니다.",
        "intro_closing": "그럼 들어주세요.",
        "intro_title": "소개 및 목차",
        "ui": {"loading": "로딩 중...", "chapter": "챕터 목록", "speed": "재생 속도", "map": "지도", "play": "재생", "pause": "일시 정지", "prev": "이전", "next": "다음", "slow": "느리게", "normal": "보통", "fast": "빠르게"}
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
    try:
        lang_code = voice_code[:2].lower()
        if "GB" in voice_code: lang_code = "en"
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
        
        # 番号付けロジック: i=0(Intro)は番号なし, i=1以降は "1. " から開始
        if i > 0: 
             speech_text = f"{i}. {track['title']}.\n{track['text']}"
             
        tasks.append(generate_single_track_fast(speech_text, save_path, voice_code, rate_value))
        track_info_list.append({"title": track['title'], "path": save_path})
    
    total = len(tasks)
    completed = 0
    for task in asyncio.as_completed(tasks):
        await task
        completed += 1
        progress_bar.progress(completed / total)
    return track_info_list

# HTMLプレイヤー生成（多言語対応・安全な文字列置換版）
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

    # HTMLテンプレート（f-stringを使わない方式に変更）
    html_template = """<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>__STORE_NAME__</title>
<style>
body{font-family:sans-serif;background:#f4f4f4;margin:0;padding:20px;line-height:1.6;}
.c{max-width:600px;margin:0 auto;background:#fff;padding:20px;border-radius:15px;box-shadow:0 2px 10px rgba(0,0,0,0.1);}
h1{text-align:center;font-size:1.5em;color:#333;margin-bottom:10px;}
h2{font-size:1.2em;color:#555;margin-top:20px;margin-bottom:10px;border-bottom:2px solid #eee;padding-bottom:5px;}
.box{background:#fff5f5;border:2px solid #ff4b4b;border-radius:10px;padding:15px;text-align:center;margin-bottom:20px;}
.ti{font-size:1.3em;font-weight:bold;color:#b71c1c;}
.ctrl{display:flex;gap:15px;margin:20px 0;justify-content:center;}
button{
    flex:1; padding:15px 0; font-size:1.8em; font-weight:bold; color:#fff;
    background:#ff4b4b; border:none; border-radius:8px; cursor:pointer;
    min-height:60px; display:flex; justify-content:center; align-items:center;
    transition:background 0.2s;
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
    <section aria-label="Status">
        <div class="box"><div class="ti" id="ti" aria-live="polite">__UI_LOADING__</div></div>
    </section>
    <audio id="au" style="width:100%" aria-label="Audio Player"></audio>
    <section class="ctrl" aria-label="Controls">
        <button onclick="prev()" aria-label="__UI_PREV__">⏮</button>
        <button onclick="toggle()" id="pb" aria-label="__UI_PLAY__">▶</button>
        <button onclick="next()" aria-label="__UI_NEXT__">⏭</button>
    </section>
    <div style="text-align:center;margin-bottom:20px;">
        <label for="sp" style="font-weight:bold; margin-right:5px;">__UI_SPEED__:</label>
        <select id="sp" onchange="csp()" style="font-size:1rem; padding:5px;">
            <option value="0.8">0.8 (__UI_SLOW__)</option>
            <option value="1.0" selected>1.0 (__UI_NORMAL__)</option>
            <option value="1.2">1.2 (__UI_FAST__)</option>
            <option value="1.5">1.5</option>
        </select>
    </div>
    <h2>📜 __UI_CHAPTER__</h2>
    <div id="ls" class="lst" role="list"></div>
</main>
<script>
const pl=__PLAYLIST_JSON__;let idx=0;
const au=document.getElementById('au');
const ti=document.getElementById('ti');
const pb=document.getElementById('pb');
function init(){ren();ld(0);csp();}
function ld(i){
    idx=i; au.src=pl[idx].src; ti.innerText=pl[idx].title; ren(); csp();
}
function toggle(){
    if(au.paused){ au.play(); pb.innerText="⏸"; pb.setAttribute("aria-label", "__UI_PAUSE__"); }
    else{ au.pause(); pb.innerText="▶"; pb.setAttribute("aria-label", "__UI_PLAY__"); }
}
function next(){
    if(idx<pl.length-1){ ld(idx+1); au.play(); pb.innerText="⏸"; pb.setAttribute("aria-label", "__UI_PAUSE__"); }
}
function prev(){
    if(idx>0){ ld(idx-1); au.play(); pb.innerText="⏸"; pb.setAttribute("aria-label", "__UI_PAUSE__"); }
}
function csp(){au.playbackRate=parseFloat(document.getElementById('sp').value);}
au.onended=function(){
    if(idx<pl.length-1){ next(); }
    else { pb.innerText="▶"; pb.setAttribute("aria-label", "__UI_PLAY__");}
};
function ren(){
    const d=document.getElementById('ls');
    d.innerHTML="";
    pl.forEach((t,i)=>{
        const m=document.createElement('div');
        m.className="itm "+(i===idx?"active":"");
        m.setAttribute("role", "listitem");
        m.setAttribute("tabindex", "0");
        
        // リスト番号付け
        let label = t.title;
        if(i > 0){ label = i + ". " + t.title; }
        
        m.setAttribute("aria-label", label);
        m.innerText=label;
        m.onclick=()=>{ld(i);au.play();pb.innerText="⏸";pb.setAttribute("aria-label","__UI_PAUSE__");};
        m.onkeydown=(e)=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();d.click();}};
        d.appendChild(m);
    });
}
init();
</script></body></html>"""
    
    # テンプレートの変数を置換
    html = html_template.replace("__STORE_NAME__", store_name)
    html = html.replace("__MAP_BUTTON__", map_button_html)
    html = html.replace("__PLAYLIST_JSON__", playlist_json_str)
    
    # UIの言語変数を置換
    html = html.replace("__UI_LOADING__", ui['loading'])
    html = html.replace("__UI_PREV__", ui['prev'])
    html = html.replace("__UI_PLAY__", ui['play'])
    html = html.replace("__UI_PAUSE__", ui['pause'])
    html = html.replace("__UI_NEXT__", ui['next'])
    html = html.replace("__UI_SPEED__", ui['speed'])
    html = html.replace("__UI_SLOW__", ui['slow'])
    html = html.replace("__UI_NORMAL__", ui['normal'])
    html = html.replace("__UI_FAST__", ui['fast'])
    html = html.replace("__UI_CHAPTER__", ui['chapter'])
    
    return html

# プレビュー用プレイヤー（多言語対応版）
def render_preview_player(tracks, lang_settings):
    playlist_data = []
    for track in tracks:
        if os.path.exists(track['path']):
            with open(track['path'], "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
                playlist_data.append({"title": track['title'],"src": f"data:audio/mp3;base64,{b64}"})
    playlist_json = json.dumps(playlist_data)
    ui = lang_settings["ui"]
    
    html_template = """<!DOCTYPE html><html><head><style>
    body{margin:0;padding:0;font-family:sans-serif;}
    .p-box{border:2px solid #e0e0e0;border-radius:12px;padding:15px;background:#fcfcfc;text-align:center;}
    .t-ti{font-size:18px;font-weight:bold;color:#333;margin-bottom:10px;padding:10px;background:#fff;border-radius:8px;border-left:5px solid #ff4b4b;}
    .ctrls{display:flex; gap:10px; margin:15px 0;}
    button {
        flex: 1; background-color: #ff4b4b; color: white; border: none;
        border-radius: 8px; font-size: 24px; padding: 10px 0; cursor: pointer;
        line-height: 1; min-height: 50px;
    }
    button:hover { background-color: #e04141; }
    button:focus { outline: 3px solid #333; outline-offset: 2px; }
    .lst{text-align:left;max-height:150px;overflow-y:auto;border-top:1px solid #eee;margin-top:10px;padding-top:5px;}
    .it{padding:8px;border-bottom:1px solid #eee;cursor:pointer;font-size:14px;}
    .it:focus{outline:2px solid #333; background:#eee;}
    .it.active{color:#b71c1c;font-weight:bold;background:#ffecec;}
    </style></head><body><div class="p-box"><div id="ti" class="t-ti">...</div><audio id="au" controls style="width:100%;height:30px;"></audio>
    <div class="ctrls">
        <button onclick="pv()" aria-label="__UI_PREV__">⏮</button>
        <button onclick="tg()" id="pb" aria-label="__UI_PLAY__">▶</button>
        <button onclick="nx()" aria-label="__UI_NEXT__">⏭</button>
    </div>
    <div style="font-size:12px;color:#666; margin-top:5px;">
        __UI_SPEED__:<select id="sp" onchange="sp()"><option value="0.8">0.8</option><option value="1.0" selected>1.0</option><option value="1.2">1.2</option><option value="1.5">1.5</option></select>
    </div>
    <div id="ls" class="lst" role="list"></div></div>
    <script>
    const pl=__PLAYLIST__;let x=0;const au=document.getElementById('au');const ti=document.getElementById('ti');const pb=document.getElementById('pb');const ls=document.getElementById('ls');
    function init(){rn();ld(0);sp();}
    function ld(i){x=i;au.src=pl[x].src;ti.innerText=pl[x].title;rn();sp();}
    function tg(){if(au.paused){au.play();pb.innerText="⏸";pb.setAttribute("aria-label","__UI_PAUSE__");}else{au.pause();pb.innerText="▶";pb.setAttribute("aria-label","__UI_PLAY__");}}
    function nx(){if(x<pl.length-1){ld(x+1);au.play();pb.innerText="⏸";pb.setAttribute("aria-label","__UI_PAUSE__");}}
    function pv(){if(x>0){ld(x-1);au.play();pb.innerText="⏸";pb.setAttribute("aria-label","__UI_PAUSE__");}}
    function sp(){au.playbackRate=parseFloat(document.getElementById('sp').value);}
    au.onended=function(){if(x<pl.length-1)nx();else{pb.innerText="▶";pb.setAttribute("aria-label","__UI_PLAY__");}};
    function rn(){ls.innerHTML="";pl.forEach((t,i)=>{
        const d=document.createElement('div');
        d.className="it "+(i===x?"active":"");
        let l=t.title; if(i>0){l=i+". "+t.title;}
        d.innerText=l;
        d.setAttribute("role","listitem");d.setAttribute("tabindex","0");d.onclick=()=>{ld(i);au.play();pb.innerText="⏸";pb.setAttribute("aria-label","__UI_PAUSE__");};d.onkeydown=(e)=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();d.click();}};ls.appendChild(d);});}
    init();</script></body></html>"""
    
    html = html_template.replace("__PLAYLIST__", playlist_json)
    html = html.replace("__UI_PREV__", ui['prev'])
    html = html.replace("__UI_PLAY__", ui['play'])
    html = html.replace("__UI_PAUSE__", ui['pause'])
    html = html.replace("__UI_NEXT__", ui['next'])
    html = html.replace("__UI_SPEED__", ui['speed'])
    components.html(html, height=450)

# --- UI ---
with st.sidebar:
    st.header("🔧 設定 / Settings")
    if "GEMINI_API_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_API_KEY"]
        st.success("🔑 API Key OK")
    else:
        api_key = st.text_input("Gemini APIキー", type="password")
    
    # 言語選択
    st.subheader("🌐 言語選択 / Language")
    selected_lang = st.selectbox("ターゲット言語", list(LANG_CONFIG.keys()))
    lang_conf = LANG_CONFIG[selected_lang]
    st.info(f"出力言語: {lang_conf['prompt_target']}")

    # 辞書機能
    st.divider()
    st.subheader("📖 辞書登録 (Learning)")
    user_dict = load_dictionary()
    
    with st.form("dict_form", clear_on_submit=True):
        c_word, c_read = st.columns(2)
        new_word = c_word.text_input("単語", placeholder="例: 辛口")
        new_read = c_read.text_input("読み", placeholder="例: からくち")
        if st.form_submit_button("➕ 追加"):
            if new_word and new_read:
                user_dict[new_word] = new_read
                save_dictionary(user_dict)
                st.success(f"「{new_word}」を登録しました！")
                st.rerun()

    if user_dict:
        with st.expander(f"登録済み単語 ({len(user_dict)})"):
            for word, read in list(user_dict.items()):
                c1, c2 = st.columns([3, 1])
                c1.text(f"{word} ➡ {read}")
                if c2.button("🗑️", key=f"del_{word}"):
                    del user_dict[word]
                    save_dictionary(user_dict)
                    st.rerun()

    valid_models = []
    target_model_name = None
    if api_key:
        try:
            genai.configure(api_key=api_key)
            all_models = list(genai.list_models())
            valid_models = [m.name for m in all_models if 'generateContent' in m.supported_generation_methods]
            default_idx = next((i for i, n in enumerate(valid_models) if "flash" in n), 0)
            target_model_name = st.selectbox("AIモデル", valid_models, index=default_idx)
        except: pass
    
    st.divider()
    rate_value = "+10%"

st.title("🎧 Menu Player Generator")
st.caption("Multilingual Accessibility Menu Creator (Dictionary Enabled)")

if 'retake_index' not in st.session_state: st.session_state.retake_index = None
if 'captured_images' not in st.session_state: st.session_state.captured_images = []
if 'camera_key' not in st.session_state: st.session_state.camera_key = 0
if 'generated_result' not in st.session_state: st.session_state.generated_result = None
if 'show_camera' not in st.session_state: st.session_state.show_camera = False
if 'menu_data_draft' not in st.session_state: st.session_state.menu_data_draft = None

# Step 1 & 2
st.markdown("### 1. お店情報の入力 / Store Info")
c1, c2 = st.columns(2)
with c1: store_name = st.text_input("🏠 店舗名 / Store Name", placeholder="e.g. Cafe Tanaka")
with c2: menu_title = st.text_input("📖 メニュー名 / Menu Title", placeholder="e.g. Lunch Menu")
map_url = st.text_input("📍 GoogleマップのURL (Option)", placeholder="https://maps.google.com/...")
st.markdown("---")
st.markdown("### 2. メニューの登録 / Input Menu")
input_method = st.radio("方法", ("📂 アルバムから", "📷 その場で撮影", "🌐 URL入力"), horizontal=True)

final_image_list = []
target_url = None

if input_method == "📂 アルバムから":
    uploaded_files = st.file_uploader("Upload Images", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)
    if uploaded_files: final_image_list.extend(uploaded_files)
elif input_method == "📷 その場で撮影":
    if st.session_state.retake_index is not None:
        target_idx = st.session_state.retake_index
        st.warning(f"Retaking No.{target_idx + 1} ...")
        retake_camera_key = f"retake_camera_{target_idx}_{st.session_state.camera_key}"
        camera_file = st.camera_input("写真を撮影する (取り直し)", key=retake_camera_key)
        c1, c2 = st.columns(2, gap="large")
        with c1:
            if camera_file and st.button("✅ これで決定", type="primary", key="retake_confirm", use_container_width=True):
                st.session_state.captured_images[target_idx] = camera_file
                st.session_state.retake_index = None
                st.session_state.show_camera = False 
                st.session_state.camera_key += 1
                st.rerun()
        with c2:
            if st.button("❌ キャンセル", key="retake_cancel", use_container_width=True):
                st.session_state.retake_index = None
                st.session_state.show_camera = False
                st.rerun()
    elif not st.session_state.show_camera:
        if st.button("📷 カメラ起動", type="primary"):
            st.session_state.show_camera = True
            st.rerun()
    else:
        camera_file = st.camera_input("写真を撮影する", key=f"camera_{st.session_state.camera_key}")
        if camera_file:
            c_btn1, c_btn2 = st.columns(2, gap="large")
            with c_btn1:
                if st.button("⬇️ 追加して次を撮る", type="primary", use_container_width=True):
                    st.session_state.captured_images.append(camera_file)
                    st.session_state.camera_key += 1
                    st.rerun()
            with c_btn2:
                if st.button("✅ 追加して終了", type="primary", use_container_width=True):
                    st.session_state.captured_images.append(camera_file)
                    st.session_state.show_camera = False
                    st.session_state.camera_key += 1
                    st.rerun()
        else:
            if st.button("❌ 撮影を中止", use_container_width=True):
                st.session_state.show_camera = False
                st.rerun()
    if st.session_state.captured_images:
        if st.session_state.retake_index is None and st.session_state.show_camera is False:
             if st.button("🗑️ 全て削除"):
                st.session_state.captured_images = []
                st.rerun()
        final_image_list.extend(st.session_state.captured_images)
elif input_method == "🌐 URL入力":
    target_url = st.text_input("URL", placeholder="https://...")

if final_image_list and st.session_state.retake_index is None:
    st.markdown("###### ▼ Image Preview")
    cols_per_row = 3
    for i in range(0, len(final_image_list), cols_per_row):
        cols = st.columns(cols_per_row, gap="medium")
        batch = final_image_list[i:i+cols_per_row]
        for j, img in enumerate(batch):
            global_idx = i + j
            with cols[j]:
                st.image(img, caption=f"No.{global_idx+1}", use_container_width=True)
                if input_method == "📷 その場で撮影" and img in st.session_state.captured_images:
                    c_retake, c_delete = st.columns(2, gap="small")
                    with c_retake:
                        if st.button("🔄 撮り直す", key=f"btn_retake_{global_idx}", use_container_width=True):
                            st.session_state.retake_index = global_idx
                            st.session_state.show_camera = True
                            st.rerun()
                    with c_delete:
                        if st.button("🗑️ 削除", key=f"btn_delete_{global_idx}", use_container_width=True):
                            st.session_state.captured_images.pop(global_idx)
                            st.session_state.retake_index = None
                            st.session_state.show_camera = False
                            st.rerun()

st.markdown("---")
st.markdown("### 3. 音声メニューの作成 / Generate")

if st.button("📝 原稿を作成 (Analysis)", type="primary", use_container_width=True, disabled=disable_create):
    if not (api_key and target_model_name and store_name):
        st.error("設定や店舗名を確認してください / Check Settings"); st.stop()
    if not (final_image_list or target_url):
        st.warning("画像かURLを入力してください / Input Image or URL"); st.stop()

    with st.spinner(f'Analyzing & Translating to {selected_lang}...'):
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(target_model_name)
            parts = []
            
            target_lang_name = lang_conf["prompt_target"]
            currency_unit = lang_conf["currency"]
            user_dict_str = json.dumps(user_dict, ensure_ascii=False)
            
            prompt = f"""
            あなたは視覚障害者のためのメニュー読み上げデータ作成のプロであり、翻訳の専門家です。
            提供されたメニュー画像を解析し、内容を**【{target_lang_name}】**に翻訳・要約して出力してください。
            
            重要ルール:
            1. 出力言語は必ず**【{target_lang_name}】**でおこなうこと。
            2. メニューを5つ〜8つ程度のカテゴリーに分類する。
            3. 商品名と価格をテンポよく読み上げる文章にする。
            4. 価格の数字は日本の通貨のまま、**{currency_unit}** (またはその言語での読み方) をつけて読み上げる。
            5. アレルギーや辛さなどの注意書きも翻訳して補足する。
            
            ★重要：以下の固有名詞・読み方辞書を必ず守ってください。
            {user_dict_str}

            出力フォーマット（JSONのみ）:
            [
              {{"title": "カテゴリー名({target_lang_name})", "text": "読み上げ文({target_lang_name})..."}},
              {{"title": "カテゴリー名({target_lang_name})", "text": "読み上げ文({target_lang_name})..."}}
            ]
            """
            
            if final_image_list:
                parts.append(prompt)
                for f in final_image_list:
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

            intro_t = lang_conf["intro_template"].format(store=store_name, title=menu_title if menu_title else "")
            intro_t += lang_conf["intro_index_msg"].format(count=len(menu_data))
            
            for i, tr in enumerate(menu_data):
                # i=0(1番目) -> "1. タイトル"
                intro_t += f"{i+1}. {tr['title']}. "
            
            intro_t += lang_conf["intro_closing"]

            menu_data.insert(0, {"title": lang_conf['intro_title'], "text": intro_t})
            
            st.session_state.menu_data_draft = menu_data
            st.rerun()

        except Exception as e: st.error(f"Error: {e}")

if st.session_state.menu_data_draft is not None:
    st.info("👇 以下の原稿を確認・編集してください。")
    edited_data = st.data_editor(st.session_state.menu_data_draft, num_rows="dynamic", use_container_width=True)
    
    if st.button("🎙️ 音声を生成 (Generate Audio)", type="primary", use_container_width=True):
        output_dir = os.path.abspath("menu_audio_album")
        if os.path.exists(output_dir): shutil.rmtree(output_dir)
        os.makedirs(output_dir)
        
        progress_bar = st.progress(0)
        st.info(f"Generating Audio in {selected_lang}...")
        
        generated_tracks = asyncio.run(process_all_tracks_fast(edited_data, output_dir, lang_conf["voice"], rate_value, progress_bar))
        html_str = create_standalone_html_player(store_name, edited_data, lang_conf, map_url)
        
        d_str = datetime.now().strftime('%Y%m%d')
        s_name = sanitize_filename(store_name)
        zip_name = f"{s_name}_{sanitize_filename(selected_lang)}_{d_str}.zip"
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
            "html_name": f"{s_name}_{sanitize_filename(selected_lang)}_player.html",
            "tracks": generated_tracks,
            "lang_conf": lang_conf
        }
        st.rerun()

if st.session_state.generated_result:
    res = st.session_state.generated_result
    st.divider()
    st.subheader("▶️ Preview")
    render_preview_player(res["tracks"], res["lang_conf"])
    st.divider()
    st.subheader("📥 Download")
    st.info("Web Player & ZIP File")
    c1, c2 = st.columns(2)
    with c1: st.download_button(f"🌐 Web Player ({res['html_name']})", res['html_content'], res['html_name'], "text/html", type="primary")
    with c2: st.download_button(f"📦 ZIP File ({res['zip_name']})", data=res["zip_data"], file_name=res['zip_name'], mime="application/zip")
