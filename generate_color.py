import json
import random
from datetime import datetime, timezone
import os
import requests
from PIL import Image
import io
import colorsys

def generate_color_name(r, g, b):
    # Konvertiere RGB in HLS (Hue, Lightness, Saturation) für präzise Farbnamen
    rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
    h, l, s = colorsys.rgb_to_hls(rf, gf, bf)
    hue = h * 360

    # Bestimme den Modifikator basierend auf Helligkeit und Sättigung
    if l < 0.2:
        modifier = "Deep"
    elif l > 0.82:
        modifier = "Radiant" if s > 0.3 else "Pale"
    elif s < 0.15:
        modifier = "Muted"
    elif s > 0.75:
        modifier = "Vivid"
    else:
        modifier = "Subtle"

    # Bestimme den Basis-Farbnamen anhand des Farbkreises (Hue 0-360°)
    if hue < 15 or hue >= 345:
        base = "Scarlet" if l < 0.5 else "Crimson"
    elif 15 <= hue < 40:
        base = "Vermilion" if s > 0.6 else "Amber"
    elif 40 <= hue < 65:
        base = "Saffron" if l > 0.5 else "Ochre"
    elif 65 <= hue < 140:
        base = "Olive" if l > 0.4 else "Emerald"
    elif 140 <= hue < 195:
        base = "Teal" if l < 0.5 else "Cyan"
    elif 195 <= hue < 250:
        base = "Cerulean" if l > 0.5 else "Azure"
    elif 250 <= hue < 290:
        base = "Violet" if l > 0.5 else "Indigo"
    elif 290 <= hue < 345:
        base = "Magenta" if s > 0.5 else "Coral"
    else:
        base = "Coral"

    return f"{modifier} {base}"

# Farbhistorie laden
try:
    with open('colors.json', 'r', encoding='utf-8') as f:
        history = json.load(f)
except FileNotFoundError:
    history = []

today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

# Prüfen, ob für heute bereits eine Farbe existiert
if history and history[-1].get("date") == today_str:
    latest_entry = history[-1]
    print(f"Using existing color for today: {latest_entry['name']} ({latest_entry['hex']})")
else:
    day_number = len(history) + 1
    r = random.randint(0, 255)
    g = random.randint(0, 255)
    b = random.randint(0, 255)
    hex_code = f"#{r:02X}{g:02X}{b:02X}"
    color_name = generate_color_name(r, g, b)

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

# Bluesky Posting Logic
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
        access_jwt = session["accessJwt"]
        did = session["did"]

        # Quadratisches Bild (1080x1080) in der Tagesfarbe erzeugen
        print("Generating color image...")
        img = Image.new("RGB", (1080, 1080), tuple(latest_entry["rgb"]))
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='JPEG', quality=90)
        img_bytes = img_byte_arr.getvalue()

        # Bild als Blob zu Bluesky hochladen
        print("Uploading image blob to Bluesky...")
        headers = {
            "Authorization": f"Bearer {access_jwt}",
            "Content-Type": "image/jpeg"
        }
        blob_res = requests.post("https://bsky.social/xrpc/com.atproto.repo.uploadBlob", headers=headers, data=img_bytes)
        blob_res.raise_for_status()
        blob_data = blob_res.json()["blob"]

        # Post-Text zusammenstellen
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
            "Authorization": f"Bearer {access_jwt}",
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
