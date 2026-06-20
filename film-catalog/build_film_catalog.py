import csv
import re
import time
import hashlib
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


SOURCES = "film_sources.csv"
LINE_URL_OUTPUT = "film_line_urls_review.csv"
CATALOG_OUTPUT = "film_catalog_review.csv"
NAMES_OUTPUT = "film_names_review.csv"
NAMES_OUTPUT = "film_names_review.csv"

MAX_PAGES_PER_SOURCE = 15
REQUEST_DELAY_SECONDS = 8.0

HEADERS = {
    "User-Agent": "Mozilla/5.0 compatible; ProkvikFilmCatalogBot/0.1; review-only crawler"
}

FILM_KEYWORDS = [
    "window film",
    "automotive film",
    "architectural film",
    "flat glass",
    "tint",
    "ceramic",
    "carbon",
    "dyed",
    "nano",
    "ir",
    "infrared",
    "uv",
    "tser",
    "vlt",
    "glare",
    "heat rejection",
    "privacy",
    "safety",
    "security",
    "decorative",
    "warranty",
    "film",
]

BAD_URL_WORDS = [
    "cart",
    "checkout",
    "account",
    "authentication",
    "buyer_flags",
    "login",
    "register",
    "dealer-locator",
    "find-a-dealer",
    "privacy-policy",
    "terms",
    "warranty-registration",
    "blog",
    "news",
    "contact",
    "about",
    "careers",
    "faq",
    "country",
    "region",
    "locale",
    "currency",
    "redirect",
    "coating",
    "ceramic-shield",
    "graphene",
    "ppf",
    "paint-protection",
    "tools",
    "dealer-gear",
    "merch",
    "clothing",
    "classes",
    "training",
    "apparel",
    "bottles",
    "cards-and-paper",
    "flags-and-banners",
]


def clean_text(value):
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_url(url):
    parsed = urlparse(url)
    return parsed._replace(fragment="", query="").geturl().rstrip("/")


def same_domain(seed_url, candidate_url):
    seed_host = urlparse(seed_url).netloc.lower().replace("www.", "")
    candidate_host = urlparse(candidate_url).netloc.lower().replace("www.", "")
    return seed_host == candidate_host


def looks_bad_url(url):
    lower = url.lower()
    return any(word in lower for word in BAD_URL_WORDS)


def keyword_score(text):
    lower = (text or "").lower()
    score = 0
    for kw in FILM_KEYWORDS:
        if kw in lower:
            score += 1
    return score


def fetch_page(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=25)

        if response.status_code == 429:
            print(f"⏳ Rate limited: {url} — sleeping 30s")
            time.sleep(30)
            return None

        response.raise_for_status()

        content_type = response.headers.get("content-type", "").lower()
        if "text/html" not in content_type:
            return None

        return response.text
    except Exception as exc:
        print(f"❌ Failed: {url} — {exc}")
        return None


def get_title_and_text(html):
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    title = clean_text(soup.title.get_text()) if soup.title else ""

    headings = []
    for tag in soup.find_all(["h1", "h2", "h3"]):
        txt = clean_text(tag.get_text())
        if txt:
            headings.append(txt)

    body_parts = []
    for tag in soup.find_all(["h1", "h2", "h3", "p", "li", "td", "th"]):
        txt = clean_text(tag.get_text())
        if txt and len(txt) > 2:
            body_parts.append(txt)

    full_text = clean_text(" ".join(body_parts))

    return title, headings, full_text


def extract_shopify_collection_links(seed_url):
    """
    Shopify collection pages often expose a clean products.json feed.
    This avoids crawling country/region selectors, login redirects, carts, etc.
    """
    parsed = urlparse(seed_url)
    path = parsed.path.rstrip("/")

    if "/collections/" not in path:
        return []

    products_json_url = f"{parsed.scheme}://{parsed.netloc}{path}/products.json?limit=250"

    try:
        response = requests.get(products_json_url, headers=HEADERS, timeout=20)

        if response.status_code == 429:
            print(f"   ⏳ Shopify products.json rate limited: {products_json_url}")
            return []

        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        print(f"   ⚠️ Shopify products.json unavailable: {products_json_url} — {exc}")
        return []

    rows = []

    for product in data.get("products", []):
        handle = product.get("handle")
        title = clean_text(product.get("title", ""))

        if not handle:
            continue

        product_type = clean_text(product.get("product_type", ""))
        tags_list = product.get("tags", []) or []
        tags = ", ".join(tags_list)

        combined = f"{title} {handle} {product_type} {' '.join(tags_list)}".lower()

        if any(bad in combined for bad in BAD_URL_WORDS):
            continue

        if not any(good in combined for good in [
            "film",
            "tint",
            "window",
            "architectural",
            "automotive",
            "ceramic",
            "carbon",
            "clear",
            "reflective",
            "dual reflective",
            "solar",
            "safety",
            "security",
            "privacy",
        ]):
            continue

        product_url = f"{parsed.scheme}://{parsed.netloc}/products/{handle}"

        body_html = product.get("body_html", "") or ""
        body_text = clean_text(BeautifulSoup(body_html, "html.parser").get_text(" "))

        rows.append({
            "url": normalize_url(product_url),
            "anchor_text": title,
            "link_score": max(5, keyword_score(f"{title} {product_url} {product_type} {tags}")),
            "shopify_title": title,
            "shopify_description": body_text,
            "shopify_product_type": product_type,
            "shopify_tags": tags,
        })

    if rows:
        print(f"   ✅ Shopify collection feed found {len(rows)} products")

    return rows


