"""a color a day – erzeugt die Tagesfarbe und veröffentlicht sie.

Ablauf bei jedem Lauf (er darf beliebig oft laufen, nichts wird doppelt gemacht):
1. Gibt es für heute (UTC) schon eine Farbe? Wenn nicht, wird sie erzeugt (colors.json).
2. Pinterest-Material wird aktualisiert (feed.xml, pins/, latest.png).
3. Für Bluesky und Mastodon wird nachgesehen, welche Tage noch nicht veröffentlicht sind
   (Merkzettel posted.json plus Gegenprobe auf dem jeweiligen Konto) und diese werden gepostet.
"""
import colorsys
import io
import json
import os
import random
import re
import time
from datetime import datetime, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape

import requests
from PIL import Image

# ----------------------------------------------------------------------------
# Einstellungen
# ----------------------------------------------------------------------------
SITE_URL = "https://a-color-a-day.github.io/infinity/"
QUOTE = "One small splash of color per day – for eternity."

# Hashtags unter jedem Post (ohne #). Reihenfolge = Reihenfolge im Post.
HASHTAGS = ["ColorOfTheDay", "Color", "Farbe", "GenerativeArt"]

# Frühestens um diese Uhrzeit (UTC) wird die Farbe des heutigen Tages gepostet.
# 12 Uhr UTC = 13/14 Uhr in Deutschland, morgens an der US-Ostküste, abends in Asien.
POST_HOUR_UTC = 12

# Wie genau muss ein bekannter Farbname zur Farbe passen?
# 0   = nur exakt derselbe Hex-Code (trifft nur etwa alle 1,5 Jahre)
# 1.0 = für das Auge nicht unterscheidbar (trifft etwa jeden 10. Tag)  <- Standard
# 2.0 = kaum unterscheidbar (trifft etwa jeden 2. Tag)
NAME_MATCH_TOLERANCE = 1.0

# So viele der neuesten Tage stehen im Pinterest-Feed.
FEED_ITEMS = 50

BLUESKY_SERVICE = os.environ.get("BLUESKY_SERVICE", "https://bsky.social").rstrip("/")

DAY_RE = re.compile(r"Day (\d{5}) /")
POSTED_FILE = "posted.json"


# ----------------------------------------------------------------------------
# Farbnamen
# ----------------------------------------------------------------------------
_database_cache = None
_named_labs_cache = None


def load_color_database():
    """Lädt die Farbnamen-Datenbank (color_database.json, Hex-Code -> Name)."""
    global _database_cache
    if _database_cache is None:
        try:
            with open('color_database.json', 'r', encoding='utf-8') as f:
                _database_cache = json.load(f)
        except FileNotFoundError:
            _database_cache = {}
    return _database_cache


def srgb_to_lab(r, g, b):
    """Rechnet eine RGB-Farbe in den Lab-Farbraum um, in dem Abstände dem Seheindruck entsprechen."""
    def lin(v):
        v /= 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    rl, gl, bl = lin(r), lin(g), lin(b)
    x = (0.4124564 * rl + 0.3575761 * gl + 0.1804375 * bl) / 0.95047
    y = (0.2126729 * rl + 0.7151522 * gl + 0.0721750 * bl)
    z = (0.0193339 * rl + 0.1191920 * gl + 0.9503041 * bl) / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def named_labs():
    global _named_labs_cache
    if _named_labs_cache is None:
        _named_labs_cache = []
        for hex_key, name in load_color_database().items():
            h = hex_key.lstrip('#')
            rgb = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
            _named_labs_cache.append((srgb_to_lab(*rgb), name))
    return _named_labs_cache


