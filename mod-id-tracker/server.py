#!/usr/bin/env python3
import os
import sys
import re
import json
import time
import urllib.parse
import urllib.request
import urllib.error
import platform
import subprocess
import shutil
from pathlib import Path
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from threading import Thread, Lock
from collections import deque

# ============================================================================
# STEAM RATE LIMITER
# Dynamically throttles requests to stay under Steam's rate limits
# ============================================================================
class SteamRateLimiter:
    """
    Rate limiter that tracks requests per minute and enforces delays.
    Steam's rate limits are not publicly documented, but appear to be:
    - ~10-15 requests per minute for workshop searches
    - Stricter limits during peak hours or if recently rate-limited
    """
    
    def __init__(self, max_requests_per_minute=10, min_delay_seconds=4.0):
        self.max_rpm = max_requests_per_minute
        self.min_delay = min_delay_seconds
        self.request_times = deque(maxlen=100)  # Track last 100 requests
        self.lock = Lock()
        self.backoff_multiplier = 1.0
        self.last_rate_limit_time = 0
        
    def wait_if_needed(self):
        """Wait if necessary to stay under rate limits"""
        with self.lock:
            now = time.time()
            
            # Remove requests older than 60 seconds
            cutoff = now - 60
            while self.request_times and self.request_times[0] < cutoff:
                self.request_times.popleft()
            
            # Check if we've hit rate limits recently (within last 5 minutes)
            if now - self.last_rate_limit_time < 300:  # 5 minutes
                # Apply backoff: reduce to 70% of normal rate
                effective_max = int(self.max_rpm * 0.7)
            else:
                effective_max = self.max_rpm
            
            # If we're at the limit, calculate how long to wait
            if len(self.request_times) >= effective_max:
                oldest = self.request_times[0]
                wait_until = oldest + 60
                wait_time = max(0, wait_until - now)
                
                if wait_time > 0:
                    print(f"[RateLimiter] Reached {len(self.request_times)} requests/min limit. Waiting {wait_time:.1f}s...")
                    time.sleep(wait_time)
                    now = time.time()
            
            # Apply minimum delay between requests
            if self.request_times:
                time_since_last = now - self.request_times[-1]
                adjusted_delay = self.min_delay * self.backoff_multiplier
                
                if time_since_last < adjusted_delay:
                    wait_time = adjusted_delay - time_since_last
                    print(f"[RateLimiter] Minimum delay: waiting {wait_time:.1f}s...")
                    time.sleep(wait_time)
                    now = time.time()
            
            # Record this request
            self.request_times.append(now)
            
            # Show current rate for monitoring
            rpm = len(self.request_times)
            print(f"[RateLimiter] Request sent. Current rate: {rpm} requests/min (limit: {effective_max})")
    
    def mark_rate_limited(self):
        """Call this when a 403/429 error occurs to increase backoff"""
        with self.lock:
            self.last_rate_limit_time = time.time()
            self.backoff_multiplier = min(2.0, self.backoff_multiplier * 1.5)
            print(f"[RateLimiter] Rate limited! Increasing backoff to {self.backoff_multiplier:.2f}x")
    
    def reset_backoff(self):
        """Reset backoff after successful requests"""
        with self.lock:
            if self.backoff_multiplier > 1.0:
                self.backoff_multiplier = max(1.0, self.backoff_multiplier * 0.9)

# Global rate limiter instance
steam_rate_limiter = SteamRateLimiter(
    max_requests_per_minute=10,  # Conservative limit
    min_delay_seconds=4.0         # 4 seconds between requests
)

# Paths / constants
PZ_APP_ID = "108600"

# Workshop item IDs that are actually static Steam page-chrome links, not
# real search results. These show up in the raw HTML/JSON of every browse
# and profile page regardless of search terms (e.g. the "Learn More" link
# to the Modding Policy in the workshop header), so they're filtered out
# defensively wherever items are collected.
KNOWN_NON_RESULT_WORKSHOP_IDS = {
    "2872282653",  # Spiffo's Workshop "Learn More" -> Modding Policy page
}

if getattr(sys, "frozen", False):
    ROOT_DIR = Path(sys._MEIPASS)
else:
    ROOT_DIR = Path(__file__).resolve().parent

PUBLIC_DIR = ROOT_DIR / "public"
VERIFY_DIR = ROOT_DIR / "verify"
TMP_VERIFY_DIR = ROOT_DIR / "_tmp_verify"

VERIFY_CONFIG_FILE = VERIFY_DIR / "verify_config.ini"
MANIFEST_DIR = VERIFY_DIR / "manifests"

DEPOT_DEFAULT_PATHS = [
    Path("C:/DepotDownloader/DepotDownloader.exe"),
    Path("C:/Program Files/DepotDownloader/DepotDownloader.exe"),
    Path.home() / "DepotDownloader" / "DepotDownloader.exe",
    Path("/usr/local/bin/DepotDownloader"),
    Path("/usr/bin/DepotDownloader"),
    Path.home() / "DepotDownloader" / "DepotDownloader",
    ]

# Configuration
def load_verify_config():
    import configparser
    config = configparser.ConfigParser()
    if VERIFY_CONFIG_FILE.exists():
        config.read(VERIFY_CONFIG_FILE)
    return config

