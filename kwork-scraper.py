#!/usr/bin/env python3
"""kwork-scraper - Open-source scraper for kwork.ru"""

import re
import json
import time
import random
import logging
import argparse
import sys
from urllib.parse import urljoin

import httpx
import dataset
from fake_useragent import UserAgent

STATE_DATA_RE = re.compile(r"window\.stateData\s*=\s*({.*?});window\.", re.DOTALL)

BASE_URL = "https://kwork.ru"

HEADERS_TEMPLATE = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.5",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": BASE_URL,
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

logger = logging.getLogger("kwork-scraper")

_delay_min = 1.0
_delay_max = 3.0


def setup_logging():
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger.setLevel(logging.INFO)


def random_delay():
    time.sleep(random.uniform(_delay_min, _delay_max))


def parse_args():
    parser = argparse.ArgumentParser(description="kwork-scraper")
    parser.add_argument(
        "-c",
        "--category",
        action="append",
        default=[],
        dest="categories",
        help="Category slug (repeatable)",
    )
    parser.add_argument(
        "-f",
        "--filter",
        action="append",
        default=[],
        dest="filters",
        help="Platform filter in key=value format (repeatable)",
    )
    parser.add_argument(
        "-d",
        "--database",
        default="sqlite:///kwork.db",
        help="Database URL (SQLite or PostgreSQL)",
    )
    parser.add_argument(
        "-D",
        "--delay",
        nargs=2,
        type=float,
        default=[1.0, 3.0],
        metavar=("MIN", "MAX"),
        help="Requests delay range in seconds (default: 1.0 3.0)",
    )
    return parser.parse_args()


def create_http_client() -> httpx.Client:
    ua = UserAgent()
    return httpx.Client(
        headers={"User-Agent": ua.random},
        follow_redirects=True,
    )


def extract_state_data(html: str):
    match = STATE_DATA_RE.search(html)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None

def safe_request(method: str, session: httpx.Client, url: str, retries: int = 3, **kwargs) -> httpx.Response | None:
    """Safely make an HTTP request with retries and exponential backoff"""
    for attempt in range(retries):
        try:
            resp = session.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp
        except httpx.HTTPError as e:
            logger.warning(f"HTTP error on {url} (Attempt {attempt + 1}/{retries}): {e}")
            if attempt < retries - 1:
                # Exponential backoff: 2s, 4s, 8s...
                time.sleep(2 ** (attempt + 1)) 
            else:
                logger.error(f"Failed to fetch {url} after {retries} attempts.")
                return None


# --- Database ---


def init_db(db_url: str):
    return dataset.connect(db_url)


def upsert_category(db, parent_id: int | None, name: str, slug: str) -> int:
    table = db["categories"]
    existing = table.find_one(slug=slug)
    if existing:
        table.update(
            dict(id=existing["id"], parent_id=parent_id, name=name, slug=slug), ["id"]
        )
        return existing["id"]
    return table.insert(dict(parent_id=parent_id, name=name, slug=slug))


def upsert_user(db, user_id: int, username: str):
    table = db["users"]
    if not table.find_one(id=user_id):
        table.insert(dict(id=user_id, username=username))


def insert_kwork(db, data: dict):
    table = db["kworks"]
    if not table.find_one(id=data["id"]):
        table.insert(data)


def insert_package(db, data: dict):
    table = db["packages"]
    if not table.find_one(id=data["id"]):
        table.insert(data)


def insert_extra(db, data: dict):
    table = db["extras"]
    if not table.find_one(id=data["id"]):
        table.insert(data)


def insert_review(db, data: dict):
    table = db["reviews"]
    if not table.find_one(id=data["id"]):
        table.insert(data)


def get_db_category_id_by_slug(db, slug: str) -> int | None:
    row = db["categories"].find_one(slug=slug)
    return row["id"] if row else None


# --- Categories ---


def load_categories(session: httpx.Client) -> list[dict]:
    resp = safe_request("GET", session, f"{BASE_URL}/")
    if not resp:
        logger.error("Failed to load main page for categories")
        return []
    
    sd = extract_state_data(resp.text)
    if not sd:
        logger.error("Failed to extract stateData from main page")
        return []
    return sd.get("headerMenu", [])