def extract_candidate_links(seed_url, html):
    shopify_links = extract_shopify_collection_links(seed_url)
    if shopify_links:
        return shopify_links

    soup = BeautifulSoup(html, "html.parser")
    links = {}

    for a in soup.find_all("a", href=True):
        href = normalize_url(urljoin(seed_url, a["href"]))
        label = clean_text(a.get_text(" "))

        if not href.startswith("http"):
            continue
        if not same_domain(seed_url, href):
            continue
        if looks_bad_url(href):
            continue

        href_lower = href.lower()
        label_lower = label.lower()
        score_text = f"{href} {label}"
        score = keyword_score(score_text)

        keep = False

        if "/products/" in href_lower:
            keep = True
        elif "/collections/" in href_lower and any(word in href_lower for word in [
            "film",
            "tint",
            "auto",
            "architect",
            "ceramic",
            "carbon",
            "window",
        ]):
            keep = True
        elif score >= 2 and any(word in label_lower for word in [
            "film",
            "tint",
            "ceramic",
            "carbon",
            "architectural",
            "automotive",
            "window",
        ]):
            keep = True

        if keep:
            links[href] = {
                "url": href,
                "anchor_text": label,
                "link_score": score,
            }

    return list(links.values())


def guess_film_line(title, headings, url):
    candidates = []

    for h in headings:
        if 2 <= len(h) <= 80:
            candidates.append(h)

    if title:
        candidates.append(title)

    slug = urlparse(url).path.rstrip("/").split("/")[-1]
    if slug:
        slug_name = slug.replace("-", " ").replace("_", " ").title()
        candidates.append(slug_name)

    # Prefer headings that do not look generic.
    generic = {
        "window film",
        "automotive window film",
        "architectural window film",
        "products",
        "shop",
        "collections",
        "auto films",
        "architectural film",
    }

    for c in candidates:
        cleaned = clean_text(c)
        if cleaned and cleaned.lower() not in generic:
            return cleaned

    return clean_text(candidates[0]) if candidates else ""


def extract_specs(text):
    specs = []

    patterns = [
        r"\bVLT\b[^.]{0,80}",
        r"\bTSER\b[^.]{0,80}",
        r"\bIR\b[^.]{0,80}",
        r"\binfrared[^.]{0,80}",
        r"\bUV[^.]{0,80}",
        r"\bheat rejection[^.]{0,100}",
        r"\bglare reduction[^.]{0,100}",
        r"\bceramic[^.]{0,100}",
        r"\bcarbon[^.]{0,100}",
        r"\blifetime warranty[^.]{0,100}",
    ]

    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            cleaned = clean_text(match)
            if cleaned and cleaned not in specs:
                specs.append(cleaned)

    return " | ".join(specs[:20])


def make_id(brand, category, url):
    raw = f"{brand}|{category}|{url}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def category_allows_url(brand, category, url, film_line):
    brand_l = (brand or "").lower()
    category_l = (category or "").lower()
    url_l = (url or "").lower()
    line_l = (film_line or "").lower()

    if brand_l == "rogue":
        if category_l == "automotive_window_film":
            if "/architectural-film/" in url_l:
                return False
            if "/auto-films/" not in url_l:
                return False
            if line_l in {"decorative films", "silver reflective films", "dual reflective films", "architectural films"}:
                return False

        if category_l == "architectural_window_film":
            if "/auto-films/" in url_l:
                return False
            if "/architectural-film/" not in url_l:
                return False
            if line_l in {"eclipse carbon ceramic", "eclipse carbon", "next-level comfort"}:
                return False

    if brand_l == "geoshield":
        architectural_lines = {
            "20/20 interior and exterior films",
            "8mil clear safety film",
            "astro",
            "blackout privacy film",
            "white frost",
            "geo",
            "lunar",
            "solar bronze",
            "super alloy",
            "ultra",
        }

        automotive_lines = {
            "apex ultra",
            "c2 carbon",
            "c2 ceramic",
            "pro classic",
            "pro nano",
        }

        if line_l == "geoshield blister free film":
            return False

        if category_l == "automotive_window_film" and line_l in architectural_lines:
            return False

        if category_l == "architectural_window_film" and line_l in automotive_lines:
            return False

    return True