def save_verify_config(config):
    import configparser
    VERIFY_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(VERIFY_CONFIG_FILE, 'w') as f:
        config.write(f)

def find_depotdownloader():
    """Find DepotDownloader executable"""
    # Check config file first
    config = load_verify_config()
    if config.has_option('Paths', 'depotdownloader'):
        path = Path(config.get('Paths', 'depotdownloader'))
        if path.exists():
            return path

    # Check common paths
    for path in DEPOT_DEFAULT_PATHS:
        if path.exists():
            return path

    # Check PATH
    depot_in_path = shutil.which('DepotDownloader')
    if depot_in_path:
        return Path(depot_in_path)

    return None

def set_depotdownloader_path(path_str: str):
    """Save DepotDownloader path to config"""
    import configparser
    config = load_verify_config()
    if not config.has_section('Paths'):
        config.add_section('Paths')
    config.set('Paths', 'depotdownloader', path_str)
    save_verify_config(config)


def get_steam_username():
    """Steam username DepotDownloader should log in as (if configured).

    DepotDownloader cannot piggyback on an already-open Steam client's
    session - it's a standalone SteamKit2 process with its own connection
    to Steam. If anonymous access to this app's workshop content stops
    working, the only way forward is a real login. See set_steam_username
    below for the one-time setup this requires.
    """
    config = load_verify_config()
    if config.has_option('Steam', 'username'):
        name = config.get('Steam', 'username').strip()
        return name or None
    return None

def set_steam_username(username_str: str):
    """Save the Steam username DepotDownloader should use.

    This alone is NOT enough to authenticate: DepotDownloader still needs
    a one-time interactive login run from an actual terminal/console (not
    through this web UI, since that subprocess has no real stdin/stdout
    for a password + Steam Guard prompt):

        DepotDownloader -app 108600 -username <username> -remember-password

    Complete the password entry and Steam Guard confirmation there once.
    DepotDownloader then caches a login key locally, and every future run
    (including the ones this server spawns) can log in silently with just
    -username <username> - no password needed again unless that cached
    session is later revoked.

    Before reaching for this at all, see get_workshop_app_id() below -
    "login failed" symptoms are often actually an outdated DepotDownloader
    mis-resolving manifest codes for shared/proxied depots, not a real
    anonymous-access lockout.
    """
    config = load_verify_config()
    if not config.has_section('Steam'):
        config.add_section('Steam')
    config.set('Steam', 'username', username_str.strip())
    save_verify_config(config)


def get_workshop_app_id():
    """AppID passed to DepotDownloader's -app for workshop manifest requests.

    Defaults to PZ_APP_ID, overridable via [Workshop] app_id in
    verify_config.ini.

    DepotDownloader resolves the manifest-request app id differently
    depending on whether the app you pass to -app is itself flagged
    FreeToDownload on Steam, when the actual depot is a shared/proxied
    one (DepotFromApp): non-free apps use the depot's real source app,
    free-to-download apps use the app id you passed in directly. Builds
    older than 3.1.0 had this backwards for the free-app case ("Fixed
    getting manifest code for FreeToDownload apps that use DepotFromApp"),
    which produces the exact same "Login failed" / "not subscribed"
    output as a genuine anonymous-access lockout, with no account issue
    at all. If PZ's workshop depot is proxied from a different
    free-to-download app, point this at that app's id instead.
    """
    config = load_verify_config()
    if config.has_option('Workshop', 'app_id'):
        app_id = config.get('Workshop', 'app_id').strip()
        return app_id or PZ_APP_ID
    return PZ_APP_ID

def set_workshop_app_id(app_id_str: str):
    """Save an override app id for workshop manifest requests."""
    config = load_verify_config()
    if not config.has_section('Workshop'):
        config.add_section('Workshop')
    config.set('Workshop', 'app_id', app_id_str.strip())
    save_verify_config(config)


# Existing search endpoints
def fetch_url(url: str, timeout: int = 15, max_retries: int = 2):
    """Fetch URL with retry logic and rate limiting"""
    # Apply rate limiting before the request
    steam_rate_limiter.wait_if_needed()
    
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate",
                "Connection": "keep-alive",
                "Cache-Control": "max-age=0",
            })
            with urllib.request.urlopen(req, timeout=timeout) as response:
                content = response.read()
                # Handle gzip encoding
                if response.headers.get('Content-Encoding') == 'gzip':
                    import gzip
                    content = gzip.decompress(content)
                
                # Reset backoff on successful request
                steam_rate_limiter.reset_backoff()
                return content.decode("utf-8", errors="ignore"), 200, None
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                steam_rate_limiter.mark_rate_limited()
                print(f"[Fetch] HTTP {e.code} (rate limit or blocked)")
                return None, e.code, str(e.reason)
            if attempt < max_retries - 1:
                print(f"[Fetch] HTTP {e.code}, retrying... ({attempt + 1}/{max_retries})")
                time.sleep(1.0 * (attempt + 1))
                continue
            return None, e.code, str(e.reason)
        except urllib.error.URLError as e:
            if attempt < max_retries - 1:
                print(f"[Fetch] URLError, retrying... ({attempt + 1}/{max_retries})")
                time.sleep(1.0 * (attempt + 1))
                continue
            return None, 0, str(e.reason)
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"[Fetch] Error: {e}, retrying... ({attempt + 1}/{max_retries})")
                time.sleep(1.0 * (attempt + 1))
                continue
            return None, 0, str(e)

    return None, 0, "Max retries exceeded"