def lookup_universal_name(r, g, b, hex_code):
    """Gibt den bekannten Farbnamen zurück, falls es einen passenden gibt, sonst None."""
    db = load_color_database()
    exact = db.get(hex_code.lower())
    if exact:
        return exact
    if NAME_MATCH_TOLERANCE <= 0 or not db:
        return None
    L, a, bb = srgb_to_lab(r, g, b)
    best_name, best_d2 = None, None
    for (l2, a2, b2), name in named_labs():
        d2 = (L - l2) ** 2 + (a - a2) ** 2 + (bb - b2) ** 2
        if best_d2 is None or d2 < best_d2:
            best_name, best_d2 = name, d2
    if best_d2 is not None and best_d2 <= NAME_MATCH_TOLERANCE ** 2:
        return best_name
    return None


def title_case(name):
    """Jedes Wort mit Großbuchstaben beginnen: 'Deep-sea purple' -> 'Deep-sea Purple'."""
    return " ".join(w[:1].upper() + w[1:] for w in name.split(" "))


def generate_color_name(r, g, b, hex_code):
    # 1. Gibt es schon einen bekannten Namen für diese Farbe? Dann wird er verwendet.
    known = lookup_universal_name(r, g, b, hex_code)
    if known:
        return known

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

    return title_case(f"{mod} {base}")


# ----------------------------------------------------------------------------
# Tagesfarbe
# ----------------------------------------------------------------------------
def load_history():
    try:
        with open('colors.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def ensure_today(history, today_str):
    """Stellt sicher, dass es einen Eintrag für heute gibt. Gibt (eintrag, ist_neu) zurück."""
    if history and history[-1].get("date") == today_str:
        entry = history[-1]
        print(f"Using existing color for today: {entry['name']} ({entry['hex']})")
        return entry, False

    day_number = max((e.get("day", 0) for e in history), default=0) + 1

    # Jede Farbe kommt nur einmal vor: bereits gezeigte Farben werden übersprungen
    used_hex = {e.get("hex", "").upper() for e in history}
    while True:
        r = random.randint(0, 255)
        g = random.randint(0, 255)
        b = random.randint(0, 255)
        hex_code = f"#{r:02X}{g:02X}{b:02X}"
        if hex_code not in used_hex:
            break

    color_name = generate_color_name(r, g, b, hex_code)
    entry = {
        "day": day_number,
        "date": today_str,
        "hex": hex_code,
        "rgb": [r, g, b],
        "name": color_name
    }
    history.append(entry)
    with open('colors.json', 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=2, ensure_ascii=False)
    print(f"Generated Day {day_number}: {color_name} ({hex_code})")
    return entry, True


# ----------------------------------------------------------------------------
# Bilder, Texte
# ----------------------------------------------------------------------------
def png_bytes(rgb, size):
    img = Image.new("RGB", size, tuple(rgb))
    buf = io.BytesIO()
    # PNG statt JPEG: verlustfrei, damit die Farbe exakt bleibt
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def entry_url(day):
    return f"{SITE_URL}#{day}"


def alt_text(entry):
    r, g, b = entry["rgb"]
    return f"Flat color field: {entry['name']}, {entry['hex']}, RGB ({r}, {g}, {b})"


def build_post_text(entry, with_quote=True):
    r, g, b = entry["rgb"]
    lines = [
        f"Day {str(entry['day']).zfill(5)} / 16,777,216",
        entry["name"],
        f"{entry['hex']} • RGB ({r}, {g}, {b})",
        "",
    ]
    if with_quote:
        lines += [f"\"{QUOTE}\"", ""]
    lines += [entry_url(entry["day"]), "", " ".join("#" + t for t in HASHTAGS)]
    return "\n".join(lines)


def bsky_facets(text, url):
    """Macht Link und Hashtags im Bluesky-Post anklickbar (Bluesky rechnet in Bytes)."""
    facets = []
    raw = text.encode("utf-8")
    start = raw.find(url.encode("utf-8"))
    if start >= 0:
        facets.append({
            "index": {"byteStart": start, "byteEnd": start + len(url.encode("utf-8"))},
            "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}]
        })
    for tag in HASHTAGS:
        for m in re.finditer(r"(?<![\w#])#" + re.escape(tag) + r"(?!\w)", text):
            facets.append({
                "index": {
                    "byteStart": len(text[:m.start()].encode("utf-8")),
                    "byteEnd": len(text[:m.end()].encode("utf-8")),
                },
                "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": tag}]
            })
    return facets


