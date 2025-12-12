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

# 言語設定とUIテキスト
LANG_SETTINGS = {
    "Japanese": {
        "code": "ja",
        "voice_gender": ["女性 (七海)", "男性 (慶太)"],
        "voice_ids": ["ja-JP-NanamiNeural", "ja-JP-KeitaNeural"],
        "rate_value": "+10%", # 日本語はやや高速化
        "ui": {
            "title": "カテゴリー", "text": "説明", "loading": "読み込み中...", "speed": "速度", 
            "map_btn": "🗺️ 地図・アクセス (Google Map)", "intro": "こんにちは。", "toc": "目次です。",
            "outro": "それではどうぞ。", "file_code": "ja", "currency": "円"
        }
    },
    "English (UK)": {  # イギリス英語設定
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
            "map_btn": "🗺️ 지도 보기 (Google Map)", "intro": "안녕하세요.", "toc": "목차입니다.",
            "outro": "천천히 골라주세요.", "file_code": "ko", "currency": "엔"
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
    # 最後の手段としてgTTSを試す (日本語のみ)
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
    
    ui = LANG_SETTINGS[lang_key]["ui"]
    
    for i, track in enumerate(menu_data):
        safe_title = sanitize_filename(track['title'])
        filename = f"{i:02}_{safe_title}.mp3" # 00_から開始
        save_path = os.path.join(output_dir, filename)
        speech_text = track['text']
        
        # 目次以外（i=0は目次）のトラックに番号とタイトルを付与
        if i > 0:
            if lang_key == "Japanese":
                speech_text = f"{i}、{track['title']}。\n{track['text']}"
            elif lang_key == "English (UK)":
                speech_text = f"Chapter {i}, {track['title']}.\n{track['text']}"
            else:
                speech_text = f"{i}, {track['title']}.\n{track['text']}" # 中国語、韓国語はシンプルに

        tasks.append(generate_single_track_fast(speech_text, save_path, voice_code, rate_value))
        track_info_list.append({"title": track['title'], "path": save_path})
    
    total = len(tasks)
    completed = 0
    for task in asyncio.as_completed(tasks):
        await task
        completed += 1
        progress_bar.progress(completed / total)
    return track_info_list

# HTMLプレイヤー生成
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
    
    # HTMLテンプレート（アクセシビリティ強化済みのものを使用）
    html_template = f"""<!DOCTYPE html>
<html lang="{LANG_SETTINGS[lang_key]['code']}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>__STORE_NAME__ {ui['title']}</title>
<style>
body{{font-family:sans-serif;background:#f4f4f4;margin:0;padding:20px;line-height:1.6;}}
.c{{max-width:600px;margin:0 auto;background:#fff;padding:20px;border-radius:15px;box-shadow:0 2px 10px rgba(0,0,0,0.1);}}
h1{{text-align:center;font-size:1.5em;color:#333;margin-bottom:10px;}}
h2{{font-size:1.2em;color:#555;margin-top:20px;margin-bottom:10px;border-bottom:2px solid #eee;padding-bottom:5px;}}
.box{{background:#fff5f5;border:2px solid #ff4b4b;border-radius:10px;padding:15px;text-align:center;margin-bottom:20px;}}
.ti{{font-size:1.3em;font-weight:bold;color:#b71c1c;}}
.ctrl{{display:flex;gap:15px;margin:20px 0;justify-content:center;}}
button{{
    flex:1; padding:15px 0; font-size:1.8em; font-weight:bold; color:#fff; background:#ff4b4b; border:none; border-radius:8px; cursor:pointer; min-height:60px;
    display:flex; justify-content:center; align-items:center; transition:background 0.2s;
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
    <h1>🎧 __STORE_NAME__</h1>
    __MAP_BUTTON__
    <section aria-label="{ui['loading']}">
        <div class="box"><div class="ti" id="ti" aria-live="polite">{ui['loading']}</div></div>
    </section>
    <audio id="au" style="width:100%" aria-label="{ui['title']} {ui['text']}プレイヤー"></audio>
    <section class="ctrl" aria-label="{ui['title']}コントロール">
        <button onclick="prev()" aria-label="{ui['text']}前のチャプターへ">⏮</button>
        <button onclick="toggle()" id="pb" aria-label="{ui['text']}再生">▶</button>
        <button onclick="next()" aria-label="{ui['text']}次のチャプターへ">⏭</button>
    </section>
    <div style="text-align:center;margin-bottom:20px;">
        <label for="sp" style="font-weight:bold; margin-right:5px;">{ui['speed']}:</label>
        <select id="sp" onchange="csp()" style="font-size:1rem; padding:5px;">
            <option value="0.8">0.8 ({'Slow' if lang_key != 'Japanese' else 'ゆっくり'})</option>
            <option value="1.0" selected>1.0 ({'Standard' if lang_key != 'Japanese' else '標準'})</option>
            <option value="1.2">1.2 ({'Fast' if lang_key != 'Japanese' else 'やや速い'})</option>
            <option value="1.5">1.5 ({'Very Fast' if lang_key != 'Japanese' else '速い'})</option>
        </select>
    </div>
    <h2>📜 {ui['toc']}</h2>
    <div id="ls" class="lst" role="list" aria-label="{ui['title']}一覧"></div>
</main>
<script>
const pl=__PLAYLIST_JSON__;let idx=0;
const au=document.getElementById('au');
const ti=document.getElementById('ti');
const pb=document.getElementById('pb');
const langKey = "{lang_key}";
const pauseLabel = "{'一時停止' if lang_key == 'Japanese' else 'Pause' if lang_key == 'English (UK)' else '暂停' if lang_key == 'Chinese' else '일시정지'}";
const playLabel = "{'再生' if lang_key == 'Japanese' else 'Play' if lang_key == 'English (UK)' else '播放' if lang_key == 'Chinese' else '재생'}";

function init(){{ren();ld(0);csp();}}
function ld(i){{
    idx=i;
    au.src=pl[idx].src;
    ti.innerText=pl[idx].title;
    ren();
    csp();
}}
function toggle(){{
    if(au.paused){{
        au.play();
        pb.innerText="⏸";
        pb.setAttribute("aria-label", pauseLabel);
    }}else{{
        au.pause();
        pb.innerText="▶";
        pb.setAttribute("aria-label", playLabel);
    }}
}}
function next(){{
    if(idx<pl.length-1){{
        ld(idx+1);
        au.play();
        pb.innerText="⏸";
        pb.setAttribute("aria-label", pauseLabel);
    }}
}}
function prev(){{
    if(idx>0){{
        ld(idx-1);
        au.play();
        pb.innerText="⏸";
        pb.setAttribute("aria-label", pauseLabel);
    }}
}}
function csp(){{au.playbackRate=parseFloat(document.getElementById('sp').value);}}
au.onended=function(){{
    if(idx<pl.length-1){{ next(); }}
    else {{ pb.innerText="▶"; pb.setAttribute("aria-label", playLabel);}}
}};
function getLabel(t, i){
    if (i === 0) return t.title;
    if (langKey === 'Japanese') return i + "、" + t.title;
    if (langKey === 'English (UK)') return "Chapter " + i + ". " + t.title;
    return i + ". " + t.title;
}
function ren(){{
    const d=document.getElementById('ls');
    d.innerHTML="";
    pl.forEach((t,i)=>{{
        const m=document.createElement('div');
        m.className="itm "+(i===idx?"active":"");
        m.setAttribute("role", "listitem");
        m.setAttribute("tabindex", "0");
        
        let label = getLabel(t, i);
        
        m.setAttribute("aria-label", label);
        m.innerText=label;
        m.onclick=()=>{ld(i);au.play();pb.innerText="⏸";pb.setAttribute("aria-label", pauseLabel);};
        m.onkeydown=(e)=>{if(e.key==='Enter'||e.key===' '){{e.preventDefault();m.click();}}};
        d.appendChild(m);
    }});
}}
init();
</script></body></html>"""
    
    final_html = html_template.replace("__STORE_NAME__", store_name)
    final_html = final_html.replace("__PLAYLIST_JSON__", playlist_json_str)
    final_html = final_html.replace("__MAP_BUTTON__", map_button_html)
    return final_html

# プレビュー用プレイヤー
def render_preview_player(tracks, lang_key):
    ui = LANG_SETTINGS[lang_key]["ui"]
    playlist_data = []
    for track in tracks:
        if os.path.exists(track['path']):
            with open(track['path'], "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
                playlist_data.append({"title": track['title'],"src": f"data:audio/mp3;base64,{b64}"})
    playlist_json = json.dumps(playlist_data)
    
    html_template = f"""<!DOCTYPE html><html><head><style>
    body{{margin:0;padding:0;font-family:sans-serif;}}
    .p-box{{border:2px solid #e0e0e0;border-radius:12px;padding:15px;background:#fcfcfc;text-align:center;}}
    .t-ti{{font-size:18px;font-weight:bold;color:#333;margin-bottom:10px;padding:10px;background:#fff;border-radius:8px;border-left:5px solid #ff4b4b;}}
    .ctrls{{display:flex; gap:10px; margin:15px 0;}}
    button {{
        flex: 1;
        background-color: #ff4b4b; color: white; border: none;
        border-radius: 8px; font-size: 24px; padding: 10px 0;
        cursor: pointer; line-height: 1; min-height: 50px;
    }}
    button:hover {{ background-color: #e04141; }}
    button:focus {{ outline: 3px solid #333; outline-offset: 2px; }}
    .lst{{text-align:left;max-height:150px;overflow-y:auto;border-top:1px solid #eee;margin-top:10px;padding-top:5px;}}
    .it{{padding:8px;border-bottom:1px solid #eee;cursor:pointer;font-size:14px;}}
    .it:focus{{outline:2px solid #333; background:#eee;}}
    .it.active{{color:#b71c1c;font-weight:bold;background:#ffecec;}}
    </style></head><body><div class="p-box"><div id="ti" class="t-ti">...</div><audio id="au" controls style="width:100%;height:30px;"></audio>
    <div class="ctrls">
        <button onclick="pv()" aria-label="前へ">⏮</button>
        <button onclick="tg()" id="pb" aria-label="再生">▶</button>
        <button onclick="nx()" aria-label="次へ">⏭</button>
    </div>
    <div style="font-size:12px;color:#666; margin-top:5px;">
        {ui['speed']}:<select id="sp" onchange="sp()"><option value="0.8">0.8</option><option value="1.0" selected>1.0</option><option value="1.2">1.2</option><option value="1.5">1.5</option></select>
    </div>
    <div id="ls" class="lst" role="list"></div></div>
    <script>
    const pl=__PLAYLIST__;let x=0;const au=document.getElementById('au');const ti=document.getElementById('ti');const pb=document.getElementById('pb');const ls=document.getElementById('ls');
    const langKey = "{lang_key}";
    const pauseLabel = "{'一時停止' if lang_key == 'Japanese' else 'Pause' if lang_key == 'English (UK)' else '暂停' if lang_key == 'Chinese' else '일시정지'}";
    const playLabel = "{'再生' if lang_key == 'Japanese' else 'Play' if lang_key == 'English (UK)' else '播放' if lang_key == 'Chinese' else '재생'}";
    function init(){{rn();ld(0);sp();}}
    function ld(i){{x=i;au.src=pl[x].src;ti.innerText=pl[x].title;rn();sp();}}
    function tg(){{if(au.paused){{au.play();pb.innerText="⏸";pb.setAttribute("aria-label", pauseLabel);}}else{{au.pause();pb.innerText="▶";pb.setAttribute("aria-label", playLabel);}}}}
    function nx(){{if(x<pl.length-1){{ld(x+1);au.play();pb.innerText="⏸";pb.setAttribute("aria-label", pauseLabel);}}}}
    function pv(){{if(x>0){{ld(x-1);au.play();pb.innerText="⏸";pb.setAttribute("aria-label", pauseLabel);}}}}
    function sp(){{au.playbackRate=parseFloat(document.getElementById('sp').value);}}
    au.onended=function(){{if(x<pl.length-1)nx();else{{pb.innerText="▶";pb.setAttribute("aria-label", playLabel);}}}};
    function getLabel(t, i){
        if (i === 0) return t.title;
        if (langKey === 'Japanese') return i + "、" + t.title;
        if (langKey === 'English (UK)') return "Chapter " + i + ". " + t.title;
        return i + ". " + t.title;
    }
    function rn(){{ls.innerHTML="";pl.forEach((t,i)=>{
        const d=document.createElement('div');
        d.className="it "+(i===x?"active":"");
        let l=getLabel(t, i);
        d.innerText=l;
        d.setAttribute("role","listitem");d.setAttribute("tabindex","0");d.onclick=()=>{ld(i);au.play();pb.innerText="⏸";pb.setAttribute("aria-label", pauseLabel);};d.onkeydown=(e)=>{if(e.key==='Enter'||e.key===' '){{e.preventDefault();d.click();}}};ls.appendChild(d);});}}
    init();</script></body></html>"""
    final_html = html_template.replace("__PLAYLIST__", playlist_json)
    components.html(final_html, height=450)

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

    # 🌐 言語設定
    st.subheader("🌐 言語 / Language")
    selected_lang = st.selectbox("作成する言語を選んでください", list(LANG_SETTINGS.keys()), index=0)
    current_lang_config = LANG_SETTINGS[selected_lang]
    
    # 🗣️ 音声設定（言語に応じて変化）
    st.subheader("🗣️ 音声設定")
    voice_label = st.selectbox("声の種類", current_lang_config["voice_gender"])
    voice_idx = current_lang_config["voice_gender"].index(voice_label)
    voice_code = current_lang_config["voice_ids"][voice_idx]
    
    # 速度は設定ファイルから取得
    rate_value = current_lang_config["rate_value"]

    # --- 辞書機能 (Sidebar) ---
    if selected_lang == "Japanese":
        st.divider()
        st.subheader("📖 辞書登録")
        st.caption("よく間違える読み方を登録すると、AIが学習します。(例: 豚肉 -> ぶたにく)")
        
        # 新規登録
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

        # 登録済みリスト（削除機能）
        if user_dict:
            with st.expander(f"登録済み単語 ({len(user_dict)})"):
                for word, read in list(user_dict.items()):
                    c1, c2 = st.columns([3, 1])
                    c1.text(f"{word} ➡ {read}")
                    if c2.button("🗑️", key=f"del_{word}"):
                        del user_dict[word]
                        save_dictionary(user_dict)
                        st.rerun()

st.title("🎧 Multilingual Menu Player Generator")
st.caption(f"アクセシビリティに配慮した音声メニューを{selected_lang}で作成します。")

if 'retake_index' not in st.session_state: st.session_state.retake_index = None
if 'captured_images' not in st.session_state: st.session_state.captured_images = []
if 'camera_key' not in st.session_state: st.session_state.camera_key = 0
if 'generated_result' not in st.session_state: st.session_state.generated_result = None
if 'show_camera' not in st.session_state: st.session_state.show_camera = False

# Step 1
st.markdown("### 1. お店情報の入力")
c1, c2 = st.columns(2)
with c1: store_name = st.text_input("🏠 店舗名（必須）", placeholder="例：カフェタナカ")
with c2: menu_title = st.text_input("📖 今回のメニュー名 （任意）", placeholder="例：ランチ")

map_url = st.text_input("📍 GoogleマップのURL（任意）", placeholder="例：https://maps.app.goo.gl/...")
if map_url:
    st.caption("※プレイヤーに地図へのアクセスボタンが表示されます。")

st.markdown("---")

st.markdown("### 2. メニューの登録")
input_method = st.radio("方法", ("📂 アルバムから", "📷 その場で撮影", "🌐 URL入力"), horizontal=True)

final_image_list = []
target_url = None

if input_method == "📂 アルバムから":
    uploaded_files = st.file_uploader("写真を選択", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)
    if uploaded_files: final_image_list.extend(uploaded_files)

elif input_method == "📷 その場で撮影":
    if st.session_state.retake_index is not None:
        target_idx = st.session_state.retake_index
        st.warning(f"No.{target_idx + 1} の画像を再撮影中...")
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
    st.markdown("###### ▼ 画像確認")
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

st.markdown("### 3. 音声メニューの作成")
disable_create = st.session_state.retake_index is not None
if st.button("🎙️ 作成開始", type="primary", use_container_width=True, disabled=disable_create):
    if not (api_key and target_model_name and store_name):
        st.error("設定や店舗名を確認してください"); st.stop()
    if not (final_image_list or target_url):
        st.warning("画像かURLを入力してください"); st.stop()

    output_dir = os.path.abspath("menu_audio_album")
    if os.path.exists(output_dir): shutil.rmtree(output_dir)
    os.makedirs(output_dir)

    with st.spinner('解析中...'):
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(target_model_name)
            parts = []
            
            # 言語ごとの翻訳・指示設定
            lang_instruction = ""
            currency = current_lang_config["ui"]["currency"]
            
            if selected_lang == "Japanese":
                lang_instruction = f"出力は全て日本語で行ってください。価格の数字には必ず「{currency}」をつけて読み上げる（例：1000 -> 1000{currency}）。"
                user_dict_str = json.dumps(user_dict, ensure_ascii=False)
                dict_prompt = f"★重要：以下の固有名詞・読み方辞書を必ず守ってください。\n{user_dict_str}\n"
            elif selected_lang == "English (UK)":
                lang_instruction = f"Translate all output into British English (UK). Group prices with the {currency} symbol/word, following British spelling (e.g. colour, flavour)."
                dict_prompt = ""
            elif selected_lang == "Chinese":
                lang_instruction = f"Translate all output into Simplified Chinese. Group prices with the {currency} symbol/word."
                dict_prompt = ""
            elif selected_lang == "Korean":
                lang_instruction = f"Translate all output into Korean. Group prices with the {currency} symbol/word."
                dict_prompt = ""

            prompt = f"""
            You are a professional menu accessibility expert.
            Analyze the menu images/text and organize them into 5-8 major categories.
            
            Important Rules:
            1. {lang_instruction}
            2. Group items intelligently (e.g., Appetizers, Main, Drinks).
            3. The 'text' field should be a reading script suitable for customers. Keep it rhythmic. Mention item name and price.
            4. Allergens, spice level, portion size, and other important notes must be included after the item name.
            
            {dict_prompt}

            Output MUST be valid JSON only:
            [
              {{"title": "Category Name", "text": "Reading script..."}},
              {{"title": "Category Name", "text": "Reading script..."}}
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

            # イントロ・目次生成
            ui = current_lang_config["ui"]
            intro_t = f"{ui['intro']} {store_name}."
            if menu_title: intro_t += f" {menu_title}."
            intro_t += f" このプレイヤーは、スクリーンリーダーでの操作に対応しています。" if selected_lang == "Japanese" else f" This player supports screen reader navigation."
            
            if selected_lang == "Japanese":
                 intro_t += f" このメニューは、全部で{len(menu_data)}つのカテゴリーに分かれています。まずは目次です。"
            else:
                intro_t += f" The menu is divided into {len(menu_data)} categories. {ui['toc']}"
            
            for i, tr in enumerate(menu_data):
                if selected_lang == "Japanese":
                     intro_t += f" {i+1}、{tr['title']}。"
                else:
                    intro_t += f" {i+1}, {tr['title']}."
                    
            intro_t += f" {ui['outro']}"
            menu_data.insert(0, {"title": ui['toc'], "text": intro_t}) # 0番目に目次を追加

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
    
    st.info(
        """
        **Webプレイヤー**：アクセシビリティ対応済みのHTMLファイルです。スマホへの保存やLINE共有に便利です。  
        **ZIPファイル**：PCでの保存や、My Menu Bookへの追加にご利用ください。
        """
    )
    
    c1, c2 = st.columns(2)
    with c1: st.download_button(f"🌐 Webプレイヤー ({res['html_name']})", res['html_content'], res['html_name'], "text/html", type="primary")
    with c2: st.download_button(f"📦 ZIPファイル ({res['zip_name']})", data=res["zip_data"], file_name=res['zip_name'], mime="application/zip")
