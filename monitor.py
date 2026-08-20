import os
import json
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup


PUSHOVER_WEBHOOK_URL = os.environ["PUSHOVER_WEBHOOK_URL"]

STATE_DIR = Path("state")
STATE_FILE = STATE_DIR / "seen.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) "
        "AppleWebKit/605.1.15 Safari/604.1"
    )
    }
SOURCES = [
    {
        "name": "Bandai One Piece",
        "game": "ONE PIECE",
        "url": "https://en.onepiece-cardgame.com/products/",
        "type": "bandai",
    },
    {
        "name": "Bandai Dragon Ball Fusion World",
        "game": "DRAGON BALL",
        "url": "https://www.dbs-cardgame.com/fw/en/products/",
        "type": "bandai",
    },
    {
        "name": "Premium Bandai USA",
        "game": "BANDAI PREMIUM",
        "url": "https://p-bandai.com/us/",
        "type": "bandai",
    },
    {
        "name": "Southern Hobby",
        "game": "DISTRIBUTOR",
        "url": "https://www.southernhobby.com/products_recent.php",
        "type": "southern_hobby",
    },
{
        "name": "Kollect Korner",
        "game": "ONE PIECE / DRAGON BALL",
        "url": "https://www.kollectkorner.com/collections/preorders",
        "type": "kollect_korner",
    },
]

def load_state():
    STATE_DIR.mkdir(exist_ok=True)

    if not STATE_FILE.exists():
        return {}

    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def save_state(state):
    STATE_DIR.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))


def get_page(url):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()
    return response.text


def clean_text(text):
    return re.sub(r"\s+", " ", text).strip()


