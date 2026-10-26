import json
import random
from datetime import datetime, timezone
import os
import requests
from PIL import Image
import io
import colorsys

SITE_URL = "https://a-color-a-day.github.io/infinity/"

def load_color_database():
    """Lädt optional eine lokale Farbdatenbank (z.B. color_database.json)"""
    try:
        with open('color_database.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def title_case(name):
    """Jedes Wort mit Großbuchstaben beginnen: 'Deep-sea purple' -> 'Deep-sea Purple'."""
    return " ".join(w[:1].upper() + w[1:] for w in name.split(" "))

def generate_color_name(r, g, b, hex_code):
    color_db = load_color_database()
    hex_lower = hex_code.lower()
    if hex_lower in color_db:
        return title_case(color_db[hex_lower])

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

    return title_case(f"{mod} {base}")

def link_facets(text, url):
    raw = text.encode("utf-8")
    start = raw.find(url.encode("utf-8"))
    if start < 0:
        return []
    return [{
        "index": {"byteStart": start, "byteEnd": start + len(url.encode("utf-8"))},
        "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}]
    }]

try:
    with open('colors.json', 'r', encoding='utf-8') as f:
        history = json.load(f)
except FileNotFoundError:
    history = []

today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

# 1. Prüfen, ob für heute bereits eine Farbe in der History existiert. Wenn nicht, generieren.
if not history or history[-1].get("date") != today_str:
    day_number = max((e.get("day", 0) for e in history), default=0) + 1

    used_hex = {e.get("hex", "").upper() for e in history}
    while True:
        r = random.randint(0, 255)
        g = random.randint(0, 255)
        b = random.randint(0, 255)
        hex_code = f"#{r:02X}{g:02X}{b:02X}"
        if hex_code not in used_hex:
            break

    color_name = generate_color_name(r, g, b, hex_code)

    new_entry = {
        "day": day_number,
        "date": today_str,
        "hex": hex_code,
        "rgb": [r, g, b],
        "name": color_name,
        "posted_bluesky": False,
        "posted_mastodon": False
    }
    history.append(new_entry)
    print(f"Generated Day {day_number}: {color_name} ({hex_code})")

# 2. Sicherstellen, dass ältere Einträge die Status-Flags besitzen.
# Da Bluesky bei dir bereits läuft, setzen wir 'posted_bluesky' für alte Einträge auf True.
# Da Mastodon neu ist, lassen wir 'posted_mastodon' für Tag 1 & 2 auf False, damit sie dort nachgeholt werden!
for entry in history:
    if "posted_bluesky" not in entry:
        entry["posted_bluesky"] = True
    if "posted_mastodon" not in entry:
        entry["posted_mastodon"] = False

# Credentials einlesen
bsky_handle = os.environ.get("BLUESKY_HANDLE")
bsky_password = os.environ.get("BLUESKY_PASSWORD")
mastodon_token = os.environ.get("MASTODON_ACCESS_TOKEN")
mastodon_url = os.environ.get("MASTODON_API_BASE_URL")

# Bluesky Session vorbereiten (falls Zugangsdaten da sind)
bluesky_session = None
if bsky_handle and bsky_password:
    try:
        print("Logging in to Bluesky...")
        session_res = requests.post("https://bsky.social/xrpc/com.atproto.server.createSession", json={
            "identifier": bsky_handle,
            "password": bsky_password
        }, timeout=30)
        session_res.raise_for_status()
        bluesky_session = session_res.json()
    except Exception as e:
        print(f"Bluesky Login Error: {e}")

# 3. Alle Einträge durchgehen und fehlende Posts (inklusive Nachholen für Mastodon ab Tag 1) ausführen
updated = False

for entry in history:
    day_str = str(entry['day']).zfill(5)
    r, g, b = entry['rgb']
    hex_code = entry['hex']
    name = entry['name']
    
    text = (
        f"Day {day_str} / 16,777,216\n"
        f"{name}\n"
        f"{hex_code} • RGB ({r}, {g}, {b})\n\n"
        f"\"One small splash of color per day – for eternity.\"\n\n"
        f"{SITE_URL}"
    )

    # Bild für diesen Eintrag verlustfrei im Speicher erzeugen
    img = Image.new("RGB", (1080, 1080), (r, g, b))
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG', optimize=True)
    img_bytes = img_byte_arr.getvalue()

    # --- BLUESKY ---
    if bsky_handle and bsky_password and bluesky_session and not entry.get("posted_bluesky", False):
        try:
            print(f"Posting Day {entry['day']} to Bluesky...")
            access_token = bluesky_session["accessJwt"]
            did = bluesky_session["did"]

            headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "image/png"}
            blob_res = requests.post("https://bsky.social/xrpc/com.atproto.repo.uploadBlob", headers=headers, data=img_bytes, timeout=60)
            blob_res.raise_for_status()
            blob_data = blob_res.json()["blob"]

            post_record = {
                "$type": "app.bsky.feed.post",
                "text": text,
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "facets": link_facets(text, SITE_URL),
                "embed": {
                    "$type": "app.bsky.embed.images",
                    "images": [{"alt": f"{name} ({hex_code})", "image": blob_data}]
                }
            }

            post_res = requests.post("https://bsky.social/xrpc/com.atproto.repo.createRecord", headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }, json={
                "repo": did,
                "collection": "app.bsky.feed.post",
                "record": post_record
            }, timeout=30)
            post_res.raise_for_status()
            
            entry["posted_bluesky"] = True
            updated = True
            print(f"Successfully posted Day {entry['day']} to Bluesky!")
        except Exception as e:
            print(f"Error posting Day {entry['day']} to Bluesky: {e}")

    # --- MASTODON (holt Tag 1 & 2 nach) ---
    if mastodon_token and mastodon_url and not entry.get("posted_mastodon", False):
        try:
            print(f"Posting Day {entry['day']} to Mastodon...")
            media_headers = {"Authorization": f"Bearer {mastodon_token}"}
            files = {"file": ("color.png", img_bytes, "image/png")}
            media_res = requests.post(f"{mastodon_url}/api/v1/media", headers=media_headers, files=files, timeout=60)
            media_res.raise_for_status()
            media_id = media_res.json()["id"]

            status_data = {
                "status": text,
                "media_ids": [media_id]
            }
            status_res = requests.post(f"{mastodon_url}/api/v1/statuses", headers=media_headers, json=status_data, timeout=30)
            status_res.raise_for_status()
            
            entry["posted_mastodon"] = True
            updated = True
            print(f"Successfully posted Day {entry['day']} to Mastodon!")
        except Exception as e:
            print(f"Error posting Day {entry['day']} to Mastodon: {e}")

# 4. History und Post-Status in colors.json speichern
if updated:
    with open('colors.json', 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=2, ensure_ascii=False)
    print("colors.json and post statuses updated successfully.")
