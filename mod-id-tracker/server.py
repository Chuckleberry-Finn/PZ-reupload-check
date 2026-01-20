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

# Paths / constants
PZ_APP_ID = "108600"

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


# Existing search endpoints
def fetch_url(url: str, timeout: int = 15, max_retries: int = 2):
    """Fetch URL with retry logic"""
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
                return content.decode("utf-8", errors="ignore"), 200, None
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
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

def search_workshop(mod_id: str, max_pages: int = 5):
    results = []
    seen = set()
    consecutive_empty = 0
    max_consecutive_empty = 2

    for page in range(1, max_pages + 1):
        url = f"https://steamcommunity.com/workshop/browse/?appid={PZ_APP_ID}&searchtext=%22Mod+ID%3A+{urllib.parse.quote(mod_id)}%22&browsesort=mostrecent&section=&actualsort=mostrecent&p={page}"
        print(f"[Search] Fetching page {page}/{max_pages} for '{mod_id}'...")

        html_content, status_code, error = fetch_url(url, timeout=20)

        if status_code in (403, 429):
            print(f"[Search] Rate limited on page {page}")
            return None, {"error": "Steam blocked/rate-limited the request.", "statusCode": status_code}

        if not html_content:
            print(f"[Search] No content returned for page {page}")
            consecutive_empty += 1
            if consecutive_empty >= max_consecutive_empty:
                print(f"[Search] Stopping after {consecutive_empty} empty pages")
                break
            time.sleep(1.0)
            continue

        if "g-recaptcha" in html_content or "captcha" in html_content.lower():
            print(f"[Search] CAPTCHA detected")
            return None, {"error": "Steam is showing a CAPTCHA challenge. Wait then retry.", "statusCode": 503}

        item_pattern = r'data-publishedfileid="(\d+)"[^>]*>.*?<div class="workshopItemTitle[^"]*">([^<]+)</div>'
        matches = re.findall(item_pattern, html_content, re.DOTALL)

        if not matches:
            alt_pattern = r'sharedfiles/filedetails/\?id=(\d+)"[^>]*>.*?<div[^>]*workshopItemTitle[^>]*>([^<]+)</div>'
            matches = re.findall(alt_pattern, html_content, re.DOTALL)

        page_found = 0
        for workshop_id, title in matches:
            if workshop_id not in seen:
                seen.add(workshop_id)
                results.append({
                    "workshopId": workshop_id,
                    "title": title.strip(),
                    "url": f"https://steamcommunity.com/sharedfiles/filedetails/?id={workshop_id}"
                })
                page_found += 1

        if page_found > 0:
            consecutive_empty = 0
            print(f"[Search] Found {page_found} items on page {page} (total: {len(results)})")
        else:
            consecutive_empty += 1
            print(f"[Search] No items on page {page} (empty count: {consecutive_empty})")
            if consecutive_empty >= max_consecutive_empty:
                print(f"[Search] Stopping search - no results on last {consecutive_empty} pages")
                break

        delay = 0.5 if page_found > 0 else 0.3
        if page < max_pages:
            time.sleep(delay)

    print(f"[Search] Complete - found {len(results)} total items for '{mod_id}'")
    return results, None

def check_workshop_exists(workshop_id: str):
    """Check if workshop item exists"""
    url = f"https://steamcommunity.com/sharedfiles/filedetails/?id={workshop_id}"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            if 'class="error_ctn"' in html:
                if "There was a problem accessing the item" in html:
                    return False, None
                if "This item has been removed" in html:
                    return False, None
            title = None
            m = re.search(r'<div class="workshopItemTitle">([^<]+)</div>', html)
            if m:
                title = m.group(1).strip()
            has_content = ("workshopItemTitle" in html) or ("workshopItemDescription" in html)
            return has_content, title
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, None
        return True, None
    except:
        return True, None

def extract_mod_id(workshop_id: str):
    """Extract Mod ID from workshop item page"""
    url = f"https://steamcommunity.com/sharedfiles/filedetails/?id={workshop_id}"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

            # Look for "Mod ID: xxxxx" pattern in description
            patterns = [
                r'Mod ID:\s*([A-Za-z0-9_\-]+)',
                r'ModID:\s*([A-Za-z0-9_\-]+)',
                r'mod\s*id:\s*([A-Za-z0-9_\-]+)',
            ]

            for pattern in patterns:
                match = re.search(pattern, html, re.IGNORECASE)
                if match:
                    return match.group(1).strip(), None

            return None, "Mod ID not found in description"
    except Exception as e:
        return None, str(e)

def search_profile_workshop(profile_input: str, max_pages: int = 10):
    """Search for workshop items from a Steam profile"""
    # Parse profile input to get profile ID
    profile_id = profile_input.strip()

    # Extract from URL if needed
    if "steamcommunity.com" in profile_id:
        # Extract ID from URL
        id_match = re.search(r'/id/([^/]+)', profile_id)
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
        # Try custom URL first, then numeric ID
        if profile_id.isdigit():
            url = f"https://steamcommunity.com/profiles/{profile_id}/myworkshopfiles/?appid={PZ_APP_ID}&p={page}"
        else:
            url = f"https://steamcommunity.com/id/{profile_id}/myworkshopfiles/?appid={PZ_APP_ID}&p={page}"

        print(f"[Profile] Fetching page {page}/{max_pages} from {profile_id}...")

        html_content, status_code, error = fetch_url(url, timeout=20)

        if status_code in (403, 429):
            rate_limit_count += 1
            if rate_limit_count > max_rate_limit_retries:
                print(f"[Profile] Rate limit exceeded {max_rate_limit_retries} times, aborting")
                return None, {"error": "Steam rate limit exceeded after multiple retries.", "statusCode": status_code}

            # Progressive delay: 5s, then 10s, then 15s
            delay = 5 * rate_limit_count
            print(f"[Profile] Rate limited (attempt {rate_limit_count}/{max_rate_limit_retries}), waiting {delay} seconds...")
            time.sleep(delay)
            continue  # Retry same page

        # Reset rate limit counter on success
        if html_content:
            rate_limit_count = 0

        if not html_content:
            print(f"[Profile] No content returned for page {page}")
            break

        if "g-recaptcha" in html_content or "captcha" in html_content.lower():
            print(f"[Profile] CAPTCHA detected")
            return None, {"error": "Steam is showing a CAPTCHA challenge. Wait then retry.", "statusCode": 503}

        # Parse workshop items from profile page
        item_pattern = r'data-publishedfileid="(\d+)"[^>]*>.*?<div class="workshopItemTitle[^"]*">([^<]+)</div>'
        matches = re.findall(item_pattern, html_content, re.DOTALL)

        if not matches:
            alt_pattern = r'sharedfiles/filedetails/\?id=(\d+)"[^>]*>.*?<div[^>]*workshopItemTitle[^>]*>([^<]+)</div>'
            matches = re.findall(alt_pattern, html_content, re.DOTALL)

        page_found = 0
        for workshop_id, title in matches:
            if workshop_id not in seen:
                seen.add(workshop_id)
                results.append({
                    "workshopId": workshop_id,
                    "title": title.strip(),
                    "url": f"https://steamcommunity.com/sharedfiles/filedetails/?id={workshop_id}"
                })
                page_found += 1

        print(f"[Profile] Found {page_found} items on page {page} (total: {len(results)})")

        if page_found == 0:
            break

        # Normal delay between successful requests
        if page < max_pages:
            time.sleep(0.5)

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