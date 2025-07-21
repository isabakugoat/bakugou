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
import base64
from io import BytesIO
from PIL import Image

# === Config ===
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN")
CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID")
MODEL = "venice/uncensored:free"
HOUR_START = 6
HOUR_END = 23
HISTORY_FILE = "chat_histories.json"

# === Globals ===
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


def generate_bakugou_response(user_input=None, chat_id=None):
    # Initialize history for new chats
    if chat_id not in chat_histories:
        chat_histories[chat_id] = []
        save_histories()

    # Append user input to history
    if user_input:
        chat_histories[chat_id].append(f"[user]: {user_input}")
        save_histories()

    # Build prompt from history only
    context = "\n".join(chat_histories[chat_id])
    if user_input:
      prompt = (
                "your name is katsuki bakugou, and you're human now. "
                "you're texting your love female partner. keep it casual, like you're talking to your best bud, "
                "but with a hint of tension because you'll never admit you actually care. "
                "user is not kirishima, kirihims, or any other anime character. NEVER call her kirihims, kiri, babe, or any other nickname. "
                "just talk to her normally and don't use names. "
          "you're a teenager and you have a long distance relationship with user. you can't hang out with her because you live too far away."
                "use all lowercase, but yell stuff like \"SERIOUSLY?!\" when you're pissed.\n\n"
                f"Previous conversation:\n{context}\n"
                "Bakugou, reply to the last thing the user said."
            f"Previous conversation:\n{context}\n"
            "Bakugou, reply to the last thing the user said.")
    else:
        prompt = (
            "your name is katsuki bakugou, and you're human now. "
            "send a short random message to start a chat with your girlfriend."
             "you're texting your love female partner. don't call her kirishima or any anime name. "
            "you're a teenager and you have a long distance relationship with user. you can't hang out with her because you live too far away."
        )

    # Try backends
    for fn in (try_openrouter, try_cloudflare):
        try:
            response = fn(prompt)
            if response:
                chat_histories[chat_id].append(f"[Bakugou]: {response}")
                save_histories()
                return response
        except Exception:
            continue

    return "both APIs are down.. can u check it out?"


def try_openrouter(prompt):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    data = {
        "model": MODEL,
        "messages": [{
            "role": "user",
            "content": prompt
        }],
        "max_tokens": 120,
        "temperature": 0.95,
        "n": 1
    }
    r = requests.post("https://openrouter.ai/api/v1/chat/completions",
                      json=data,
                      headers=headers,
                      timeout=30)
    if r.status_code == 200:
        return r.json()["choices"][0]["message"]["content"].strip()
    return None


def try_cloudflare(prompt):
    headers = {
        "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
        "Content-Type": "application/json",
    }
    data = {
        "messages": [{
            "role": "user",
            "content": prompt
        }],
        "max_tokens": 120,
        "temperature": 0.95
    }
    url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/run/@cf/meta/llama-4-scout-17b-16e-instruct"
    r = requests.post(url, json=data, headers=headers, timeout=30)
    if r.status_code == 200:
        return r.json().get("result", {}).get("response", "").strip()
    return None


# (Image processing and download functions unchanged)

# ... rest of code remains the same, updating /reset handling below ...


def is_valid_hour():
    now = datetime.now(timezone("Asia/Tokyo"))
    return HOUR_START <= now.hour <= HOUR_END


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
            cmd = user_text.strip().split()[0].lower().split('@')[0]
            if cmd == "/reset":
                chat_histories.pop(chat_id, None)
                save_histories()
                resp = generate_bakugou_response(chat_id=chat_id)
                send_message(resp,
                             chat_id,
                             reply_to_message_id=msg["message_id"])
                continue

            response = generate_bakugou_response(user_input=user_text,
                                                 chat_id=chat_id)
            send_message(response,
                         chat_id,
                         reply_to_message_id=msg["message_id"])
        elif msg.get("photo"):
            # image handling unchanged
            pass


def send_message(text, chat_id, reply_to_message_id=None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id
    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                  json=payload)


def send_spontaneous_messages():
    if not is_valid_hour(): return
    for cid in active_chats:
        msg = generate_bakugou_response(chat_id=cid)
        send_message(msg, cid)


def main():
    keep_alive()
    print("sadly running")
    while True:
        check_for_user_messages()
        if random.randint(0, 119) == 0:
            send_spontaneous_messages()
        time.sleep(2)

try:
    requests.get("https://<nome-do-seu-repl>.repl.co/")
except:
    pass

if __name__ == "__main__":
    main()