def _extract_ssr_render_context(html_content: str):
    """Pull Steam's embedded TanStack-Query hydration state out of the page.

    Steam's current SSR frontend ships a line like:

        window.SSR.renderContext=JSON.parse("{...escaped JSON...}");

    That JSON blob contains a `queryData` field (itself a JSON string) with
    every server-fetched query result for the page - including the exact
    workshop_browse / myworkshopfiles results array, already structured,
    with no CSS classes to keep up with. Class names in the rendered HTML
    (e.g. what used to be "_3rvey4VpXts-") are build-hashed and can change
    on every Steam frontend deploy, so we prefer this JSON source and only
    fall back to HTML scraping if it's missing.
    """
    m = re.search(
        r'window\.SSR\.renderContext\s*=\s*JSON\.parse\("(.*?)"\);',
        html_content,
        re.DOTALL,
    )
    if not m:
        return None
    try:
        raw = m.group(1)
        # `raw` is already JSON-escaped exactly like a JSON string body,
        # so wrapping it in quotes and decoding once unescapes it back to
        # plain text, and json.loads-ing that gives us the real object.
        outer = json.loads('"' + raw + '"')
        return json.loads(outer) if isinstance(outer, str) else outer
    except Exception as e:
        print(f"[Parse] Failed to decode SSR renderContext: {e}")
        return None


