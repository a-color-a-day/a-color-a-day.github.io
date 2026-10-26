import json
import random
from datetime import datetime, timezone
import os
import requests
from PIL import Image
import io
import colorsys

def load_color_database():
    """Lädt optional eine lokale Farbdatenbank (z.B. color_database.json)"""
    try:
        with open('color_database.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def generate_color_name(r, g, b, hex_code):
    # 1. Prüfen, ob der HEX-Code in der großen Farbdatenbank existiert
    color_db = load_color_database()
    hex_lower = hex_code.lower()
    if hex_lower in color_db:
        return color_db[hex_lower]

    # 2. Ansonsten Fallback auf unsere poetische HSL-Logik
    rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
    h, l, s = colorsys.rgb_to_hls(rf, gf, bf)
    hue = h * 360

    if l < 0.22:
        light_mod = ["Deep-sea", "Midnight", "Abyss", "Shadows", "Obsidian"]
    elif l > 0.78:
        light_mod = ["Mist", "Whisper", "Dawn", "Glow", "Haze"]
    elif s < 0.18:
        light_mod = ["Muted", "Silent", "Dust", "Faded", "Soft"]
    else:
        light_mod = ["Radiant", "Vivid", "Ethereal", "Pure", "Luminous"]

    if hue < 15 or hue >= 345:
        base_names = ["scarlet", "crimson", "ember", "ruby", "blush"]
    elif 15 <= hue < 45:
        base_names = ["amber", "copper", "rust", "autumn", "terra"]
    elif 45 <= hue < 70:
        base_names = ["saffron", "honey", "ochre", "sun", "gold"]
    elif 70 <= hue < 150:
        base_names = ["olive", "moss", "emerald", "forest", "sage"]
    elif 150 <= hue < 200:
        base_names = ["teal", "lagoon", "pine", "glacier", "mint"]
    elif 200 <= hue < 260:
        base_names = ["cerulean", "azure", "cobalt", "ocean", "indigo"]
    elif 260 <= hue < 310:
        base_names = ["purple", "lilac", "lavender", "plum", "violet"]
    else:
        base_names = ["magenta", "coral", "rose", "orchid", "wine"]

    mod = light_mod[(r + g) % len(light_mod)]
    base = base_names[(g + b) % len(base_names)]

    return f"{mod} {base}"

try:
    with open('colors.json', 'r', encoding='utf-8') as f:
        history = json.load(f)
except FileNotFoundError:
    history = []

today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

if history and history[-1].get("date") == today_str:
    latest_entry = history[-1]
    print(f"Using existing color for today: {latest_entry['name']} ({latest_entry['hex']})")
else:
    day_number = len(history) + 1
    r = random.randint(0, 255)
    g = random.randint(0, 255)
    b = random.randint(0, 255)
    hex_code = f"#{r:02X}{g:02X}{b:02X}"
    color_name = generate_color_name(r, g, b, hex_code)

    latest_entry = {
        "day": day_number,
        "date": today_str,
        "hex": hex_code,
        "rgb": [r, g, b],
        "name": color_name
    }
    history.append(latest_entry)

    with open('colors.json', 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=2, ensure_ascii=False)
    print(f"Generated Day {day_number}: {color_name} ({hex_code})")

handle = os.environ.get("BLUESKY_HANDLE")
password = os.environ.get("BLUESKY_PASSWORD")

if handle and password:
    try:
        print("Logging in to Bluesky...")
        session_res = requests.post("https://bsky.social/xrpc/com.atproto.server.createSession", json={
            "identifier": handle,
            "password": password
        })
        session_res.raise_for_status()
        session = session_res.json()
        access_token = session["accessJwt"]
        did = session["did"]

        print("Generating color image...")
        img = Image.new("RGB", (1080, 1080), tuple(latest_entry["rgb"]))
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='JPEG', quality=90)
        img_bytes = img_byte_arr.getvalue()

        print("Uploading image blob to Bluesky...")
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "image/jpeg"
        }
        blob_res = requests.post("https://bsky.social/xrpc/com.atproto.repo.uploadBlob", headers=headers, data=img_bytes)
        blob_res.raise_for_status()
        blob_data = blob_res.json()["blob"]

        day_str = str(latest_entry['day']).zfill(5)
        text = (
            f"Day {day_str} / 16,777,216\n"
            f"{latest_entry['name']}\n"
            f"{latest_entry['hex']} • RGB ({latest_entry['rgb'][0]}, {latest_entry['rgb'][1]}, {latest_entry['rgb'][2]})\n\n"
            f"\"One small splash of color per day – for eternity.\"\n\n"
            f"https://a-color-a-day.github.io/infinity/"
        )

        print("Publishing post to Bluesky...")
        post_record = {
            "$type": "app.bsky.feed.post",
            "text": text,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "embed": {
                "$type": "app.bsky.embed.images",
                "images": [
                    {
                        "alt": f"{latest_entry['name']} ({latest_entry['hex']})",
                        "image": blob_data
                    }
                ]
            }
        }

        post_res = requests.post("https://bsky.social/xrpc/com.atproto.repo.createRecord", headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }, json={
            "repo": did,
            "collection": "app.bsky.feed.post",
            "record": post_record
        })
        post_res.raise_for_status()
        print("Successfully posted to Bluesky!")

    except Exception as e:
        print(f"Error posting to Bluesky: {e}")
else:
    print("Bluesky credentials not found in environment variables.")