def parse_category_tree(header_menu: list[dict]) -> dict[str, dict]:
    """
    Parse headerMenu into flat dict of slug -> category info.
    Returns {slug: {name, level, l1_slug?, l2_slug?}}
    """
    result = {}

    for l1 in header_menu:
        l1_name = l1["name"]
        l1_slug = l1["url"].rstrip("/").rsplit("/", 1)[-1]
        result[l1_slug] = {"name": l1_name, "level": 1}

        for column in l1.get("columns", []):
            for item in column.get("items", []):
                l2_name = item["name"]
                l2_slug = None
                first_child = None

                children = item.get("children", [])
                if children:
                    for child_group in children:
                        if child_group:
                            first_child = child_group[0]
                            break

                if not first_child:
                    continue

                l2_slug = first_child["url"].rstrip("/").rsplit("/", 2)[-2]
                result[l2_slug] = {
                    "name": l2_name,
                    "level": 2,
                    "l1_slug": l1_slug,
                }

                for child_group in children:
                    for child in child_group:
                        child_url = child["url"]
                        slug_parts = child_url.rstrip("/").rsplit("/", 2)[-2:]
                        l3_slug = "/".join(slug_parts)
                        result[l3_slug] = {
                            "name": child["name"],
                            "level": 3,
                            "l2_slug": l2_slug,
                            "l1_slug": l1_slug,
                        }

    return result


def validate_and_deduplicate_categories(requested: list[str], tree: dict) -> list[str]:
    queue = set()
    l2_in_queue: set[str] = set()

    for slug in requested:
        slug = slug.strip("/")
        if slug not in tree:
            logger.warning("Unknown category slug '%s', skipping", slug)
            continue

        info = tree[slug]

        if info["level"] == 1:
            l1_slug = slug
            expanded = [
                s
                for s, si in tree.items()
                if si.get("l1_slug") == l1_slug and si["level"] == 2
            ]
            queue.update(expanded)
            l2_in_queue.update(expanded)
            logger.info("Expanded L1 '%s' to %d L2 children", slug, len(expanded))

        elif info["level"] == 2:
            queue.add(slug)
            l2_in_queue.add(slug)

        elif info["level"] == 3:
            l2_slug = info.get("l2_slug")
            if l2_slug and l2_slug in l2_in_queue:
                logger.warning(
                    "L3 '%s' skipped: L2 parent '%s' already in queue",
                    slug,
                    l2_slug,
                )
            else:
                queue.add(slug)

    return list(queue)


def store_category_tree(db, tree: dict) -> dict:
    # L1
    for slug, info in tree.items():
        if info["level"] == 1:
            info["db_id"] = upsert_category(db, None, info["name"], slug)

    # L2
    for slug, info in tree.items():
        if info["level"] == 2:
            parent_id = (
                tree[info["l1_slug"]]["db_id"] if info.get("l1_slug") in tree else None
            )
            info["db_id"] = upsert_category(db, parent_id, info["name"], slug)

    # L3
    for slug, info in tree.items():
        if info["level"] == 3:
            parent_id = (
                tree[info["l2_slug"]]["db_id"] if info.get("l2_slug") in tree else None
            )
            info["db_id"] = upsert_category(db, parent_id, info["name"], slug)

    return tree


# --- Catalog scraping ---


def fetch_catalog_page(
    session: httpx.Client,
    slug: str,
    page: int,
    exclude_ids: list[int],
    filters: dict[str, str],
) -> dict | None:
    url = f"{BASE_URL}/catalog_kworks_filters/{slug}"

    data: dict = {
        "page": str(page),
        "excludeIds": ",".join(map(str, exclude_ids)),
        "onePage": "1",
        "paymentTypes[]": "",
    }
    data.update(filters)

    headers = dict(HEADERS_TEMPLATE)
    headers["Referer"] = f"{BASE_URL}/categories/{slug}"

    resp = safe_request("POST", session, url, data=data, headers=headers)
    if not resp:
        return None
    
    try:
        return resp.json()
    except json.JSONDecodeError:
        logger.error("Failed to parse catalog JSON for '%s' page %d", slug, page)
        return None