def _parse_workshop_items_from_html(html_content: str):
    """Extract workshop items (and total page count, if known) from a page.

    Returns (items, total_pages). total_pages is None if it couldn't be
    determined (older/plain HTML fallback paths).
    """
    items = []
    seen = set()
    total_pages = None

    ctx = _extract_ssr_render_context(html_content)
    if ctx:
        try:
            qd_raw = ctx.get("queryData")
            qd = json.loads(qd_raw) if isinstance(qd_raw, str) else (qd_raw or {})
            for q in qd.get("queries", []):
                data = (q.get("state") or {}).get("data")
                if isinstance(data, dict) and isinstance(data.get("results"), list):
                    if data.get("total_pages") is not None:
                        total_pages = data.get("total_pages")
                    for r in data["results"]:
                        wid = str(r.get("publishedfileid") or "").strip()
                        if wid and wid not in seen:
                            seen.add(wid)
                            items.append({
                                "workshopId": wid,
                                "title": (r.get("title") or "").strip() or f"Workshop Item {wid}",
                                "url": f"https://steamcommunity.com/sharedfiles/filedetails/?id={wid}",
                                "author": str(r.get("creator") or "") or None,
                                "shortDescription": (r.get("short_description") or "").strip() or None,
                                "subscriptions": r.get("subscriptions"),
                                "timeUpdated": r.get("time_updated"),
                            })
        except Exception as e:
            print(f"[Parse] JSON extraction failed, will try HTML fallback: {e}")

    if items:
        return items, total_pages

    # Fallback 1: current title-div class as of this writing. Steam hashes
    # these per-build so this WILL drift again - it's a safety net, not
    # the primary path.
    for wid, title in re.findall(
        r'class="Sw3NXcvOA4Y-"><a[^>]+\?id=(\d+)[^>]*>([^<]+)<',
        html_content,
    ):
        if wid not in seen:
            seen.add(wid)
            items.append({
                "workshopId": wid,
                "title": title.strip() or f"Workshop Item {wid}",
                "url": f"https://steamcommunity.com/sharedfiles/filedetails/?id={wid}",
            })

    # Fallback 2: img alt text next to filedetails link.
    if not items:
        for wid, title in re.findall(
            r'filedetails/\?id=(\d+)"[^>]*><img[^>]+alt="([^"]+)"',
            html_content,
        ):
            if wid not in seen:
                seen.add(wid)
                items.append({
                    "workshopId": wid,
                    "title": title.strip() or f"Workshop Item {wid}",
                    "url": f"https://steamcommunity.com/sharedfiles/filedetails/?id={wid}",
                })

    # Fallback 3: classic (pre-SSR-redesign) profile workshop-files page.
    # /profiles/<id>/myworkshopfiles/ (and /id/<vanity>/myworkshopfiles/)
    # still serve Steam's long-standing legacy template - no window.SSR
    # JSON blob at all, and none of the new /workshop/browse/ page's
    # build-hashed classes exist here.
    if not items:
        # 3a (preferred): each item's hover script calls
        # SharedFileBindMouseHover("sharedfile_<id>", <bool>, {json}) with
        # a clean JSON object - id, title, description, appid. This is
        # more reliable than scraping the surrounding HTML/classes at all,
        # same reasoning as preferring the browse page's SSR JSON blob.
        pattern = r'SharedFileBindMouseHover\(\s*"sharedfile_\d+"\s*,\s*\w+\s*,\s*(\{.*?\})\s*\)\s*;'
        for m in re.finditer(pattern, html_content, re.DOTALL):
            try:
                obj = json.loads(m.group(1))
            except Exception:
                continue
            wid = str(obj.get("id") or "").strip()
            if not wid or wid in seen:
                continue
            seen.add(wid)
            items.append({
                "workshopId": wid,
                "title": (obj.get("title") or "").strip() or f"Workshop Item {wid}",
                "url": f"https://steamcommunity.com/sharedfiles/filedetails/?id={wid}",
                "shortDescription": (obj.get("description") or "").strip() or None,
            })
        if items:
            print(f"[Parse] Found {len(items)} item(s) via legacy page's SharedFileBindMouseHover data.")

        # 3b (fallback): if the hover-script data isn't present for some
        # reason, scope to each "workshopItem" block and pull the id
        # (from the filedetails link on the preview thumbnail) and title
        # (from the sibling "workshopItemTitle" div - note this class
        # often has extra modifiers appended, e.g. "workshopItemTitle
        # ellipsis", so the match can't require an exact class value).
        # These are SIBLING elements, not nested in one another. (This
        # page has no "Learn More" policy-link chrome like the browse
        # page, so scoping to workshopItem blocks doesn't reintroduce the
        # earlier false-positive risk from an unscoped link grab.)
        if not items:
            for block in re.split(r'(?=class="workshopItem")', html_content):
                if 'class="workshopItem"' not in block:
                    continue
                id_match = re.search(r'filedetails/\?id=(\d+)', block)
                if not id_match:
                    continue
                wid = id_match.group(1)
                if wid in seen:
                    continue
                title_match = re.search(r'class="workshopItemTitle[^"]*"[^>]*>([^<]+)<', block)
                title = title_match.group(1).strip() if title_match else ""
                seen.add(wid)
                items.append({
                    "workshopId": wid,
                    "title": title or f"Workshop Item {wid}",
                    "url": f"https://steamcommunity.com/sharedfiles/filedetails/?id={wid}",
                })
            if items:
                print(f"[Parse] Found {len(items)} item(s) via legacy workshopItem block scan.")

        if items:
            # Legacy pagination: "Showing 1-9 of 28 entries" tells us the
            # real total so callers can stop at the right page instead of
            # guessing from empty-page streaks.
            m = re.search(r'of\s+([\d,]+)\s+entries', html_content)
            if m:
                total_entries = int(m.group(1).replace(",", ""))
                per_page = max(len(items), 1)
                total_pages = -(-total_entries // per_page)  # ceil div

    # NOTE: there used to be a Fallback here that grabbed *any*
    # sharedfiles/filedetails/?id=... link on the page as a last resort.
    # That's unsafe: Steam's workshop header always contains a static
    # "Learn More" link to the Modding Policy page (id=2872282653), plus
    # other page-chrome links, none of which are search results. When a
    # search legitimately returned zero real matches, that fallback would
    # silently report the policy page (or other chrome) as a "found" item.
    # A clean zero-results is far safer than a false positive here, so we
    # deliberately don't grab unscoped links anymore.
    if not items:
        print("[Parse] No items found via JSON or scoped HTML fallbacks "
              "- treating as a genuine zero-result page.")

    # Belt-and-suspenders: filter out known Steam page-chrome IDs even if
    # they somehow slipped through one of the paths above.
    if items:
        items = [it for it in items if it["workshopId"] not in KNOWN_NON_RESULT_WORKSHOP_IDS]

    return items, total_pages


def search_workshop(mod_id: str, max_pages: int = 5):
    """Search the Workshop browse page for items matching 'Mod ID: <mod_id>'.

    Parses Steam's new SSR JSON-embedded HTML format instead of old CSS classes.
    """
    results = []
    seen = set()
    consecutive_empty = 0
    max_consecutive_empty = 2

    for page in range(1, max_pages + 1):
        url = (
            f"https://steamcommunity.com/workshop/browse/"
            f"?appid={PZ_APP_ID}"
            f"&searchtext=%22Mod+ID%3A+{urllib.parse.quote(mod_id)}%22"
            f"&browsesort=mostrecent&section=readytouseitems"
            f"&actualsort=mostrecent&p={page}"
        )
        print(f"[Search] Fetching page {page}/{max_pages} for '{mod_id}'...")

        html_content, status_code, error = fetch_url(url, timeout=20)

        if status_code in (403, 429):
            return None, {"error": "Steam blocked/rate-limited the request.", "statusCode": status_code}

        if not html_content:
            consecutive_empty += 1
            if consecutive_empty >= max_consecutive_empty:
                break
            time.sleep(1.0)
            continue

        if "g-recaptcha" in html_content or "captcha" in html_content.lower():
            return None, {"error": "Steam is showing a CAPTCHA challenge. Wait then retry.", "statusCode": 503}

        items, total_pages = _parse_workshop_items_from_html(html_content)
        page_found = 0
        for item in items:
            if item["workshopId"] not in seen:
                seen.add(item["workshopId"])
                results.append(item)
                page_found += 1

        if page_found > 0:
            consecutive_empty = 0
            print(f"[Search] Found {page_found} items on page {page} (total: {len(results)})")
        else:
            consecutive_empty += 1
            print(f"[Search] No items on page {page} (empty count: {consecutive_empty})")
            if consecutive_empty >= max_consecutive_empty:
                break

        # Steam tells us the real page count now - stop as soon as we've
        # covered it instead of guessing from empty-page streaks.
        if total_pages is not None and page >= total_pages:
            print(f"[Search] Reached last page ({total_pages}) per Steam's own count.")
            break

    print(f"[Search] Complete - found {len(results)} total items for '{mod_id}'")
    return results, None

def check_workshop_exists(workshop_id: str):
    """Check if workshop item exists using GetPublishedFileDetails API."""
    data, error = _get_published_file_details([workshop_id])
    if error or not data:
        return True, None  # Assume exists on error
    files = data.get("response", {}).get("publishedfiledetails", [])
    if not files:
        return False, None
    f = files[0]
    # result=9 means item doesn't exist / removed
    if f.get("result", 1) != 1:
        return False, None
    title = f.get("title", "").strip() or None
    return True, title

def _get_published_file_details(workshop_ids: list):
    """Batch-fetch file details from ISteamRemoteStorage/GetPublishedFileDetails."""
    steam_rate_limiter.wait_if_needed()
    params = {"itemcount": len(workshop_ids)}
    for i, wid in enumerate(workshop_ids):
        params[f"publishedfileids[{i}]"] = wid
    data = urllib.parse.urlencode(params).encode()
    url = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Mozilla/5.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            steam_rate_limiter.reset_backoff()
            return json.loads(resp.read().decode("utf-8", errors="ignore")), None
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            steam_rate_limiter.mark_rate_limited()
        return None, f"HTTP {e.code}"
    except Exception as e:
        return None, str(e)


def extract_mod_id(workshop_id: str):
    """Extract Mod ID from a workshop item's description via API."""
    data, error = _get_published_file_details([workshop_id])
    if error or not data:
        return None, error or "API request failed"
    files = data.get("response", {}).get("publishedfiledetails", [])
    if not files or files[0].get("result", 1) != 1:
        return None, "Workshop item not found or removed"
    description = files[0].get("description", "") or ""
    patterns = [
        r'Mod\s*ID:\s*([A-Za-z0-9_\-]+)',
        r'ModID:\s*([A-Za-z0-9_\-]+)',
        r'mod\s*id:\s*([A-Za-z0-9_\-]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, description, re.IGNORECASE)
        if match:
            return match.group(1).strip(), None
    return None, "Mod ID not found in description"

def get_workshop_full_details(workshop_id: str):
    """Fetch full workshop item details via Steam API."""
    data, error = _get_published_file_details([workshop_id])
    if error or not data:
        return {
            "exists": True,
            "workshopId": workshop_id,
            "title": None, "author": None, "modIds": [],
            "error": error or "API request failed"
        }
    files = data.get("response", {}).get("publishedfiledetails", [])
    if not files or files[0].get("result", 1) != 1:
        return {
            "exists": False,
            "workshopId": workshop_id,
            "error": "Workshop item not found or removed"
        }

    f = files[0]
    title = f.get("title", "").strip() or None
    # creator_appid steam_id -> we can surface the creator's steamid
    creator = str(f.get("creator", "") or "")
    description = f.get("description", "") or ""

    # Extract all Mod IDs from description (plain text, no HTML tags)
    mod_ids = []
    seen_mod_ids = set()
    mod_id_patterns = [
        r'Mod\s*ID:\s*([A-Za-z0-9_\-]+)',
        r'ModID:\s*([A-Za-z0-9_\-]+)',
        r'Mod\s*IDs?:\s*([A-Za-z0-9_\-,\s]+?)(?:\r|\n|$)',
    ]
    for pattern in mod_id_patterns:
        for match in re.findall(pattern, description, re.IGNORECASE):
            for mod_id in match.split(','):
                mod_id = mod_id.strip()
                if mod_id and len(mod_id) <= 100 and mod_id.lower() not in seen_mod_ids:
                    seen_mod_ids.add(mod_id.lower())
                    mod_ids.append(mod_id)

    return {
        "exists": True,
        "workshopId": workshop_id,
        "title": title,
        "author": creator,   # steamid64; front-end only uses for display
        "modIds": mod_ids
    }

def search_profile_workshop(profile_input: str, max_pages: int = 10):
    """Fetch workshop items from a Steam profile page.

    Parses Steam's new SSR JSON-embedded HTML. Accepts a Steam64 ID,
    vanity URL name, or full steamcommunity.com URL.
    """
    profile_id = profile_input.strip()

    if "steamcommunity.com" in profile_id:
        id_match = re.search(r'/id/([^/?#]+)', profile_id)
        profiles_match = re.search(r'/profiles/(\d+)', profile_id)
        if id_match:
            profile_id = id_match.group(1)
        elif profiles_match:
            profile_id = profiles_match.group(1)

    results = []
    seen = set()
    rate_limit_count = 0
    max_rate_limit_retries = 3

    page = 1
    while page <= max_pages:
        # numperpage=30 is the highest value this legacy page template
        # accepts (9 is the default) - cuts the number of pages needed
        # for profiles with a lot of submissions roughly 3x.
        if profile_id.isdigit():
            url = f"https://steamcommunity.com/profiles/{profile_id}/myworkshopfiles/?appid={PZ_APP_ID}&p={page}&numperpage=30"
        else:
            url = f"https://steamcommunity.com/id/{profile_id}/myworkshopfiles/?appid={PZ_APP_ID}&p={page}&numperpage=30"

        print(f"[Profile] Fetching page {page}/{max_pages} from {profile_id}...")

        html_content, status_code, error = fetch_url(url, timeout=20)

        if status_code in (403, 429):
            rate_limit_count += 1
            if rate_limit_count > max_rate_limit_retries:
                return None, {"error": "Steam rate limit exceeded after multiple retries.", "statusCode": status_code}
            delay = 5 * rate_limit_count
            print(f"[Profile] Rate limited, waiting {delay}s...")
            time.sleep(delay)
            continue

        if html_content:
            rate_limit_count = 0

        if not html_content:
            break

        if "g-recaptcha" in html_content or "captcha" in html_content.lower():
            return None, {"error": "Steam is showing a CAPTCHA challenge. Wait then retry.", "statusCode": 503}

        items, total_pages = _parse_workshop_items_from_html(html_content)
        page_found = 0
        for item in items:
            if item["workshopId"] not in seen:
                seen.add(item["workshopId"])
                results.append(item)
                page_found += 1

        print(f"[Profile] Found {page_found} items on page {page} (total: {len(results)})")

        if page_found == 0:
            break

        if total_pages is not None and page >= total_pages:
            print(f"[Profile] Reached last page ({total_pages}).")
            break

        page += 1

    print(f"[Profile] Complete - found {len(results)} total items from profile")
    return results, None

# VERIFY state
verification_lock = Lock()
verification_state = {
    "running": False,
    "should_stop": False,
    "progress": None,
    "results": None,
    "error": None
}

def start_verification_job(payload: dict):
    """Background job to run verification and track progress"""
    with verification_lock:
        verification_state["running"] = True
        verification_state["should_stop"] = False
        verification_state["progress"] = {"type": "start", "message": "Verification started"}
        verification_state["results"] = None
        verification_state["error"] = None

    try:
        tracked_mods = payload.get("trackedMods", []) or []
        entries = payload.get("entries", []) or []

        print(f"[VERIFY] Starting with {len(tracked_mods)} tracked mods and {len(entries)} DMCA entries")

        if not entries:
            _set_progress("error", {"message": "No DMCA entries provided"}, done=True)
            with verification_lock:
                verification_state["running"] = False
            return

        # Build export format
        export = {
            "exportedAt": datetime.utcnow().isoformat() + "Z",
            "exportVersion": 1,
            "trackedMods": tracked_mods,
            "entries": entries
        }

        # Write temp JSON
        os.makedirs(TMP_VERIFY_DIR, exist_ok=True)
        tmp_in = TMP_VERIFY_DIR / f"dmca_export_{int(time.time())}.json"
        with open(tmp_in, "w", encoding="utf-8") as f:
            json.dump(export, f, indent=2, ensure_ascii=False)

        print(f"[VERIFY] Wrote input file: {tmp_in} ({tmp_in.stat().st_size} bytes)")

        # Find verifier - use DepotDownloader version
        verifier_path = VERIFY_DIR / "verify_dmca.py"
        if not verifier_path.exists():
            verifier_path = ROOT_DIR / "verify_dmca.py"
        if not verifier_path.exists():
            verifier_path = Path(__file__).parent / "verify" / "verify_dmca.py"
        if not verifier_path.exists():
            verifier_path = Path(__file__).parent / "verify_dmca.py"

        if not verifier_path.exists():
            raise FileNotFoundError(f"Could not find verify_dmca.py. Checked: {VERIFY_DIR}, {ROOT_DIR}, {Path(__file__).parent}")

        print(f"[VERIFY] Using verifier: {verifier_path}")
        print(f"[VERIFY] Python executable: {sys.executable}")

        # Use the same Python interpreter
        cmd = [sys.executable, str(verifier_path), "--dmca-export", str(tmp_in)]

        print(f"[VERIFY] Running command: {' '.join(cmd)}")
        _set_progress("running", {"message": "Starting verification process..."}, done=False)

        # Set environment to force UTF-8 encoding
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'

        # Spawn process
        start_time = time.time()
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace',  # Replace encoding errors with ?
            bufsize=1,
            universal_newlines=True,
            env=env
        )

        # Read output line by line
        stdout_lines = []
        stderr_lines = []

        try:
            stdout, stderr = proc.communicate(timeout=600)  # 10 minute timeout
            stdout_lines = stdout.splitlines() if stdout else []
            stderr_lines = stderr.splitlines() if stderr else []
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            stdout_lines = stdout.splitlines() if stdout else []
            stderr_lines = stderr.splitlines() if stderr else []
            raise Exception("Verification timed out after 10 minutes")
        except Exception as e:
            # Handle any other communication errors
            print(f"[VERIFY] Communication error: {e}")
            raise

        elapsed = time.time() - start_time
        print(f"[VERIFY] Process completed in {elapsed:.1f}s with return code: {proc.returncode}")

        # Log all output
        if stdout_lines:
            print(f"[VERIFY] STDOUT ({len(stdout_lines)} lines):")
            for line in stdout_lines:
                print(f"  {line}")

        if stderr_lines:
            print(f"[VERIFY] STDERR ({len(stderr_lines)} lines):")
            for line in stderr_lines:
                print(f"  {line}")

        if proc.returncode != 0:
            error_msg = "\n".join(stderr_lines) if stderr_lines else "Process failed with no error output"
            raise Exception(f"Verification process failed (exit code {proc.returncode}): {error_msg}")

        # Read back the modified file
        if not tmp_in.exists():
            raise FileNotFoundError(f"Output file not found: {tmp_in}")

        print(f"[VERIFY] Reading output file: {tmp_in} ({tmp_in.stat().st_size} bytes)")

        with open(tmp_in, "r", encoding="utf-8") as f:
            output_data = json.load(f)

        verified_entries = output_data.get("entries", [])
        print(f"[VERIFY] Loaded {len(verified_entries)} verified entries from output file")

        if not verified_entries:
            raise Exception("No entries found in verification output - verification may have failed")

        # Check if any entries actually have verification data
        verified_count = sum(1 for e in verified_entries if e.get("verification"))
        print(f"[VERIFY] {verified_count}/{len(verified_entries)} entries have verification data")

        # Build summary from entries
        summary = {"high": 0, "medium": 0, "low": 0, "none": 0, "takenDown": 0}
        for entry in verified_entries:
            v = entry.get("verification", {})
            if v.get("takenDown"):
                summary["takenDown"] += 1
            elif v.get("verified"):
                pct = v.get("matchPercentage", 0)
                if pct >= 75:
                    summary["high"] += 1
                elif pct >= 50:
                    summary["medium"] += 1
                elif pct >= 25:
                    summary["low"] += 1
                else:
                    summary["none"] += 1

        print(f"[VERIFY] Summary: {summary}")

        # CRITICAL FIX: Set results BEFORE setting progress to complete
        with verification_lock:
            verification_state["results"] = {
                "entries": verified_entries,
                "summary": summary
            }

        _set_progress("complete", {"summary": summary}, done=True)
        print(f"[VERIFY] Results set in state, entries count: {len(verified_entries)}")

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"[VERIFY] ERROR:")
        print(error_details)
        _set_progress("error", {"message": str(e)}, done=True)
        with verification_lock:
            verification_state["error"] = str(e)

    finally:
        with verification_lock:
            verification_state["running"] = False


