import streamlit as st
import zipfile
import base64
import json
import os
import re
import streamlit.components.v1 as components

# ページ設定
st.set_page_config(page_title="My Menu Book", layout="centered")

st.markdown("""
<style>
    body { font-family: sans-serif; }
    h1 { color: #ff4b4b; }
    .stButton button { width: 100%; }
</style>
""", unsafe_allow_html=True)

st.title("🎧 My Menu Book")

# データ管理
if 'my_library' not in st.session_state:
    st.session_state.my_library = {}

# --- サイドバー：本の追加 ---
with st.sidebar:
    st.header("➕ 本の追加")
    st.info("生成アプリで作ったZIPファイルを登録します。")
    
    uploaded_zips = st.file_uploader("ZIPファイルをドロップ", type="zip", accept_multiple_files=True)
    
    if uploaded_zips:
        for zfile in uploaded_zips:
            filename = os.path.splitext(zfile.name)[0]
            store_name = re.sub(r'_\d{8}.*', '', filename).replace("_", " ")
            st.session_state.my_library[store_name] = zfile
            
        st.success(f"{len(uploaded_zips)}冊を追加しました！")

    st.divider()
    if st.button("🗑️ 本棚を空にする"):
        st.session_state.my_library = {}
        st.session_state.selected_shop = None
        st.rerun()

# プレイヤー生成関数
def render_player(shop_name):
    zfile = st.session_state.my_library[shop_name]
    playlist_data = []
    map_url = None

    try:
        with zipfile.ZipFile(zfile) as z:
            file_list = sorted(z.namelist())
            
            for f in file_list:
                if f.endswith(".html"):
                    try:
                        html_content = z.read(f).decode('utf-8')
                        match = re.search(r'href="(https://.*?maps.*?)"', html_content)
                        if match:
                            map_url = match.group(1)
                    except: pass

            for f in file_list:
                if f.endswith(".mp3"):
                    data = z.read(f)
                    b64_data = base64.b64encode(data).decode()
                    title = f.replace(".mp3", "").replace("_", " ")
                    title = re.sub(r'^\d{2}\s*', '', title) 
                    playlist_data.append({"title": title, "src": f"data:audio/mp3;base64,{b64_data}"})
                    
    except Exception as e:
        st.error(f"ファイルの読み込みエラー: {e}"); return

    playlist_json = json.dumps(playlist_data, ensure_ascii=False)

    map_btn_html = ""
    if map_url:
        map_btn_html = f"""
        <div style="margin: 15px 0;">
            <a href="{map_url}" target="_blank" style="text-decoration:none;">
                <button style="width:100%; padding:10px; background:#4285F4; color:white; border:none; border-radius:8px; font-weight:bold; cursor:pointer;">
                    🗺️ Googleマップを開く
                </button>
            </a>
        </div>
        """

    # HTMLテンプレート (f文字列を使わない)
    html_raw = """<!DOCTYPE html><html><head><style>
        .player-container { border: 2px solid #e0e0e0; border-radius: 15px; padding: 20px; background-color: #f9f9f9; text-align: center; }
        .track-title { font-size: 20px; font-weight: bold; color: #333; margin-bottom: 15px; padding: 10px; background: #fff; border-radius: 8px; border-left: 5px solid #ff4b4b; }
        .controls { display: flex; gap: 10px; margin: 15px 0; }
        button.ctrl-btn { flex: 1; padding: 15px; font-size: 18px; font-weight: bold; color: white; background-color: #ff4b4b; border: none; border-radius: 8px; cursor: pointer; }
        .track-list { margin-top: 20px; text-align: left; max-height: 250px; overflow-y: auto; border-top: 1px solid #ddd; padding-top: 10px; }
        .track-item { padding: 10px; border-bottom: 1px solid #eee; cursor: pointer; }
        .track-item.active { background-color: #ffecec; font-weight: bold; color: #ff4b4b; }
    </style></head><body>
    <div class="player-container">
        <div class="track-title" id="title">Loading...</div>
        <audio id="audio" controls style="width:100%"></audio>
        <div class="controls">
            <button class="ctrl-btn" onclick="prev()">⏮</button>
            <button class="ctrl-btn" onclick="toggle()" id="pb">▶ / ⏸</button>
            <button class="ctrl-btn" onclick="next()">⏭</button>
        </div>
        __MAP_BUTTON__
        <div style="text-align:center; margin-top:10px;">
            速度: <select id="speed" onchange="spd()">
                <option value="0.8">0.8 (ゆっくり)</option>
                <option value="1.0" selected>1.0 (標準)</option>
                <option value="1.2">1.2 (少し速く)</option>
                <option value="1.5">1.5 (速く)</option>
            </select>
        </div>
        <div class="track-list" id="list"></div>
    </div>
    <script>
        const pl = __PLAYLIST__; let idx = 0;
        const au = document.getElementById('audio'); const ti = document.getElementById('title'); const btn = document.getElementById('pb'); const ls = document.getElementById('list');
        function init() { render(); load(0); spd(); }
        function load(i) { idx = i; au.src = pl[idx].src; ti.innerText = pl[idx].title; highlight(); spd(); }
        function toggle() { if(au.paused){au.play(); btn.innerText="⏸";} else {au.pause(); btn.innerText="▶";} }
        function next() { if(idx < pl.length-1) { load(idx+1); au.play(); btn.innerText="⏸"; } }
        function prev() { if(idx > 0) { load(idx-1); au.play(); btn.innerText="⏸"; } }
        function spd() { au.playbackRate = parseFloat(document.getElementById('speed').value); }
        au.onended = function() { idx < pl.length-1 ? next() : btn.innerText="▶"; };
        function render() { ls.innerHTML = ""; pl.forEach((t, i) => { const d = document.createElement('div'); d.className = "track-item"; d.id = "tr-" + i; d.innerText = (i+1) + ". " + t.title; d.onclick = () => { load(i); au.play(); btn.innerText="⏸"; }; ls.appendChild(d); }); }
        function highlight() { document.querySelectorAll('.track-item').forEach(e => e.classList.remove('active')); const el = document.getElementById("tr-" + idx); if(el) { el.classList.add('active'); el.scrollIntoView({behavior:'smooth', block:'nearest'}); } }
        init();
    </script></body></html>"""
    
    # テンプレート変数を置換 (f文字列を使わないので安全)
    html = html_raw.replace("__PLAYLIST__", playlist_json)
    html = html.replace("__MAP_BUTTON__", map_btn_html)
    st.components.v1.html(html, height=600)

# --- 画面表示 ---
if 'selected_shop' not in st.session_state:
    st.session_state.selected_shop = None

if st.session_state.selected_shop:
    shop_name = st.session_state.selected_shop
    st.markdown(f"### 🎧 再生中: {shop_name}")
    if st.button("⬅️ リストに戻る", use_container_width=True):
        st.session_state.selected_shop = None
        st.rerun()
    st.markdown("---")
    render_player(shop_name)
else:
    st.markdown("#### 📚 本棚")
    search_query = st.text_input("🔍 お店を検索", placeholder="例: カフェ")
    if not st.session_state.my_library:
        st.info("👈 左のサイドバーにZIPファイルをアップロードしてください。")
    
    shop_list = list(st.session_state.my_library.keys())
    if search_query:
        shop_list = [name for name in shop_list if search_query in name]
    
    for shop_name in shop_list:
        # ここを修正しました (文法エラーの箇所)
        if st.button(f"📖 {shop_name}", use_container_width=True):
            st.session_state.selected_shop = shop_name
            st.rerun()