def fingerprint(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def send_alert(title, message, url):
    payload = {
        "title": title,
        "message": message,
        "url": url,
        "url_title": "Open Product / Order Page",
    }

    response = requests.post(
        PUSHOVER_WEBHOOK_URL,
        json=payload,
        timeout=30,
    )

    response.raise_for_status()


def monitor_bandai(source, html, state):
    soup = BeautifulSoup(html, "html.parser")

    # Look for product-like text containing known TCG identifiers.
    candidates = []

    for element in soup.find_all(["a", "li", "article", "div"]):
        text = clean_text(element.get_text(" ", strip=True))

        if not text:
            continue

        if len(text) > 500:
            continue

        if re.search(
            r"\b(OP-\d+|OP\d+-EB\d+|EB-\d+|PRB-\d+|FB\d+|FS\d+|ST\d+)\b",
            text,
            re.IGNORECASE,
        ):
            candidates.append(text)

    # Remove duplicates while preserving order.
    unique = []
    seen = set()

    for item in candidates:
        key = fingerprint(item)

        if key not in seen:
            seen.add(key)
            unique.append(item)

    # Keep the useful product-level records.
    unique = unique[:100]

    current = {
        item: fingerprint(item)
        for item in unique
    }

    source_key = source["name"]
    previous = state.get(source_key, {})

    # First run establishes a baseline.
    if not previous:
        state[source_key] = current
        print(f"{source_key}: baseline established ({len(current)} records)")
        return

    new_items = [
        item for item in unique
        if item not in previous
    ]

    changed_items = [
        item for item in unique
        if item in previous and previous[item] != current[item]
    ]

    for item in new_items:
        send_alert(
            f"🚨 {source['game']} — NEW PRODUCT",
            f"{item}\n\nA new product entry was detected on the official Bandai page.",
            source["url"],
        )

    for item in changed_items:
        send_alert(
            f"🔔 {source['game']} — PRODUCT UPDATED",
            f"{item}\n\nAn existing product entry changed on the official Bandai page.",
            source["url"],
        )

    state[source_key] = current

    print(
        f"{source_key}: "
        f"{len(new_items)} new, "
        f"{len(changed_items)} changed"
    )


def monitor_southern_hobby(source, html, state):
    soup = BeautifulSoup(html, "html.parser")

    page_text = clean_text(soup.get_text(" ", strip=True))

    # Product identifiers we're interested in.
    product_pattern = re.compile(
        r"(Bandai\s*-\s*One Piece Card Game:[^|]+?"
        r"OP-\d+|"
        r"Dragon Ball Super Fusion World:[^|]+?"
        r"FB\d+|"
        r"Dragon Ball Super Fusion World:[^|]+?"
        r"FS\d+)",
        re.IGNORECASE,
    )

    matches = product_pattern.findall(page_text)

    # If the site's formatting changes, fall back to table rows.
    if not matches:
        for row in soup.find_all("tr"):
            text = clean_text(row.get_text(" ", strip=True))

            if re.search(
                r"(One Piece Card Game|Dragon Ball Super Fusion World)",
                text,
                re.IGNORECASE,
            ) and re.search(
                r"(OP-\d+|FB\d+|FS\d+)",
                text,
                re.IGNORECASE,
            ):
                matches.append(text)

    unique = []
    seen = set()

    for item in matches:
        item = clean_text(item)

        if len(item) > 400:
            continue

        if item not in seen:
            seen.add(item)
            unique.append(item)

    current = {
        item: fingerprint(item)
        for item in unique
    }

    source_key = source["name"]
    previous = state.get(source_key, {})

    if not previous:
        state[source_key] = current
        print(f"{source_key}: baseline established ({len(current)} records)")
        return

    new_items = [
        item for item in unique
        if item not in previous
    ]

    changed_items = [
        item for item in unique
        if item in previous and previous[item] != current[item]
    ]

    for item in new_items:
        game = (
            "ONE PIECE"
            if "One Piece" in item
            else "DRAGON BALL"
        )

        send_alert(
            f"🚨 {game} — DISTRIBUTOR UPDATE",
            f"{item}\n\nNew distributor information detected at Southern Hobby.",
            source["url"],
        )

    for item in changed_items:
        game = (
            "ONE PIECE"
            if "One Piece" in item
            else "DRAGON BALL"
        )

        send_alert(
            f"🚨 {game} — ORDER INFO CHANGED",
            f"{item}\n\nDistributor information changed at Southern Hobby.",
            source["url"],
        )

    state[source_key] = current

    print(
        f"{source_key}: "
        f"{len(new_items)} new, "
        f"{len(changed_items)} changed"
    )
def monitor_kollect_korner(source, html, state):
    soup = BeautifulSoup(html, "html.parser")

    products = []

    # Shopify product cards
    for item in soup.select(
        "li.grid__item, .card-wrapper, .product-card-wrapper, "
        ".product-grid .grid__item, .product-item"
    ):
        text = clean_text(item.get_text(" ", strip=True))

        if not text:
            continue

        # Only monitor the two games we care about.
        if not re.search(
            r"(One Piece|Dragon Ball.*Fusion World)",
            text,
            re.IGNORECASE,
        ):
            continue

        # Only monitor actual preorder listings.
        if not re.search(
            r"(pre[\s-]?order|preorder)",
            text,
            re.IGNORECASE,
        ):
            continue

        # Determine whether the product is currently purchasable.
        sold_out = bool(
            re.search(
                r"(sold out|unavailable)",
                text,
                re.IGNORECASE,
            )
        )

        available = bool(
            re.search(
                r"(add to cart|add to bag|buy now)",
                text,
                re.IGNORECASE,
            )
        )

        # Try to find the product URL.
        link = item.find("a", href=True)

        if link:
            product_url = link["href"]

            if product_url.startswith("/"):
                product_url = "https://www.kollectkorner.com" + product_url
        else:
            product_url = source["url"]

        # Create a compact record.
        record = {
            "text": text,
            "url": product_url,
            "available": available and not sold_out,
        }

        products.append(record)

    # Fallback: inspect links if the Shopify card selectors change.
    if not products:
        for link in soup.find_all("a", href=True):
            text = clean_text(link.get_text(" ", strip=True))

            if not text:
                continue

            if not re.search(
                r"(One Piece|Dragon Ball.*Fusion World)",
                text,
                re.IGNORECASE,
            ):
                continue

            if not re.search(
                r"(pre[\s-]?order|preorder)",
                text,
                re.IGNORECASE,
            ):
                continue

            url = link["href"]

            if url.startswith("/"):
                url = "https://www.kollectkorner.com" + url

            products.append(
                {
                    "text": text,
                    "url": url,
                    "available": True,
                }
            )

    # Deduplicate products.
    unique = {}

    for product in products:
        key = product["url"]

        if key not in unique:
            unique[key] = product

    products = list(unique.values())

    current = {
        product["url"]: {
            "text": product["text"],
            "available": product["available"],
        }
        for product in products
    }

    source_key = source["name"]
    previous = state.get(source_key, {})

    # First run establishes the baseline.
    if not previous:
        state[source_key] = current

        print(
            f"{source_key}: baseline established "
            f"({len(current)} products)"
        )

        return

    for product in products:
        url = product["url"]
        current_data = current[url]
        previous_data = previous.get(url)

        # Brand-new preorder listing.
        if previous_data is None:
            game = (
                "ONE PIECE"
                if re.search(
                    r"One Piece",
                    product["text"],
                    re.IGNORECASE,
                )
                else "DRAGON BALL"
            )

            send_alert(
                f"🚨 {game} — KOLLECT KORNER PREORDER",
                (
                    f"{product['text']}\n\n"
                    "New preorder detected at Kollect Korner."
                ),
                url,
            )

            continue

        # Existing preorder changed from unavailable to available.
        if (
            not previous_data.get("available", False)
            and current_data.get("available", False)
        ):
            game = (
                "ONE PIECE"
                if re.search(
                    r"One Piece",
                    product["text"],
                    re.IGNORECASE,
                )
                else "DRAGON BALL"
            )

            send_alert(
                f"🔥 {game} — KOLLECT KORNER NOW AVAILABLE",
                (
                    f"{product['text']}\n\n"
                    "A previously unavailable preorder "
                    "is now showing as available."
                ),
                url,
            )

    state[source_key] = current

    print(
        f"{source_key}: "
        f"{len(products)} One Piece / Dragon Ball "
        f"preorders monitored"
    )


def main():
    state = load_state()

    for source in SOURCES:
        try:
            print(f"Checking {source['name']}...")

            html = get_page(source["url"])

            if source["type"] == "bandai":
                monitor_bandai(source, html, state)

            elif source["type"] == "southern_hobby":
                monitor_southern_hobby(source, html, state)
            
            elif source["type"] == "kollect_korner":
                monitor_kollect_korner(source, html, state)


        except Exception as exc:
            print(
                f"ERROR checking {source['name']}: "
                f"{type(exc).__name__}: {exc}"
            )

    save_state(state)


if __name__ == "__main__":
    main()