def _set_progress(type_: str, payload: dict, done: bool = False):
    with verification_lock:
        verification_state["progress"] = {
            "type": type_,
            "payload": payload,
            "time": datetime.utcnow().isoformat() + "Z",
            "done": done
        }
        if type_ == "error":
            verification_state["error"] = payload

def _should_stop():
    with verification_lock:
        return verification_state["should_stop"]

# HTTP server
class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

class RequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"[HTTP] {args[0]}")

    def send_json(self, data: dict, status: int = 200):
        response = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(response)

    def send_file(self, filepath: Path):
        if not filepath.exists():
            self.send_error(404, "File not found")
            return

        ext = filepath.suffix.lower()
        content_types = {
            ".html": "text/html",
            ".css": "text/css",
            ".js": "application/javascript",
            ".json": "application/json",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".svg": "image/svg+xml",
            ".ico": "image/x-icon",
        }
        content_type = content_types.get(ext, "application/octet-stream")

        data = filepath.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        content_len = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_len) if content_len else b"{}"
        try:
            payload = json.loads(body.decode("utf-8"))
        except:
            payload = {}

        if path == "/api/verify/start":
            with verification_lock:
                if verification_state["running"]:
                    self.send_json({"error": "Verification already running"}, 409)
                    return

            entries = payload.get("entries") or []
            if not entries:
                self.send_json({"error": "No DMCA entries found (add via +DMCA first)", "code": "NO_DMCA"}, 400)
                return

            # Check if DepotDownloader is configured
            depot_path = find_depotdownloader()
            if not depot_path:
                self.send_json({
                    "error": "DepotDownloader not configured",
                    "code": "NO_DEPOT",
                    "message": "Please configure DepotDownloader path in settings"
                }, 400)
                return

            t = Thread(target=start_verification_job, args=(payload,), daemon=True)
            t.start()

            self.send_json({"ok": True, "message": "Verification started"})
            return

        if path == "/api/verify/stop":
            with verification_lock:
                verification_state["should_stop"] = True
            self.send_json({"ok": True, "message": "Stopping..."})
            return

        if path == "/api/config/depot-path":
            depot_path_str = payload.get("path", "").strip()
            if not depot_path_str:
                self.send_json({"error": "No path provided"}, 400)
                return

            depot_path = Path(depot_path_str)
            if not depot_path.exists():
                self.send_json({"error": "File not found", "path": depot_path_str}, 404)
                return

            set_depotdownloader_path(depot_path_str)
            self.send_json({"ok": True, "path": depot_path_str, "message": "DepotDownloader path saved"})
            return

        if path == "/api/config/steam-username":
            username_str = payload.get("username", "").strip()
            if not username_str:
                self.send_json({"error": "No username provided"}, 400)
                return

            set_steam_username(username_str)
            self.send_json({
                "ok": True,
                "username": username_str,
                "message": (
                    "Username saved. This alone doesn't log you in - DepotDownloader can't "
                    "reuse an already-open Steam client's session. Run this once from a real "
                    "terminal (not through this web UI) to complete the login and Steam "
                    f"Guard prompt: DepotDownloader -app {PZ_APP_ID} -username {username_str} "
                    "-remember-password"
                ),
            })
            return

        if path == "/api/config/workshop-app-id":
            app_id_str = payload.get("appId", "").strip()
            if not app_id_str:
                self.send_json({"error": "No appId provided"}, 400)
                return

            set_workshop_app_id(app_id_str)
            self.send_json({
                "ok": True,
                "appId": app_id_str,
                "message": (
                    f"Workshop app id for manifest requests set to {app_id_str}. Try this "
                    "(and updating DepotDownloader to >= 3.1.0) before setting up a real Steam "
                    "login - 'Login failed'/'not subscribed' errors on a shared/proxied depot "
                    "are often just a manifest-code resolution issue, not an actual account "
                    "lockout."
                ),
            })
            return

        self.send_json({"error": "Unknown POST route"}, 404)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/api/verify/status":
            with verification_lock:
                self.send_json({
                    "running": verification_state["running"],
                    "progress": verification_state["progress"],
                    "results": verification_state["results"],
                    "error": verification_state["error"]
                })
            return

        if path == "/api/config/depot-path":
            depot_path = find_depotdownloader()
            self.send_json({
                "configured": depot_path is not None,
                "path": str(depot_path) if depot_path else None
            })
            return

        if path == "/api/config/steam-username":
            username = get_steam_username()
            self.send_json({
                "configured": username is not None,
                "username": username,
            })
            return

        if path == "/api/config/workshop-app-id":
            self.send_json({
                "appId": get_workshop_app_id(),
                "isDefault": get_workshop_app_id() == PZ_APP_ID,
            })
            return

        if path == "/api/modid-search-all":
            mod_id = query.get("modId", [""])[0]
            max_pages = int(query.get("maxPages", ["5"])[0])
            if not mod_id:
                self.send_json({"error": "Missing modId parameter"}, 400)
                return

            items, error = search_workshop(mod_id, max_pages)
            if error:
                self.send_json(error, error.get("statusCode", 500))
            else:
                self.send_json({"modId": mod_id, "count": len(items), "items": items})
            return

        if path == "/api/check-workshop-exists":
            workshop_id = query.get("workshopId", [""])[0]
            if not workshop_id:
                self.send_json({"error": "Missing workshopId parameter"}, 400)
                return

            exists, title = check_workshop_exists(workshop_id)
            self.send_json({
                "workshopId": workshop_id,
                "exists": exists,
                "title": title
            })
            return

        if path == "/api/profile-workshop":
            profile_id = query.get("profileId", [""])[0]
            max_pages = int(query.get("maxPages", ["10"])[0])
            if not profile_id:
                self.send_json({"error": "Missing profileId parameter"}, 400)
                return

            items, error = search_profile_workshop(profile_id, max_pages)
            if error:
                self.send_json(error, error.get("statusCode", 500))
            else:
                self.send_json({"profileId": profile_id, "count": len(items), "items": items})
            return

        if path == "/api/workshop-details":
            workshop_id = query.get("workshopId", [""])[0]
            if not workshop_id:
                self.send_json({"error": "Missing workshopId parameter"}, 400)
                return

            mod_id, error = extract_mod_id(workshop_id)
            self.send_json({
                "workshopId": workshop_id,
                "modId": mod_id,
                "error": error
            })
            return

        if path == "/api/workshop-full-details":
            workshop_id = query.get("workshopId", [""])[0]
            if not workshop_id:
                self.send_json({"error": "Missing workshopId parameter"}, 400)
                return

            details = get_workshop_full_details(workshop_id)
            self.send_json(details)
            return

        if path == "/" or path == "":
            return self.send_file(PUBLIC_DIR / "index.html")

        static_path = (PUBLIC_DIR / path.lstrip("/")).resolve()
        if str(static_path).startswith(str(PUBLIC_DIR.resolve())) and static_path.exists():
            return self.send_file(static_path)

        self.send_error(404, "Not found")

def run_server(host="127.0.0.1", port=8000):
    if not PUBLIC_DIR.exists():
        print(f"[ERROR] Missing public dir: {PUBLIC_DIR}")
        print("Expected: mod-id-tracker/public/index.html")
        return

    server = ThreadedHTTPServer((host, port), RequestHandler)
    print(f"Server running: http://{host}:{port}")
    server.serve_forever()

if __name__ == "__main__":
    import webbrowser

    host = "127.0.0.1"
    port = 3000

    if getattr(sys, "frozen", False):
        def open_browser():
            time.sleep(2)
            try:
                webbrowser.open(f"http://localhost:{port}")
                print(f"\n[INFO] Browser opened to http://localhost:{port}")
            except:
                print(f"\n[INFO] Could not auto-open browser. Please visit: http://localhost:{port}")

        browser_thread = Thread(target=open_browser, daemon=True)
        browser_thread.start()

    run_server(host, port)
