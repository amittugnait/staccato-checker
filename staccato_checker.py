"""
Staccato California-Compliant CPO Stock Checker
Checks HD C3.6, HD P4, and HD C4X for "Compliant Preferred Package" availability
and sends an email alert when any are found in stock.

Required environment variables (set in Replit Secrets):
  GMAIL_ADDRESS   - your Gmail address (sender + recipient)
  GMAIL_APP_PASSWORD - your Gmail App Password (NOT your regular password)
"""

import urllib.request
import json
import smtplib
import os
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# ── Products to monitor ───────────────────────────────────────────────────────
PRODUCTS = [
    {
        "label": "Staccato HD C3.6",
        "slug": "staccato-hd-c3-6-certified-pre-owned-handgun",
        "url": "https://staccato2011.com/products/staccato-hd-c3-6-certified-pre-owned-handgun",
    },
    {
        "label": "Staccato HD P4",
        "slug": "staccato-hd-p4-certified-pre-owned-handgun",
        "url": "https://staccato2011.com/products/staccato-hd-p4-certified-pre-owned-handgun",
    },
    {
        "label": "Staccato HD C4X",
        "slug": "staccato-hd-c4x-certified-pre-owned-handgun",
        "url": "https://staccato2011.com/products/staccato-hd-c4x-certified-pre-owned-handgun",
    },
]

# Keywords that identify a California-compliant variant (case-insensitive)
COMPLIANT_KEYWORDS = ["compliant preferred", "state compliant preferred"]

# How often to check (in seconds). 120 = every 2 minutes.
# On non-Wednesday days this doesn't matter much; the schedule logic below
# limits active checking to Wednesday mornings only.
CHECK_INTERVAL_SECONDS = 120

# Wednesday drop window in Pacific time (UTC-7 in summer / PDT)
# We check from 6:45 AM to 7:30 AM PT  →  13:45–14:30 UTC
WINDOW_START_UTC_HOUR = 13
WINDOW_START_UTC_MIN  = 45
WINDOW_END_UTC_HOUR   = 14
WINDOW_END_UTC_MIN    = 30


# ── Email ─────────────────────────────────────────────────────────────────────
def send_email(subject, body_html, body_text):
    gmail_address    = os.environ["GMAIL_ADDRESS"]
    gmail_app_password = os.environ["GMAIL_APP_PASSWORD"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = gmail_address
    msg["To"]      = gmail_address

    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_address, gmail_app_password)
        server.sendmail(gmail_address, gmail_address, msg.as_string())

    print(f"  📧 Email sent: {subject}")


# ── Stock checking ────────────────────────────────────────────────────────────
def fetch_product_json(slug):
    url = f"https://staccato2011.com/products/{slug}.json"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def find_compliant_variants(data, product):
    """Return list of available compliant variant dicts."""
    found = []
    variants = data.get("product", {}).get("variants", [])

    for v in variants:
        option_values = v.get("option_values", [])
        all_labels = " ".join(o.get("label", "").lower() for o in option_values)

        is_compliant = any(kw in all_labels for kw in COMPLIANT_KEYWORDS)
        if not is_compliant:
            continue

        # A variant is purchasable when purchasing_disabled is False
        # and either inventory > 0 or inventory tracking is off
        purchasing_disabled = v.get("purchasing_disabled", True)
        inventory_level     = v.get("inventory_level", 0)
        inventory_tracking  = v.get("inventory_tracking", "none")

        in_stock = (
            not purchasing_disabled
            and (inventory_level > 0 or inventory_tracking == "none")
        )

        config_label = next(
            (o["label"] for o in option_values
             if "config" in o.get("option_display_name", "").lower()
             or "package" in o.get("option_display_name", "").lower()),
            all_labels
        )
        condition_label = next(
            (o["label"] for o in option_values
             if "condition" in o.get("option_display_name", "").lower()),
            ""
        )
        price = v.get("price")
        price_str = f"${float(price):,.2f}" if price else "See site"

        found.append({
            "label":     product["label"],
            "config":    config_label,
            "condition": condition_label,
            "price":     price_str,
            "in_stock":  in_stock,
            "url":       product["url"],
        })

    return found


def check_all_products():
    """Returns list of available compliant variants across all products."""
    available = []
    for product in PRODUCTS:
        try:
            data     = fetch_product_json(product["slug"])
            variants = find_compliant_variants(data, product)
            in_stock = [v for v in variants if v["in_stock"]]
            sold_out = [v for v in variants if not v["in_stock"]]

            if in_stock:
                print(f"  ✅ {product['label']}: {len(in_stock)} available")
                available.extend(in_stock)
            elif sold_out:
                print(f"  ❌ {product['label']}: compliant variant found but sold out ({sold_out[0]['price']})")
            else:
                print(f"  ⚠️  {product['label']}: no compliant variant detected in API")

        except Exception as e:
            print(f"  ⚠️  {product['label']}: error — {e}")

    return available