# ----------------------------------------------------------------------------
# Pinterest-Material: Bilder (2:3) und RSS-Feed
# ----------------------------------------------------------------------------
def update_pinterest_files(history):
    os.makedirs("pins", exist_ok=True)
    for e in history:
        path = f"pins/day-{int(e['day']):05d}.png"
        if not os.path.exists(path):
            with open(path, "wb") as f:
                f.write(png_bytes(e["rgb"], (1000, 1500)))

    newest = max(history, key=lambda e: e["day"])
    # Vorschaubild für Link-Vorschauen (WhatsApp, Slack, Messenger ...)
    with open("latest.png", "wb") as f:
        f.write(png_bytes(newest["rgb"], (1200, 630)))

    items = sorted(history, key=lambda e: e["day"], reverse=True)[:FEED_ITEMS]

    def pub_date(e):
        dt = datetime.strptime(e["date"], "%Y-%m-%d").replace(hour=POST_HOUR_UTC, tzinfo=timezone.utc)
        return format_datetime(dt)

    tags = " ".join("#" + t for t in HASHTAGS)
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/" xmlns:atom="http://www.w3.org/2005/Atom">',
        '<channel>',
        '<title>a color a day</title>',
        f'<link>{escape(SITE_URL)}</link>',
        '<description>One small splash of color per day – for eternity.</description>',
        f'<atom:link href="{escape(SITE_URL)}feed.xml" rel="self" type="application/rss+xml"/>',
        f'<lastBuildDate>{pub_date(newest)}</lastBuildDate>',
    ]
    for e in items:
        r, g, b = e["rgb"]
        img_rel = f"pins/day-{int(e['day']):05d}.png"
        img_url = SITE_URL + img_rel
        size = os.path.getsize(img_rel)
        title = f"Day {str(e['day']).zfill(5)}: {e['name']}"[:100]
        desc = f"{e['name']} – {e['hex']} – RGB ({r}, {g}, {b}). {QUOTE} {tags}"
        parts += [
            '<item>',
            f'<title>{escape(title)}</title>',
            f'<link>{escape(entry_url(e["day"]))}</link>',
            f'<guid isPermaLink="false">acolorday-{int(e["day"])}</guid>',
            f'<pubDate>{pub_date(e)}</pubDate>',
            f'<description>{escape(desc)}</description>',
            f'<enclosure url="{escape(img_url)}" length="{size}" type="image/png"/>',
            f'<media:content url="{escape(img_url)}" medium="image" type="image/png" width="1000" height="1500"/>',
            '</item>',
        ]
    parts += ['</channel>', '</rss>', '']
    with open("feed.xml", "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
    print(f"Pinterest feed updated ({len(items)} items).")


# ----------------------------------------------------------------------------
# Merkzettel: was wurde wo schon gepostet?
# ----------------------------------------------------------------------------
def load_posted():
    try:
        with open(POSTED_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}
    for key in ("bluesky", "mastodon"):
        data.setdefault(key, [])
    return data


def save_posted(posted):
    for key in posted:
        posted[key] = sorted(set(posted[key]))
    with open(POSTED_FILE, "w", encoding="utf-8") as f:
        json.dump(posted, f, indent=2)


def is_due(entry, now, post_now):
    """Darf dieser Tag jetzt gepostet werden? Frühere Tage immer, der heutige erst ab POST_HOUR_UTC."""
    if post_now:
        return True
    today = now.strftime("%Y-%m-%d")
    date = entry.get("date", "")
    if date < today:
        return True
    if date == today:
        return now.hour >= POST_HOUR_UTC
    return False


# ----------------------------------------------------------------------------
# Bluesky
# ----------------------------------------------------------------------------
def bluesky_existing_days(headers, did):
    """Liest die letzten Posts des Kontos und liefert die Tage, die schon veröffentlicht sind."""
    days, cursor = set(), None
    for _ in range(3):
        params = {"actor": did, "limit": 100, "filter": "posts_no_replies"}
        if cursor:
            params["cursor"] = cursor
        res = requests.get(f"{BLUESKY_SERVICE}/xrpc/app.bsky.feed.getAuthorFeed",
                           headers=headers, params=params, timeout=30)
        res.raise_for_status()
        data = res.json()
        for item in data.get("feed", []):
            text = item.get("post", {}).get("record", {}).get("text", "")
            for m in DAY_RE.finditer(text):
                days.add(int(m.group(1)))
        cursor = data.get("cursor")
        if not cursor:
            break
    return days


def post_to_bluesky(pending, posted, today_str):
    handle = os.environ.get("BLUESKY_HANDLE")
    password = os.environ.get("BLUESKY_PASSWORD")
    if not (handle and password):
        print("Bluesky: credentials not found - skipped.")
        return
    if not pending:
        print("Bluesky: nothing to post.")
        return

    print("Bluesky: logging in...")
    res = requests.post(f"{BLUESKY_SERVICE}/xrpc/com.atproto.server.createSession",
                        json={"identifier": handle, "password": password}, timeout=30)
    res.raise_for_status()
    session = res.json()
    auth = {"Authorization": f"Bearer {session['accessJwt']}"}
    did = session["did"]

    existing = bluesky_existing_days(auth, did)

    for entry in pending:
        day = int(entry["day"])
        if day in existing:
            print(f"Bluesky: Day {day} already on the account - marking as done.")
            posted["bluesky"].append(day)
            save_posted(posted)
            continue

        blob_res = requests.post(f"{BLUESKY_SERVICE}/xrpc/com.atproto.repo.uploadBlob",
                                 headers={**auth, "Content-Type": "image/png"},
                                 data=png_bytes(entry["rgb"], (1080, 1080)), timeout=60)
        blob_res.raise_for_status()
        blob = blob_res.json()["blob"]

        text = build_post_text(entry)
        if len(text) > 295:  # Bluesky erlaubt 300 Zeichen
            text = build_post_text(entry, with_quote=False)

        # Nachgeholte Tage bekommen das Datum ihres eigenen Tages, damit die Reihenfolge stimmt
        if entry.get("date", today_str) < today_str:
            created_at = f"{entry['date']}T{POST_HOUR_UTC:02d}:00:00.000Z"
        else:
            created_at = datetime.now(timezone.utc).isoformat()

        record = {
            "$type": "app.bsky.feed.post",
            "text": text,
            "createdAt": created_at,
            "langs": ["en"],
            "facets": bsky_facets(text, entry_url(day)),
            "embed": {
                "$type": "app.bsky.embed.images",
                "images": [{"alt": alt_text(entry), "image": blob}]
            }
        }
        post_res = requests.post(f"{BLUESKY_SERVICE}/xrpc/com.atproto.repo.createRecord",
                                 headers={**auth, "Content-Type": "application/json"},
                                 json={"repo": did, "collection": "app.bsky.feed.post", "record": record},
                                 timeout=30)
        post_res.raise_for_status()
        print(f"Bluesky: posted Day {day}.")
        posted["bluesky"].append(day)
        save_posted(posted)


# ----------------------------------------------------------------------------
# Mastodon
# ----------------------------------------------------------------------------
def mastodon_base():
    inst = os.environ.get("MASTODON_INSTANCE", "").strip().rstrip("/")
    if inst and not inst.startswith("http"):
        inst = "https://" + inst
    return inst


def mastodon_existing_days(base, headers, account_id):
    days, max_id = set(), None
    for _ in range(5):
        params = {"limit": 40, "exclude_replies": "true", "exclude_reblogs": "true"}
        if max_id:
            params["max_id"] = max_id
        res = requests.get(f"{base}/api/v1/accounts/{account_id}/statuses",
                           headers=headers, params=params, timeout=30)
        res.raise_for_status()
        statuses = res.json()
        if not statuses:
            break
        for st in statuses:
            plain = re.sub(r"<[^>]+>", " ", st.get("content", ""))
            for m in DAY_RE.finditer(plain):
                days.add(int(m.group(1)))
        max_id = statuses[-1]["id"]
    return days


def post_to_mastodon(pending, posted):
    base = mastodon_base()
    token = os.environ.get("MASTODON_ACCESS_TOKEN", "").strip()
    if not (base and token):
        print("Mastodon: credentials not found - skipped.")
        return
    if not pending:
        print("Mastodon: nothing to post.")
        return

    headers = {"Authorization": f"Bearer {token}"}
    me = requests.get(f"{base}/api/v1/accounts/verify_credentials", headers=headers, timeout=30)
    me.raise_for_status()
    account_id = me.json()["id"]
    print(f"Mastodon: logged in as {me.json().get('acct', account_id)}.")

    existing = mastodon_existing_days(base, headers, account_id)

    for entry in pending:
        day = int(entry["day"])
        if day in existing:
            print(f"Mastodon: Day {day} already on the account - marking as done.")
            posted["mastodon"].append(day)
            save_posted(posted)
            continue

        media = requests.post(f"{base}/api/v2/media", headers=headers,
                              files={"file": (f"day-{day:05d}.png", png_bytes(entry["rgb"], (1080, 1080)), "image/png")},
                              data={"description": alt_text(entry)}, timeout=60)
        media.raise_for_status()
        media_id = media.json()["id"]
        if media.status_code == 202:  # Mastodon verarbeitet das Bild noch
            for _ in range(15):
                time.sleep(2)
                check = requests.get(f"{base}/api/v1/media/{media_id}", headers=headers, timeout=30)
                if check.status_code == 200:
                    break
                check.raise_for_status()

        status = requests.post(f"{base}/api/v1/statuses",
                               headers={**headers, "Idempotency-Key": f"acolorday-{day}"},
                               json={"status": build_post_text(entry), "media_ids": [media_id],
                                     "visibility": "public", "language": "en"},
                               timeout=30)
        status.raise_for_status()
        print(f"Mastodon: posted Day {day}.")
        posted["mastodon"].append(day)
        save_posted(posted)
        time.sleep(1)


# ----------------------------------------------------------------------------
# Hauptprogramm
# ----------------------------------------------------------------------------
def main():
    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")
    post_now = os.environ.get("POST_NOW", "").strip().lower() in ("1", "true", "yes")

    history = load_history()
    ensure_today(history, today_str)
    update_pinterest_files(history)

    posted = load_posted()
    save_posted(posted)

    ordered = sorted(history, key=lambda e: e["day"])
    for platform, func in (("bluesky", lambda p: post_to_bluesky(p, posted, today_str)),
                           ("mastodon", lambda p: post_to_mastodon(p, posted))):
        pending = [e for e in ordered
                   if int(e["day"]) not in posted[platform] and is_due(e, now, post_now)]
        waiting = [e for e in ordered
                   if int(e["day"]) not in posted[platform] and not is_due(e, now, post_now)]
        if waiting:
            print(f"{platform}: Day {waiting[0]['day']} waits until {POST_HOUR_UTC:02d}:00 UTC.")
        try:
            func(pending)
        except Exception as e:  # Ein Fehler bei einem Netzwerk darf die anderen nicht stoppen
            print(f"Error with {platform} (will retry next run): {e}")


if __name__ == "__main__":
    main()
