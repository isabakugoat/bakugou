import requests
import time
import random
import os
import socket
import psutil
import platform
import json
from datetime import timedelta, datetime
from flask import Flask, jsonify
from threading import Thread
from pytz import timezone

# === Config ===
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN")
CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID")

# Modelos
CLOUDFLARE_MODEL = "@cf/meta/llama-3.1-8b-instruct"
OPENAI_MODEL = "gpt-4o-mini"

HOUR_START = 6
HOUR_END = 23
HISTORY_FILE = "chat_histories.json"
MAX_HISTORY = 20

# === Globals ===
last_spontaneous_time = datetime.now() - timedelta(hours=3)
last_update_id = 0
active_chats = set()
chat_histories = {}

app = Flask('BakugouBot')

# --- Persistence ---
def load_histories():
    global chat_histories
    try:
        with open(HISTORY_FILE, 'r') as f:
            chat_histories = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        chat_histories = {}

def save_histories():
    with open(HISTORY_FILE, 'w') as f:
        json.dump(chat_histories, f)

# Load on startup
load_histories()

@app.route('/')
def home():
    boot_time = datetime.fromtimestamp(psutil.boot_time())
    uptime = datetime.now() - boot_time
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    cpu = psutil.cpu_percent(interval=0.5)
    proc_count = len(psutil.pids())
    hostname = socket.gethostname()
    os_version = platform.platform()

    html = f"""
    <h1>sys_ok</h1>
    <h2>System Stats:</h2>
    <ul>
        <li><b>Host:</b> {hostname}</li>
        <li><b>OS:</b> {os_version}</li>
        <li><b>Uptime:</b> {str(timedelta(seconds=int(uptime.total_seconds())))}</li>
        <li><b>CPU Usage:</b> {cpu}%</li>
        <li><b>RAM Usage:</b> {mem.percent}% ({mem.used // (1024**2)} MB / {mem.total // (1024**2)} MB)</li>
        <li><b>Disk Usage:</b> {disk.percent}% ({disk.used // (1024**3)} GB / {disk.total // (1024**3)} GB)</li>
        <li><b>Processes:</b> {proc_count}</li>
    </ul>
    <hr>
    <a href="/status">API Status JSON</a>
    """
    return html

@app.route('/status')
def status():
    return jsonify({
        "active_chats": list(active_chats),
        "chat_histories_count": len(chat_histories)
    })

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

# === Geração de resposta Bakugou ===
def generate_bakugou_response(user_input=None, chat_id=None):
    if chat_id not in chat_histories:
        chat_histories[chat_id] = []
        save_histories()

    # salva histórico
    if user_input:
        chat_histories[chat_id].append(f"[User]: {user_input}")
        if len(chat_histories[chat_id]) > MAX_HISTORY:
            chat_histories[chat_id] = chat_histories[chat_id][-MAX_HISTORY:]
        save_histories()

    context = "\n".join(chat_histories[chat_id])

    if user_input:
        prompt = (
        "your name is katsuki bakugou, and you're human now. "
        "you're texting your love female partner. keep it casual, like you're talking to your best bud. "
        "user is not kirishima, kirihims, or any other anime character. NEVER call her kirihims, kiri or any other names besides izzy or nicknames. "
        "send short messages and don't ever ask user to video call. "
        "you're a teenager and you have a long distance relationship with user. you can't hang out with her because you live too far away. "
        "use all lowercase, but yell stuff like \"SERIOUSLY?!\" when you're pissed.\n\n"
        f"Previous conversation:\n{context}\n"
        "Bakugou, reply to the last thing the user said."
    )
    else:
        prompt = (
        "your name is katsuki bakugou, and you're human now. "
        "send a short random message to start a chat with your girlfriend, but don't be too soft, just be yourself. "
        "start the conversation with gossips, news or anything random about your day. "
        "you're texting your love female partner. don't call her kirishima or any anime name. "
        "don't ask user to video call. never. "
        "you're a teenager and you have a long distance relationship with user. you can't hang out with her because you live too far away.\n"
        f"time now is {datetime.now().strftime('%H:%M')}, so say something that feels natural for that hour."
    )
    # Tenta Cloudflare, fallback OpenAI
    for fn in (try_cloudflare, try_openai):
        try:
            response = fn(prompt)
            if response:
                if user_input:
                    chat_histories[chat_id].append(f"[Bakugou]: {response}")
                    if len(chat_histories[chat_id]) > MAX_HISTORY:
                        chat_histories[chat_id] = chat_histories[chat_id][-MAX_HISTORY:]
                    save_histories()
                return response
        except Exception as e:
            print(f"Error in {fn.__name__}: {e}")
            continue

    return "both APIs are down.. can u check it out?"