# ── Email formatting ──────────────────────────────────────────────────────────
def build_email(available_variants):
    now = datetime.utcnow().strftime("%I:%M %p UTC")
    subject = f"🟢 Staccato CA Stock Alert — {len(available_variants)} item(s) available!"

    rows_html = ""
    rows_text = ""
    for v in available_variants:
        rows_html += f"""
        <tr>
          <td style="padding:10px 14px; border-bottom:1px solid #eee;"><strong>{v['label']}</strong></td>
          <td style="padding:10px 14px; border-bottom:1px solid #eee;">{v['config']}</td>
          <td style="padding:10px 14px; border-bottom:1px solid #eee;">{v.get('condition','')}</td>
          <td style="padding:10px 14px; border-bottom:1px solid #eee; font-weight:bold;">{v['price']}</td>
          <td style="padding:10px 14px; border-bottom:1px solid #eee;">
            <a href="{v['url']}" style="background:#1a7f4b;color:#fff;padding:6px 12px;border-radius:4px;text-decoration:none;font-size:13px;">Buy now →</a>
          </td>
        </tr>"""
        rows_text += f"  • {v['label']} | {v['config']} | {v.get('condition','')} | {v['price']}\n    {v['url']}\n\n"

    body_html = f"""
    <div style="font-family:sans-serif; max-width:620px; margin:0 auto; padding:24px;">
      <h2 style="color:#1a7f4b; margin-bottom:4px;">🟢 Staccato CA Stock Alert</h2>
      <p style="color:#666; font-size:13px; margin-top:0;">Checked at {now} · These sell fast!</p>
      <table style="width:100%; border-collapse:collapse; font-size:14px; margin-top:16px;">
        <thead>
          <tr style="background:#f5f5f5;">
            <th style="padding:10px 14px; text-align:left;">Model</th>
            <th style="padding:10px 14px; text-align:left;">Configuration</th>
            <th style="padding:10px 14px; text-align:left;">Condition</th>
            <th style="padding:10px 14px; text-align:left;">Price</th>
            <th style="padding:10px 14px; text-align:left;"></th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>
      <p style="margin-top:20px; font-size:12px; color:#999;">
        Staccato CPO page: <a href="https://staccato2011.com/shop/handguns/certified-pre-owned-handguns">staccato2011.com</a>
      </p>
    </div>"""

    body_text = f"STACCATO CA STOCK ALERT — {now}\n\n{rows_text}\nFull CPO page: https://staccato2011.com/shop/handguns/certified-pre-owned-handguns"

    return subject, body_html, body_text


# ── Schedule logic ────────────────────────────────────────────────────────────
def is_wednesday_window():
    """True if it's Wednesday and within the active check window (UTC)."""
    now = datetime.utcnow()
    if now.weekday() != 2:  # 2 = Wednesday
        return False
    start = now.replace(hour=WINDOW_START_UTC_HOUR, minute=WINDOW_START_UTC_MIN, second=0)
    end   = now.replace(hour=WINDOW_END_UTC_HOUR,   minute=WINDOW_END_UTC_MIN,   second=0)
    return start <= now <= end


def seconds_until_next_window():
    """How many seconds until next Wednesday 6:45 AM PT window opens."""
    from datetime import timedelta
    now = datetime.utcnow()
    days_ahead = (2 - now.weekday()) % 7  # days until Wednesday
    if days_ahead == 0:
        # It's Wednesday — check if window already passed today
        end = now.replace(hour=WINDOW_END_UTC_HOUR, minute=WINDOW_END_UTC_MIN, second=0)
        if now > end:
            days_ahead = 7  # next Wednesday
    next_wed = (now + timedelta(days=days_ahead)).replace(
        hour=WINDOW_START_UTC_HOUR, minute=WINDOW_START_UTC_MIN, second=0, microsecond=0
    )
    return max(0, int((next_wed - now).total_seconds()))


# ── Main loop ─────────────────────────────────────────────────────────────────
def main():
    print("🔍 Staccato CA Stock Checker started")
    print(f"   Monitoring: HD C3.6, HD P4, HD C4X (Compliant Preferred Package)")
    print(f"   Active window: Wednesdays 6:45–7:30 AM PT")
    print(f"   Check interval: every {CHECK_INTERVAL_SECONDS // 60} minutes during window\n")

    alerted_this_session = set()  # avoid spamming duplicate emails

    while True:
        now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

        if not is_wednesday_window():
            secs = seconds_until_next_window()
            hrs  = secs // 3600
            mins = (secs % 3600) // 60
            print(f"[{now_str}] Outside window — sleeping {hrs}h {mins}m until next Wednesday drop window...")
            # Sleep in 60-second chunks so we don't miss the window by much
            sleep_chunk = min(secs, 60)
            time.sleep(sleep_chunk)
            continue

        print(f"[{now_str}] 🟡 In drop window — checking...")
        available = check_all_products()

        new_available = [v for v in available if v["config"] not in alerted_this_session]

        if new_available:
            subject, body_html, body_text = build_email(new_available)
            try:
                send_email(subject, body_html, body_text)
                for v in new_available:
                    alerted_this_session.add(v["config"])
            except Exception as e:
                print(f"  ⚠️  Email failed: {e}")
        else:
            print(f"  Nothing available yet.")

        print(f"  Sleeping {CHECK_INTERVAL_SECONDS}s...\n")
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