# --- Kwork page scraping ---


def scrape_kwork_page(session: httpx.Client, kwork_url: str, category_id: int, db):
    url = urljoin(BASE_URL, kwork_url)
    resp = safe_request("GET", session, url)
    if not resp:
        return
    
    sd = extract_state_data(resp.text)
    if not sd:
        logger.error("Failed to extract stateData from %s", kwork_url)
        return

    kwork_data = sd.get("kwork")
    if not kwork_data:
        logger.error("No kwork data in stateData for %s", kwork_url)
        return

    # User
    user_id = kwork_data.get("userId")
    username = kwork_data.get("username", "")
    if user_id and username:
        upsert_user(db, user_id, username)

    # Kwork record
    is_package = kwork_data.get("isPackage", False)
    packages = kwork_data.get("packages", {})

    result_text = kwork_data.get("gwork", "")
    if not result_text and is_package and isinstance(packages, dict):
        std = packages.get("standard", {})
        if isinstance(std, dict) and std.get("desc"):
            result_text = std["desc"]

    kwork_record = {
        "id": kwork_data.get("id"),
        "category_id": category_id,
        "user_id": user_id,
        "url": kwork_url,
        "price": kwork_data.get("minVolumePrice") or kwork_data.get("price", 0),
        "bookmarks": kwork_data.get("bookmarkCount", 0),
        "queue": int(kwork_data.get("queueCount") or 0),
        "days": int(kwork_data.get("days") or 0),
        "average_work_time": int(kwork_data.get("avgWorkTime") or 0),
        "title": kwork_data.get("gtitle", ""),
        "description": kwork_data.get("gdesc", ""),
        "requirements": kwork_data.get("ginst", ""),
        "result": result_text,
    }
    insert_kwork(db, kwork_record)

    # Packages
    if is_package and isinstance(packages, dict):
        for pkg_type, pkg in packages.items():
            if isinstance(pkg, dict):
                insert_package(
                    db,
                    {
                        "id": pkg.get("id"),
                        "kwork_id": kwork_data.get("id"),
                        "type": pkg_type,
                        "price": pkg.get("minVolumePrice") or pkg.get("price", 0),
                        "days": pkg.get("duration", 0),
                        "title": pkg.get("desc", ""),
                    },
                )

    # Extras
    extras = sd.get("extras", [])
    if isinstance(extras, list):
        for extra in extras:
            insert_extra(
                db,
                {
                    "id": extra.get("id"),
                    "kwork_id": kwork_data.get("id"),
                    "price": extra.get("price", 0),
                    "days": extra.get("duration", 0),
                    "title": extra.get("title", ""),
                    "description": extra.get("description", ""),
                    "is_popular": extra.get("isPopular", False),
                },
            )


# --- Reviews scraping ---


def scrape_reviews(session: httpx.Client, kwork_id: int, db):
    for review_type in ("positive", "negative"):
        offset = 0
        limit = 12
        scraped = 0
        total = None

        while True:
            random_delay()

            headers = dict(HEADERS_TEMPLATE)
            headers["Content-Type"] = "application/json"
            headers["Referer"] = f"{BASE_URL}/"

            payload = {
                "id": kwork_id,
                "type": review_type,
                "offset": offset,
                "limit": limit,
            }
            resp = safe_request(
                "POST", 
                session, 
                f"{BASE_URL}/kwork/get_reviews",
                json=payload,
                headers=headers,
            )
            if not resp:
                logger.error("Failed to fetch reviews for kwork %d after retries", kwork_id)
                break

            try:
                data = resp.json()
            except json.JSONDecodeError:
                logger.error("Failed to parse reviews JSON for kwork %d", kwork_id)
                break

            reviews = data.get("data", {}).get("reviews", [])
            if not reviews:
                break

            if total is None:
                total = (
                    data.get("data", {}).get("goodReviews", 0)
                    if review_type == "positive"
                    else data.get("data", {}).get("badReviews", 0)
                )

            for review in reviews:
                r_user_id = review.get("USERID")
                r_username = review.get("username", "")
                if r_user_id and r_username:
                    try:
                        upsert_user(db, int(r_user_id), r_username)
                    except (ValueError, TypeError):
                        pass

                insert_review(
                    db,
                    {
                        "id": review.get("order_id", 0),
                        "kwork_id": kwork_id,
                        "user_id": int(r_user_id) if r_user_id else None,
                        "type": (
                            "positive" if review.get("good") == "1" else "negative"
                        ),
                        "time_added": review.get("time_added", 0),
                        "comment": review.get("comment", ""),
                    },
                )

            scraped += len(reviews)
            logger.info(
                "Scraping %s reviews of %d: %d/%d ",
                review_type,
                kwork_id,
                scraped,
                total or 0,
            )

            offset += limit
            if total is not None and offset >= total:
                break


