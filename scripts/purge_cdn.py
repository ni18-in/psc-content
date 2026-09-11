#!/usr/bin/env python3
"""
jsDelivr CDN Cache Purger for State PSC Content Bank.
Purges cached files across global edge caches (Cloudflare, Fastly) using the official jsDelivr Purge API.

Usage:
    python scripts/purge_cdn.py [--exam bpsc] [--branch main] [--repo ni18-in/psc-content]
    python scripts/purge_cdn.py --all
"""

import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error

PURGE_API_BASE = "https://purge.jsdelivr.net"

def get_git_repo():
    """Attempt to detect github user/repo from git remote."""
    try:
        out = subprocess.check_output(
            ["git", "remote", "get-url", "origin"],
            stderr=subprocess.DEVNULL,
            universal_newlines=True
        ).strip()
        match = re.search(r"github\.com[:/]([^/]+/[^/]+?)(\.git)?$", out)
        if match:
            return match.group(1)
    except Exception:
        pass
    return "ni18-in/psc-content"

def get_git_branch():
    """Attempt to detect current git branch."""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL,
            universal_newlines=True
        ).strip()
        if out and out != "HEAD":
            return out
    except Exception:
        pass
    return "main"

def purge_single_file(repo, branch, rel_path):
    """Purge a single file path through jsDelivr purge API."""
    url = f"{PURGE_API_BASE}/gh/{repo}@{branch}/{rel_path.replace(os.sep, '/')}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "PSC-Content-Purger/1.0"},
        method="GET"
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            data = json.loads(response.read().decode("utf-8"))
            status = data.get("status", "unknown")
            return {
                "path": rel_path,
                "url": url,
                "status": status,
                "success": status in ("finished", "pending"),
                "raw": data
            }
    except urllib.error.HTTPError as e:
        return {
            "path": rel_path,
            "url": url,
            "status": f"HTTP {e.code}",
            "success": False,
            "error": str(e)
        }
    except Exception as e:
        return {
            "path": rel_path,
            "url": url,
            "status": "Error",
            "success": False,
            "error": str(e)
        }

def collect_files_to_purge(root_dir, exam_filter=None):
    """Collect relative file paths for exams."""
    files_to_purge = []
    exams_dir = os.path.join(root_dir, "exams")
    if not os.path.exists(exams_dir):
        print(f"[ERROR] 'exams' directory not found at: {exams_dir}")
        return []

    for root, _, files in os.walk(exams_dir):
        for f in files:
            if f.endswith(".json"):
                full_path = os.path.join(root, f)
                rel_path = os.path.relpath(full_path, root_dir)
                parts = rel_path.replace(os.sep, "/").split("/")
                # parts: ['exams', '<exam_id>', ...]
                if len(parts) >= 2:
                    current_exam = parts[1]
                    if exam_filter and current_exam.lower() != exam_filter.lower():
                        continue
                files_to_purge.append(rel_path.replace(os.sep, "/"))

    return sorted(files_to_purge)

def main():
    parser = argparse.ArgumentParser(
        description="Purge jsDelivr CDN cache for State PSC Content Bank"
    )
    parser.add_argument(
        "--repo",
        default=None,
        help="GitHub repo (e.g. ni18-in/psc-content or nitinkanade/psc-content)"
    )
    parser.add_argument(
        "--branch",
        default=None,
        help="Git branch or tag (default: current branch or main)"
    )
    parser.add_argument(
        "--exam",
        default=None,
        help="Specific exam to purge (e.g. bpsc, tnpsc, mpsc). If omitted, purges all exams."
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=6,
        help="Concurrent purge workers (default: 6)"
    )

    args = parser.parse_args()

    # Determine script root
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(script_dir, ".."))

    repo = args.repo or get_git_repo()
    branch = args.branch or get_git_branch()
    exam = args.exam

    print("=" * 65)
    print("      State PSC Content jsDelivr CDN Cache Purger")
    print("=" * 65)
    print(f" Repository : {repo}")
    print(f" Branch/Tag : {branch}")
    print(f" Exam Target: {exam if exam else 'ALL EXAMS'}")
    print("=" * 65)

    files = collect_files_to_purge(repo_root, exam_filter=exam)
    if not files:
        print("[WARN] No JSON files found to purge.")
        sys.exit(0)

    print(f"Discovered {len(files)} files to purge from jsDelivr CDN edge caches...")
    start_time = time.time()
    success_count = 0
    fail_count = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(purge_single_file, repo, branch, f): f for f in files
        }
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res["success"]:
                success_count += 1
                print(f"  [PURGED] {res['path']}")
            else:
                fail_count += 1
                err_msg = res.get("error") or res.get("status")
                print(f"  [FAILED] {res['path']} -> {err_msg}")

    elapsed = round(time.time() - start_time, 2)
    print("=" * 65)
    print(f" Summary: {success_count}/{len(files)} purged successfully in {elapsed}s")
    if fail_count > 0:
        print(f" [WARN] {fail_count} file(s) encountered warnings or errors.")
        sys.exit(1)
    else:
        print(" [SUCCESS] All CDN edge caches invalidated. Fresh content is now live!")
        sys.exit(0)

if __name__ == "__main__":
    main()
