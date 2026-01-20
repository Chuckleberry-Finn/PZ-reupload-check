#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Project Zomboid DMCA Verification Tool (DepotDownloader Version)
"""

import os
import sys
import json
import argparse
import subprocess
import shutil
import urllib.request
import urllib.error
import re
import time
import configparser
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional

PZ_APP_ID = "108600"
CONFIG_FILE = Path(__file__).parent / "verify_config.ini"

DEPOT_DEFAULT_PATHS = [
    Path("C:/DepotDownloader/DepotDownloader.exe"),
    Path("C:/Program Files/DepotDownloader/DepotDownloader.exe"),
    Path.home() / "DepotDownloader" / "DepotDownloader.exe",
    Path("/usr/local/bin/DepotDownloader"),
    Path("/usr/bin/DepotDownloader"),
    Path.home() / "DepotDownloader" / "DepotDownloader",
    ]

# Global log file handle
LOG_FILE = None

def log(msg):
    """Write to log file instead of stdout to avoid encoding issues"""
    if LOG_FILE:
        try:
            LOG_FILE.write(msg + '\n')
            LOG_FILE.flush()
        except:
            pass

def load_config():
    config = configparser.ConfigParser()
    if CONFIG_FILE.exists():
        config.read(CONFIG_FILE)
    return config

def save_config(config):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, 'w') as f:
        config.write(f)

def find_depotdownloader(interactive=False):
    config = load_config()
    if config.has_option('Paths', 'depotdownloader'):
        path = Path(config.get('Paths', 'depotdownloader'))
        if path.exists():
            log(f"[Config] Using DepotDownloader: {path}")
            return path

    for path in DEPOT_DEFAULT_PATHS:
        if path.exists():
            log(f"[Auto] Found DepotDownloader: {path}")
            if not config.has_section('Paths'):
                config.add_section('Paths')
            config.set('Paths', 'depotdownloader', str(path))
            save_config(config)
            return path

    depot_in_path = shutil.which('DepotDownloader')
    if depot_in_path:
        path = Path(depot_in_path)
        log(f"[Auto] Found DepotDownloader in PATH: {path}")
        if not config.has_section('Paths'):
            config.add_section('Paths')
        config.set('Paths', 'depotdownloader', str(path))
        save_config(config)
        return path

    if interactive:
        log("\n" + "=" * 70)
        log("DEPOTDOWNLOADER NOT FOUND")
        log("=" * 70)
        log("\nDownload from: https://github.com/SteamRE/DepotDownloader/releases\n")
    return None

def get_depot_dir(depot_path):
    return depot_path.parent / "depots" / PZ_APP_ID

def get_manifest_mapping_file(depot_dir):
    return depot_dir / "manifest_mapping.json"

def load_manifest_mapping(depot_dir):
    mapping_file = get_manifest_mapping_file(depot_dir)
    if mapping_file.exists():
        try:
            with open(mapping_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            log(f"[Warning] Failed to load manifest mapping: {e}")
            return {}
    return {}

def save_manifest_mapping(depot_dir, mapping):
    mapping_file = get_manifest_mapping_file(depot_dir)
    depot_dir.mkdir(parents=True, exist_ok=True)
    with open(mapping_file, 'w', encoding='utf-8') as f:
        json.dump(mapping, f, indent=2)

def check_workshop_exists(workshop_id):
    url = f"https://steamcommunity.com/sharedfiles/filedetails/?id={workshop_id}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as response:
            html = response.read().decode('utf-8', errors='ignore')
            if 'error_ctn' in html and ('problem accessing' in html or 'removed' in html):
                return False, None
            title_match = re.search(r'<div class="workshopItemTitle">([^<]+)</div>', html)
            title = title_match.group(1).strip() if title_match else None
            has_content = 'workshopItemTitle' in html or 'workshopItemDescription' in html
            return has_content, title
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, None
        return True, None
    except Exception as e:
        log(f"[Warning] Error checking workshop {workshop_id}: {e}")
        return True, None

def find_manifest_for_workshop(depot_dir, workshop_id):
    mapping = load_manifest_mapping(depot_dir)
    if workshop_id in mapping:
        manifest_path = depot_dir / mapping[workshop_id]
        if manifest_path.exists():
            return manifest_path
        del mapping[workshop_id]
        save_manifest_mapping(depot_dir, mapping)

    if not depot_dir.exists():
        return None

    for build_dir in depot_dir.iterdir():
        if not build_dir.is_dir():
            continue
        for manifest_file in build_dir.glob("manifest_*.txt"):
            try:
                with open(manifest_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = ''.join([next(f, '') for _ in range(500)])
                if workshop_id in content:
                    mapping[workshop_id] = str(manifest_file.relative_to(depot_dir))
                    save_manifest_mapping(depot_dir, mapping)
                    return manifest_file
            except:
                continue
    return None

def parse_manifest_fast(manifest_content):
    hashes = {}
    lines = manifest_content.split('\n')
    data_start = 0
    for i, line in enumerate(lines):
        if 'Size' in line and 'Chunks' in line and 'File SHA' in line:
            data_start = i + 1
            break
    if not data_start:
        return hashes
    for line in lines[data_start:]:
        parts = line.strip().split()
        if len(parts) < 5:
            continue
        try:
            size, hash_val, flags = int(parts[0]), parts[2], int(parts[3])
            filename = ' '.join(parts[4:])
            if flags in (40, 64, 0x40) or hash_val == '0'*40 or size == 0:
                continue
            if len(hash_val) == 40 and all(c in '0123456789abcdefABCDEF' for c in hash_val):
                hashes[hash_val.lower()] = filename
        except:
            continue
    return hashes

def download_workshop_manifest(depot_path, workshop_id, depot_dir, timeout=300):
    existing = set()
    if depot_dir.exists():
        for bd in depot_dir.iterdir():
            if bd.is_dir():
                existing.update(bd.glob("manifest_*.txt"))

    start_time = time.time()
    cmd = [str(depot_path), '-app', PZ_APP_ID, '-pubfile', workshop_id, '-manifest-only']

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=depot_path.parent)
        output = result.stdout + result.stderr

        if 'No subscription' in output or 'not subscribed' in output.lower():
            return False, "Not subscribed", None
        if 'Login' in output and 'FAILED' in output:
            return False, "Login failed", None

        if 'manifest' in output.lower():
            new_or_updated = []
            if depot_dir.exists():
                for bd in depot_dir.iterdir():
                    if bd.is_dir():
                        for mf in bd.glob("manifest_*.txt"):
                            if mf not in existing or mf.stat().st_mtime >= start_time - 5:
                                new_or_updated.append(mf)

            if new_or_updated:
                new_or_updated.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                manifest_path = new_or_updated[0]
                mapping = load_manifest_mapping(depot_dir)
                mapping[workshop_id] = str(manifest_path.relative_to(depot_dir))
                save_manifest_mapping(depot_dir, mapping)
                return True, None, manifest_path
        return False, "Unknown error", None
    except subprocess.TimeoutExpired:
        return False, "Timeout", None
    except Exception as e:
        return False, str(e), None

def compare_hashes(original, suspect):
    matched = set(original.keys()) & set(suspect.keys())
    return len(matched), len(original), [original[h] for h in matched]

def main():
    global LOG_FILE

    parser = argparse.ArgumentParser()
    parser.add_argument('--dmca-export', required=True)
    parser.add_argument('--depot-path')
    parser.add_argument('--pending-only', action='store_true')
    parser.add_argument('--show-config', action='store_true')
    parser.add_argument('--clear-cache', action='store_true')
    args = parser.parse_args()

    # Create log file next to the export file
    dmca_path = Path(args.dmca_export)
    log_path = dmca_path.parent / f"{dmca_path.stem}_verify.log"
    LOG_FILE = open(log_path, 'w', encoding='utf-8')

    try:
        log(f"[VERIFY] Starting verification process")
        log(f"[VERIFY] Python version: {sys.version}")
        log(f"[VERIFY] Working directory: {os.getcwd()}")

        depot_path = Path(args.depot_path) if args.depot_path else find_depotdownloader(interactive=False)
        if not depot_path:
            log("ERROR: DepotDownloader not found")
            raise Exception("DepotDownloader not found")

        log(f"[VERIFY] DepotDownloader path: {depot_path}")

        depot_dir = get_depot_dir(depot_path)
        log(f"[VERIFY] Depot directory: {depot_dir}")

        if args.clear_cache:
            if depot_dir.exists():
                mapping_file = get_manifest_mapping_file(depot_dir)
                if mapping_file.exists():
                    mapping_file.unlink()
                shutil.rmtree(depot_dir)
                log("Cache cleared")
            return

        if args.show_config:
            log(f"DepotDownloader: {depot_path}")
            log(f"Depot dir: {depot_dir}")
            if depot_dir.exists():
                mapping = load_manifest_mapping(depot_dir)
                log(f"Mapped items: {len(mapping)}")
            return

        log(f"[VERIFY] Input file: {dmca_path}")

        if not dmca_path.exists():
            log(f"ERROR: Input file does not exist: {dmca_path}")
            raise Exception(f"Input file not found: {dmca_path}")

        log(f"[VERIFY] Reading input file...")
        with open(dmca_path, 'r', encoding='utf-8') as f:
            dmca_data = json.load(f)
        log(f"[VERIFY] Successfully loaded JSON")

        entries = dmca_data.get('entries', [])
        log(f"[VERIFY] Found {len(entries)} entries in input")

        if args.pending_only:
            entries = [e for e in entries if not e.get('filedDate') and not e.get('takenDownDate')]
            log(f"[VERIFY] Filtered to {len(entries)} pending entries")

        tracked_mods = {m['modId']: m['workshopId'] for m in dmca_data.get('trackedMods', [])
                        if m.get('modId') and m.get('workshopId')}
        log(f"[VERIFY] Found {len(tracked_mods)} tracked mods")

        needed_mods = set()
        for e in entries:
            needed_mods.update(e.get('containsModIds', []))

        log(f"[VERIFY] Need {len(needed_mods)} original mods for comparison")

        all_items = {}
        for mod_id, ws_id in tracked_mods.items():
            if mod_id in needed_mods:
                all_items[ws_id] = ('original', mod_id)
        for e in entries:
            if e['workshopId'] not in all_items:
                # Use ASCII-safe representation for logging
                title = e.get('title', 'Unknown')
                safe_title = title.encode('ascii', errors='replace').decode('ascii')
                all_items[e['workshopId']] = ('suspect', safe_title)

        log(f"\n[Download] Processing {len(all_items)} workshop items...")
        workshop_to_manifest = {}

        for i, (ws_id, (item_type, name)) in enumerate(all_items.items(), 1):
            log(f"[{i}/{len(all_items)}] {item_type.upper()}: {name} ({ws_id})")

            manifest_path = find_manifest_for_workshop(depot_dir, ws_id)
            if manifest_path:
                log(f"  [CACHED] {manifest_path.name}")
                workshop_to_manifest[ws_id] = manifest_path
                continue

            exists, _ = check_workshop_exists(ws_id)
            if not exists:
                log(f"  [SKIP] Item removed")
                continue

            success, error, manifest_path = download_workshop_manifest(depot_path, ws_id, depot_dir)
            if success and manifest_path:
                workshop_to_manifest[ws_id] = manifest_path
                log(f"  [DOWNLOADED] {manifest_path.name}")
                time.sleep(2)
            else:
                log(f"  [ERROR] {error}")

        log(f"\n[Read] Parsing {len(workshop_to_manifest)} manifests...")
        workshop_hashes = {}
        for ws_id, manifest_path in workshop_to_manifest.items():
            try:
                content = manifest_path.read_text(encoding='utf-8', errors='ignore')
                hashes = parse_manifest_fast(content)
                workshop_hashes[ws_id] = hashes
                log(f"  {ws_id}: {len(hashes)} files")
            except Exception as e:
                log(f"  {ws_id}: ERROR - {e}")
                workshop_hashes[ws_id] = {}

        original_hashes = {}
        for mod_id, ws_id in tracked_mods.items():
            if mod_id in needed_mods and ws_id in workshop_hashes:
                original_hashes[mod_id] = workshop_hashes[ws_id]

        log(f"\n[Verify] Comparing {len(entries)} suspects...")
        verified_count = 0

        for i, entry in enumerate(entries, 1):
            ws_id = entry['workshopId']
            title = entry.get('title', 'Unknown')
            safe_title = title.encode('ascii', errors='replace').decode('ascii')
            log(f"[{i}/{len(entries)}] {safe_title}")

            suspect_hashes = workshop_hashes.get(ws_id, {})
            if not suspect_hashes:
                entry['verification'] = {'verified': False, 'error': 'No manifest'}
                log(f"  SKIP: No manifest found")
                continue

            mod_results = {}
            total_matched, total_files = 0, 0

            for mod_id in entry.get('containsModIds', []):
                if mod_id not in original_hashes:
                    continue
                matched, total, files = compare_hashes(original_hashes[mod_id], suspect_hashes)
                pct = round(matched / total * 100, 1) if total > 0 else 0
                mod_results[mod_id] = {
                    'matchPercentage': pct,
                    'matchedFiles': matched,
                    'totalFiles': total,
                    'sampleMatches': files[:5]
                }
                total_matched += matched
                total_files += total
                log(f"  {mod_id}: {pct}% ({matched}/{total})")

            overall_pct = round(total_matched / total_files * 100, 1) if total_files > 0 else 0
            entry['verification'] = {
                'verified': True,
                'matchPercentage': overall_pct,
                'matchedFiles': total_matched,
                'totalFiles': total_files,
                'verifiedDate': datetime.utcnow().isoformat() + 'Z',
                'modResults': mod_results
            }
            verified_count += 1
            log(f"  OVERALL: {overall_pct}%")

        log(f"\n[VERIFY] Writing results back to {dmca_path}...")
        with open(dmca_path, 'w', encoding='utf-8') as f:
            json.dump(dmca_data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        log(f"[VERIFY] Successfully wrote {dmca_path.stat().st_size} bytes")

        high = len([e for e in entries if e.get('verification', {}).get('matchPercentage', 0) >= 75])
        med = len([e for e in entries if 50 <= e.get('verification', {}).get('matchPercentage', 0) < 75])
        low = len([e for e in entries if 25 <= e.get('verification', {}).get('matchPercentage', 0) < 50])
        none_match = len([e for e in entries if e.get('verification', {}).get('matchPercentage', 0) < 25])

        log(f"\n{'='*70}")
        log("VERIFICATION COMPLETE")
        log(f"{'='*70}")
        log(f"Verified:     {verified_count}/{len(entries)}")
        log(f"High (75%+):  {high}")
        log(f"Medium:       {med}")
        log(f"Low:          {low}")
        log(f"None:         {none_match}")
        log(f"\nOutput saved: {dmca_path}")
        log(f"File size: {dmca_path.stat().st_size} bytes")

        # Print success to stdout so server knows it worked
        print("VERIFICATION_COMPLETE")

    except Exception as e:
        log(f"\nFATAL ERROR: {e}")
        import traceback
        log(traceback.format_exc())
        raise
    finally:
        if LOG_FILE:
            LOG_FILE.close()

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        # Print simple error to stdout
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)