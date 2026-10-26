import json
import random
from datetime import datetime, timezone
import os
import requests
from PIL import Image
import io
import colorsys

def generate_color_name(r, g, b):
    # Konvertiere RGB in HLS (Hue, Lightness, Saturation) für präzise Zuordnung
    rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
    h, l, s = colorsys.rgb_to_hls(rf, gf, bf)
    hue = h * 360

    # Poetische Modifikatoren basierend auf Helligkeit und Sättigung
    if l < 0.22:
        light_mod = ["Deep-sea", "Midnight", "Abyss", "Shadows", "Obsidian"]
    elif l > 0.78:
        light_mod = ["Mist", "Whisper", "Dawn", "Glow", "Haze"]
    elif s < 0.18:
        light_mod = ["Muted", "Silent", "Dust", "Faded", "Soft"]
    else:
        light_mod = ["Radiant", "Vivid", "Ethereal", "Pure", "Luminous"]

    # Poetische Basisnamen basierend auf dem Farbkreis (Hue 0-360°)
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

    # Wähle basierend auf den RGB-Werten deterministisch aus den Listen aus, damit es konsistent bleibt
    mod = light_mod[(r + g) % len(light_mod)]
    base = base_names[(g + b) % len(base_names)]

    # Verbinde sie elegant mit Bindestrich oder Leerzeichen
    return f"{mod} {base}"

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
        session_res.raise