# --- Main orchestration ---


def process_category(session: httpx.Client, db, slug: str, filters: dict[str, str]):
    category_id = get_db_category_id_by_slug(db, slug)
    if category_id is None:
        logger.error("Category slug '%s' not found in database", slug)
        return

    logger.info("Processing category: %s (id=%d)", slug, category_id)

    page = 1
    exclude_ids: list[int] = []
    total_kworks: int | None = None
    scraped: set[int] = set()
    api_filters = dict(filters)

    while True:
        random_delay()

        result = fetch_catalog_page(session, slug, page, exclude_ids, api_filters)
        if not result or not result.get("success"):
            logger.error("Catalog request failed for '%s' page %d", slug, page)
            break

        view_data = result.get("data", {}).get("stateData", {}).get("viewData", {})
        kworks_data = view_data.get("kworks", {})

        if total_kworks is None:
            total_kworks = kworks_data.get("total", 0)
            logger.info("Total kworks for %s: %d", slug, total_kworks)

        posts = kworks_data.get("posts", {}).get("data", [])
        if not posts:
            break

        for post in posts:
            kwork_id = post.get("id")
            kwork_url = post.get("url")
            if not kwork_id or not kwork_url:
                continue

            exclude_ids.append(kwork_id)

            if kwork_id in scraped:
                continue

            random_delay()
            logger.info(
                "Scraping kwork %d: %d/%d",
                kwork_id,
                len(scraped) + 1,
                total_kworks,
            )
            scrape_kwork_page(session, kwork_url, category_id, db)
            scrape_reviews(session, kwork_id, db)
            scraped.add(kwork_id)

        logger.info(
            "Category %s progress: %d/%d kworks scraped",
            slug,
            len(scraped),
            total_kworks,
        )

        if len(scraped) >= total_kworks:
            break

        page += 1

    logger.info("Finished category %s: %d kworks scraped", slug, len(scraped))


def main():
    global _delay_min, _delay_max

    setup_logging()
    args = parse_args()

    _delay_min, _delay_max = args.delay

    if not args.categories:
        logger.error("No categories specified. Use -c to specify categories.")
        sys.exit(1)

    db = init_db(args.database)

    filters = {}
    for f in args.filters:
        if "=" in f:
            k, v = f.split("=", 1)
            filters[k] = v
        else:
            logger.warning("Invalid filter format: %s (expected key=value)", f)

    # Load headerMenu and parse category tree
    logger.info("Loading categories from kwork.ru...")
    session = create_http_client()
    try:
        header_menu = load_categories(session)
    finally:
        session.close()

    if not header_menu:
        logger.error("Failed to load categories from website")
        sys.exit(1)

    tree = parse_category_tree(header_menu)
    tree = store_category_tree(db, tree)
    logger.info("Loaded %d categories from website", len(tree))

    queue = validate_and_deduplicate_categories(args.categories, tree)
    if not queue:
        logger.error("No valid categories to scrape")
        sys.exit(1)

    logger.info("Categories to scrape: %s", ", ".join(queue))

    for slug in queue:
        logger.info("=" * 60)
        session = create_http_client()
        try:
            process_category(session, db, slug, filters)
        except Exception:
            logger.exception("Error processing category '%s'", slug)
        finally:
            session.close()

    logger.info("=" * 60)
    logger.info("Done! All categories processed.")


if __name__ == "__main__":
    main()