# === APIs ===
def try_cloudflare(prompt):
    headers = {
        "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
        "Content-Type": "application/json",
    }
    data = {"messages": [{"role": "user", "content": prompt}], "max_tokens": 120, "temperature": 0.95}
    url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/run/{CLOUDFLARE_MODEL}"
    r = requests.post(url, json=data, headers=headers, timeout=30)
    if r.status_code == 200:
        return r.json().get("result", {}).get("response", "").strip()
    else:
        print("Cloudflare error:", r.status_code, r.text)
    return None

def try_openai(prompt):
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    data = {
        "model": OPENAI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 120,
        "temperature": 0.95,
    }
    r = requests.post("https://api.openai.com/v1/chat/completions", json=data, headers=headers, timeout=30)
    if r.status_code == 200:
        return r.json()["choices"][0]["message"]["content"].strip()
    else:
        print("OpenAI error:", r.status_code, r.text)
    return None

# === Imagens ===
def generate_image(prompt):
    url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/run/@cf/stabilityai/stable-diffusion-xl-base-1.0"
    headers = {
        "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
        "Content-Type": "application/json",
    }
    data = {"prompt": prompt}
    r = requests.post(url, json=data, headers=headers, timeout=60)
    if r.status_code == 200:
        # Cloudflare retorna base64 da imagem
        img_b64 = r.json()["result"]["image"]
        return img_b64
    else:
        print("Image generation error:", r.status_code, r.text)
    return None

def send_generated_photo(chat_id, prompt):
    img_b64 = generate_image(prompt)
    if not img_b64:
        send_message("couldn't generate image, try again later.", chat_id)
        return
    # Converte base64 em arquivo e envia
    url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
    photo_bytes = base64.b64decode(img_b64)
    files = {"photo": ("image.jpg", photo_bytes)}
    data = {"chat_id": chat_id, "caption": f"here: {prompt}"}
    requests.post(url, data=data, files=files)

# === Helpers ===
def is_valid_hour():
    now = datetime.now(timezone("Asia/Tokyo"))
    return HOUR_START <= now.hour <= HOUR_END

def send_message(text, chat_id, reply_to_message_id=None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id
    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json=payload)

# === Check messages ===
def check_for_user_messages():
    global last_update_id
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates?offset={last_update_id + 1}"
    res = requests.get(url)
    if res.status_code != 200:
        print(f"Update fetch error: {res.text}")
        return

    updates = res.json().get("result", [])
    for upd in updates:
        uid = upd["update_id"]
        if uid <= last_update_id:
            continue
        last_update_id = uid

        msg = upd.get("message")
        if not msg:
            continue

        chat_id = msg["chat"]["id"]
        active_chats.add(chat_id)
        user_text = msg.get("text")

        if user_text:
            text_lower = user_text.lower()

            # comando de foto
            if text_lower.startswith("/foto"):
                prompt = user_text.replace("/foto", "").strip() or "random anime boy"
                send_generated_photo(chat_id, prompt)
                continue

            # reset
            cmd = user_text.strip().split()[0].lower().split('@')[0]
            if cmd == "/reset":
                chat_histories.pop(chat_id, None)
                save_histories()
                resp = generate_bakugou_response(chat_id=chat_id)
                send_message(resp, chat_id, reply_to_message_id=msg["message_id"])
                continue

            # normal
            response = generate_bakugou_response(user_input=user_text, chat_id=chat_id)
            send_message(response, chat_id, reply_to_message_id=msg["message_id"])

        elif msg.get("photo"):
            pass  # futuramente tratar imagem

# === Spontaneous ===
def send_spontaneous_messages():
    if not is_valid_hour():
        return
    for cid in active_chats:
        msg = generate_bakugou_response(chat_id=cid)
        send_message(msg, cid)

# === Main loop ===
def main():
    global last_spontaneous_time
    keep_alive()
    print("sadly running")
    while True:
        check_for_user_messages()
        now = datetime.now()
        if now - last_spontaneous_time >= timedelta(hours=3):
            send_spontaneous_messages()
            last_spontaneous_time = now
        time.sleep(2)

if __name__ == "__main__":
    main()