def crawl_source(source):
    brand = source["brand"].strip()
    category = source.get("film_category", "").strip()
    start_url = source["url"].strip()

    print(f"\n🔎 Crawling {brand} — {category}")
    print(f"   {start_url}")

    start_html = fetch_page(start_url)
    if not start_html:
        return [], []

    discovered = {
        normalize_url(start_url): {
            "url": normalize_url(start_url),
            "anchor_text": "seed URL",
            "link_score": keyword_score(start_url),
        }
    }

    for link in extract_candidate_links(start_url, start_html):
        discovered[link["url"]] = link

    candidate_urls = sorted(
        discovered.values(),
        key=lambda x: (-x["link_score"], x["url"])
    )[:MAX_PAGES_PER_SOURCE]

    line_url_rows = []
    catalog_rows = []

    for item in candidate_urls:
        url = item["url"]

        if item.get("shopify_title") or item.get("shopify_description"):
            title = item.get("shopify_title", "") or item.get("anchor_text", "")
            headings = [title] if title else []
            text = item.get("shopify_description", "")
            score = keyword_score(
                f"{url} {title} {text[:3000]} {item.get('shopify_product_type', '')} {item.get('shopify_tags', '')}"
            )
        else:
            html = fetch_page(url)
            if not html:
                continue

            title, headings, text = get_title_and_text(html)
            score = keyword_score(f"{url} {title} {' '.join(headings)} {text[:3000]}")

        if score < 2:
            continue

        film_line = guess_film_line(title, headings, url)

        generic_lines = {
            "country/region",
            "country region",
            "country",
            "region",
            "select your country",
            "shipping",
            "account",
            "log in",
            "login",
            "dealer login",
            "dealer portal",
            "dealer resources",
            "create account",
            "become a dealer",
            "training",
            "features",
            "our products",
            "products",
            "home",
            "contact us",
            "proven performance",
            "cutting edge",
            "cutting edge standard in ceramic technology, again",
            "superior performance",
            "nano-ceramic technology with no limits",
            "quality you can trust",
            "the autobahn difference",
            "affordable performance",
            "professional quality window film",
            "window tint",
            "window film",
            "automotive window film",
            "architectural window film",
            "automotive films",
            "architectural films",
            "auto films",
            "architectural film",
        }

        film_line_clean = film_line.strip().lower()

        if film_line_clean in generic_lines:
            continue

        if any(bad in film_line_clean for bad in [
            "dealer login",
            "create account",
            "become a dealer",
            "contact us",
            "our products",
            "shop now",
            "learn more",
        ]):
            continue

        if looks_bad_url(url):
            continue

        specs = extract_specs(text)

        line_id = make_id(brand, category, url)

        line_url_rows.append({
            "id": line_id,
            "brand": brand,
            "film_category": category,
            "film_line_guess": film_line,
            "source_url": url,
            "anchor_text": item.get("anchor_text", ""),
            "match_score": score,
            "review_status": "needs_review",
            "notes": title,
        })

        catalog_rows.append({
            "id": line_id,
            "brand": brand,
            "film_line": film_line,
            "film_category": category,
            "short_description": "",
            "long_description": text[:3000],
            "published_specs": specs,
            "source_url": url,
            "review_status": "needs_review",
            "notes": title,
        })

        print(f"   ✅ {brand}: {film_line} — score {score}")
        time.sleep(REQUEST_DELAY_SECONDS)

    return line_url_rows, catalog_rows


def dedupe_rows(rows, key_fields):
    seen = set()
    output = []

    for row in rows:
        key = tuple(row.get(field, "") for field in key_fields)
        if key in seen:
            continue
        seen.add(key)
        output.append(row)

    return output


def write_csv(path, rows, fieldnames):
    with open(path, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"✅ Wrote {path}")
    print(f"Rows: {len(rows)}")


def main():
    all_line_url_rows = []
    all_catalog_rows = []

    with open(SOURCES, newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        for source in reader:
            line_rows, catalog_rows = crawl_source(source)
            all_line_url_rows.extend(line_rows)
            all_catalog_rows.extend(catalog_rows)

    all_line_url_rows = dedupe_rows(all_line_url_rows, ["brand", "film_category", "source_url"])
    all_catalog_rows = dedupe_rows(all_catalog_rows, ["brand", "film_category", "source_url"])

    write_csv(
        LINE_URL_OUTPUT,
        all_line_url_rows,
        [
            "id",
            "brand",
            "film_category",
            "film_line_guess",
            "source_url",
            "anchor_text",
            "match_score",
            "review_status",
            "notes",
        ],
    )

    write_csv(
        CATALOG_OUTPUT,
        all_catalog_rows,
        [
            "id",
            "brand",
            "film_line",
            "film_category",
            "short_description",
            "long_description",
            "published_specs",
            "source_url",
            "review_status",
            "notes",
        ],
    )

    name_rows = []
    for row in all_line_url_rows:
        film_name = clean_text(row.get("film_line_guess", ""))
        if not film_name:
            continue

        name_rows.append({
            "brand": row.get("brand", ""),
            "film_category": row.get("film_category", ""),
            "film_name": film_name,
            "source_url": row.get("source_url", ""),
            "review_status": "needs_review",
        })

    name_rows = dedupe_rows(name_rows, ["brand", "film_category", "film_name"])

    write_csv(
        NAMES_OUTPUT,
        name_rows,
        [
            "brand",
            "film_category",
            "film_name",
            "source_url",
            "review_status",
        ],
    )


if __name__ == "__main__":
    main()
