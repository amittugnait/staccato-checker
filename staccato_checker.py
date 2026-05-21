"""
Staccato California-Compliant CPO Stock Checker
Designed for GitHub Actions - runs once, checks stock, emails if found, then exits.

Required environment variables (GitHub Secrets):
  GMAIL_ADDRESS      - your Gmail address
  GMAIL_APP_PASSWORD - your Gmail App Password (16-char, not your real password)
"""

import urllib.request
import json
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone

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

COMPLIANT_KEYWORDS = ["compliant preferred", "state compliant preferred"]


def fetch_product_json(slug):
    url = f"https://staccato2011.com/products/{slug}.json"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def find_available_compliant_variants(data, product):
    found = []
    variants = data.get("product", {}).get("variants", [])

    for v in variants:
        option_values = v.get("option_values", [])
        all_labels = " ".join(o.get("label", "").lower() for o in option_values)

        if not any(kw in all_labels for kw in COMPLIANT_KEYWORDS):
            continue

        purchasing_disabled = v.get("purchasing_disabled", True)
        inventory_level = v.get("inventory_level", 0)
        inventory_tracking = v.get("inventory_tracking", "none")

        in_stock = (
            not purchasing_disabled
            and (inventory_level > 0 or inventory_tracking == "none")
        )

        if not in_stock:
            price = v.get("price")
            price_str = f"${float(price):,.2f}" if price else "See site"
            print(f"  ❌ {product['label']}: compliant variant sold out ({price_str})")
            continue

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
            "label": product["label"],
            "config": config_label,
            "condition": condition_label,
            "price": price_str,
            "url": product["url"],
        })

    return found


def send_email(available):
    gmail_address = os.environ["GMAIL_ADDRESS"]
    gmail_app_password = os.environ["GMAIL_APP_PASSWORD"]
    now = datetime.now(timezone.utc).strftime("%I:%M %p UTC")

    subject = f"🟢 Staccato CA Alert — {len(available)} item(s) available now!"

    rows_html = ""
    rows_text = ""
    for v in available:
        rows_html += f"""
        <tr>
          <td style="padding:10px 14px;border-bottom:1px solid #eee;"><strong>{v['label']}</strong></td>
          <td style="padding:10px 14px;border-bottom:1px solid #eee;">{v['config']}</td>
          <td style="padding:10px 14px;border-bottom:1px solid #eee;">{v.get('condition','')}</td>
          <td style="padding:10px 14px;border-bottom:1px solid #eee;font-weight:bold;">{v['price']}</td>
          <td style="padding:10px 14px;border-bottom:1px solid #eee;">
            <a href="{v['url']}" style="background:#1a7f4b;color:#fff;padding:6px 12px;border-radius:4px;text-decoration:none;font-size:13px;">Buy now →</a>
          </td>
        </tr>"""
        rows_text += f"  • {v['label']} | {v['config']} | {v.get('condition','')} | {v['price']}\n    {v['url']}\n\n"

    body_html = f"""
    <div style="font-family:sans-serif;max-width:620px;margin:0 auto;padding:24px;">
      <h2 style="color:#1a7f4b;">🟢 Staccato CA Stock Alert</h2>
      <p style="color:#666;font-size:13px;">Checked at {now} · These sell fast — act quickly!</p>
      <table style="width:100%;border-collapse:collapse;font-size:14px;margin-top:16px;">
        <thead>
          <tr style="background:#f5f5f5;">
            <th style="padding:10px 14px;text-align:left;">Model</th>
            <th style="padding:10px 14px;text-align:left;">Configuration</th>
            <th style="padding:10px 14px;text-align:left;">Condition</th>
            <th style="padding:10px 14px;text-align:left;">Price</th>
            <th style="padding:10px 14px;text-align:left;"></th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>
      <p style="margin-top:20px;font-size:12px;color:#999;">
        Full CPO page: <a href="https://staccato2011.com/shop/handguns/certified-pre-owned-handguns">staccato2011.com</a>
      </p>
    </div>"""

    body_text = f"STACCATO CA STOCK ALERT — {now}\n\n{rows_text}\nFull CPO page: https://staccato2011.com/shop/handguns/certified-pre-owned-handguns"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_address
    msg["To"] = gmail_address
    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_address, gmail_app_password)
        server.sendmail(gmail_address, gmail_address, msg.as_string())

    print(f"  📧 Alert email sent!")


def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"[{now}] Checking Staccato CA compliant CPO stock...")

    all_available = []

    for product in PRODUCTS:
        try:
            data = fetch_product_json(product["slug"])
            available = find_available_compliant_variants(data, product)
            if available:
                print(f"  ✅ {product['label']}: {len(available)} compliant variant(s) IN STOCK!")
                all_available.extend(available)
            else:
                print(f"  ⚪ {product['label']}: no available compliant variants")
        except Exception as e:
            print(f"  ⚠️  {product['label']}: error — {e}")

    if all_available:
        print(f"\nFound {len(all_available)} available item(s) — sending email...")
        try:
            send_email(all_available)
        except Exception as e:
            print(f"  ⚠️  Email failed: {e}")
    else:
        print("\nNothing available this check. No email sent.")

    print("Done.")


if __name__ == "__main__":
    main()
