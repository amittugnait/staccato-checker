"""
Staccato California-Compliant CPO Stock Checker
Designed for GitHub Actions - runs once, checks stock, emails if found, then exits.

Required environment variables (GitHub Secrets):
  GMAIL_ADDRESS      - your Gmail address
  GMAIL_APP_PASSWORD - your Gmail App Password (16-char, not your real password)
"""

import urllib.request
import urllib.error
import json
import smtplib
import os
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone

PRODUCTS = [
    {
        "label": "Staccato HD C3.6",
        "url": "https://staccato2011.com/products/staccato-hd-c3-6-certified-pre-owned-handgun",
    },
    {
        "label": "Staccato HD P4",
        "url": "https://staccato2011.com/products/staccato-hd-p4-certified-pre-owned-handgun",
    },
    {
        "label": "Staccato HD C4X",
        "url": "https://staccato2011.com/products/staccato-hd-c4x-certified-pre-owned-handgun",
        "fallback_url": "https://staccato2011.com/products/staccato-hd-c4x-state-compliant",
    },
]

COMPLIANT_KEYWORDS = ["compliant preferred", "state compliant preferred"]

# Condition grades Staccato uses — any of these appearing WITHOUT "(Out of stock)"
# means that condition is available to purchase
CONDITION_GRADES = ["like new", "very good", "average", "factory blem"]


def fetch_html(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


def extract_next_data(html):
    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except Exception:
        return None


def find_available_compliant_variants_next(next_data, product):
    """Parse availability from Next.js embedded JSON."""
    found = []
    try:
        props = next_data.get("props", {})
        page_props = props.get("pageProps", {})
        product_data = (
            page_props.get("product") or
            page_props.get("data", {}).get("product") or
            page_props.get("productData") or {}
        )
        variants = product_data.get("variants", [])
        if not variants:
            edges = product_data.get("variants", {}).get("edges", [])
            variants = [e.get("node", {}) for e in edges]
    except Exception as e:
        print(f"    Could not parse variant data: {e}")
        return found

    if not variants:
        print(f"    No variants found in Next.js data")
        return found

    for v in variants:
        option_values = v.get("option_values", []) or v.get("optionValues", [])
        if option_values and isinstance(option_values[0], dict) and "node" in option_values[0]:
            option_values = [e["node"] for e in option_values]

        all_labels = " ".join(
            (o.get("label") or o.get("value") or o.get("name") or "").lower()
            for o in option_values
        )

        if not any(kw in all_labels for kw in COMPLIANT_KEYWORDS):
            continue

        purchasing_disabled = v.get("purchasing_disabled") or v.get("purchasingDisabled") or False
        inventory_level = v.get("inventory_level") or v.get("inventoryLevel") or 0
        inventory_tracking = v.get("inventory_tracking") or v.get("inventoryTracking") or "none"

        in_stock = (
            not purchasing_disabled
            and (inventory_level > 0 or inventory_tracking == "none")
        )

        price = v.get("price") or v.get("calculated_price") or v.get("calculatedPrice")
        price_str = f"${float(price):,.2f}" if price else "See site"

        if not in_stock:
            print(f"    ❌ Compliant variant found but sold out ({price_str})")
            continue

        config_label = next(
            ((o.get("label") or o.get("value") or "") for o in option_values
             if "config" in (o.get("option_display_name") or o.get("optionDisplayName") or "").lower()
             or "package" in (o.get("option_display_name") or o.get("optionDisplayName") or "").lower()),
            all_labels
        )
        condition_label = next(
            ((o.get("label") or o.get("value") or "") for o in option_values
             if "condition" in (o.get("option_display_name") or o.get("optionDisplayName") or "").lower()),
            ""
        )
        found.append({
            "label": product["label"],
            "config": config_label,
            "condition": condition_label,
            "price": price_str,
            "url": product["url"],
        })

    return found


def check_html_fallback(html, product):
    """
    Reliable HTML fallback using two signals that must BOTH be true:
    1. A compliant keyword exists on the page (the config is listed)
    2. At least one condition grade appears WITHOUT '(out of stock)' after it
       — meaning some condition is purchasable

    This correctly handles the case where the non-compliant config is available
    but the compliant one is sold out, because Staccato's conditions are shared
    across all configurations — if any condition is available, the compliant
    config can also be selected with that condition.
    """
    lower = html.lower()

    # Signal 1: compliant config is listed on the page
    has_compliant = any(kw in lower for kw in COMPLIANT_KEYWORDS)
    if not has_compliant:
        print(f"    No compliant configuration found on page")
        return []

    # Signal 2: find a condition grade that is NOT followed by "(out of stock)"
    available_conditions = []
    for grade in CONDITION_GRADES:
        idx = lower.find(grade)
        if idx == -1:
            continue
        # Look at the 60 chars after the grade name
        after = lower[idx:idx + 60]
        if "out of stock" not in after:
            available_conditions.append(grade.title())

    if not available_conditions:
        print(f"    ❌ Compliant config listed but all conditions show (Out of stock)")
        return []

    # Both signals present — something is available!
    price_match = re.search(r'\$[\d,]+\.?\d*', html)
    price_str = price_match.group(0) if price_match else "See site"

    conditions_str = ", ".join(available_conditions)
    print(f"    ✅ Compliant config available! Conditions in stock: {conditions_str}")

    return [{
        "label": product["label"],
        "config": "State Compliant Preferred Package",
        "condition": conditions_str,
        "price": price_str,
        "url": product["url"],
    }]


def check_product(product):
    urls_to_try = [product["url"]]
    if product.get("fallback_url"):
        urls_to_try.append(product["fallback_url"])

    for url in urls_to_try:
        try:
            print(f"    Fetching {url}")
            html = fetch_html(url)

            next_data = extract_next_data(html)
            if next_data:
                print(f"    Found Next.js page data, parsing variants...")
                return find_available_compliant_variants_next(next_data, product)
            else:
                print(f"    No Next.js data found, using HTML fallback...")
                return check_html_fallback(html, product)

        except urllib.error.HTTPError as e:
            if e.code == 404:
                print(f"    404 at {url}" + (", trying fallback..." if product.get("fallback_url") and url == product["url"] else ""))
                continue
            else:
                print(f"    ⚠️  HTTP error {e.code}")
                return []
        except Exception as e:
            print(f"    ⚠️  Error: {e}")
            return []

    print(f"    ⚠️  All URLs returned 404 — CPO page may not exist yet for this model")
    return []


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
        rows_text += f"  • {v['label']} | {v['config']} | {v.get('condition','')}\n    Price: {v['price']}\n    {v['url']}\n\n"

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
    print(f"[{now}] Checking Staccato CA compliant CPO stock...\n")

    all_available = []

    for product in PRODUCTS:
        print(f"  Checking {product['label']}...")
        available = check_product(product)
        if available:
            print(f"  ✅ {len(available)} compliant variant(s) IN STOCK!")
            all_available.extend(available)
        else:
            print(f"  ⚪ Nothing available")
        print()

    if all_available:
        print(f"Found {len(all_available)} available item(s) — sending email...")
        try:
            send_email(all_available)
        except Exception as e:
            print(f"  ⚠️  Email failed: {e}")
    else:
        print("Nothing available this check. No email sent.")

    print("Done.")


if __name__ == "__main__":
    main()
