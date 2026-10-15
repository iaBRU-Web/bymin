#!/usr/bin/env python3
"""
Bymin - All-in-one dir buster / subdomain buster / admin page finder
Runs on Colab. Interactive. Uses large SecLists wordlists (auto-downloaded).

Modes:
  -f : path busting       (example.com/way)
  -b : subdomain busting  (admin.example.com)
  -a : flag, admin-hunt wordlists layered on top of -f or -b
"""

import sys, os, socket, ssl, time, urllib.request, urllib.error, random, string
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------------- CONFIG ----------------
WORDDIR = "/root/bymin_wordlists"
SECLISTS_URL = "https://github.com/danielmiessler/SecLists/archive/refs/heads/master.zip"
THREADS = 40
TIMEOUT = 8
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

# 40+ large wordlists from SecLists (paths relative to repo root)
PATH_LISTS = [
    "Discovery/Web-Content/common.txt",
    "Discovery/Web-Content/big.txt",
    "Discovery/Web-Content/raft-large-files.txt",
    "Discovery/Web-Content/raft-large-directories.txt",
    "Discovery/Web-Content/raft-large-words.txt",
    "Discovery/Web-Content/directory-list-2.3-medium.txt",
    "Discovery/Web-Content/directory-list-lowercase-2.3-medium.txt",
    "Discovery/Web-Content/DirBuster-2007_directory-list-lowercase-2.3.txt",
    "Discovery/Web-Content/quickhits.txt",
    "Discovery/Web-Content/Combined%20Wordlists%20Optimized.7z".replace("%20", " "),
    "Discovery/Web-Content/admin-panels.txt",
    "Discovery/Web-Content/AdminPanels/admin-panels.txt",
    "Discovery/Web-Content/ConstellationsAdmin.txt",
    "Discovery/Web-Content/CMS.txt",
    "Discovery/Web-Content/WordPress.fuzz.txt",
    "Discovery/Web-Content/Joomla.fuzz.txt",
    "Discovery/Web-Content/Drupal.fuzz.txt",
    "Discovery/Web-Content/apache.txt",
    "Discovery/Web-Content/nginx.txt",
    "Discovery/Web-Content/iis.txt",
    "Discovery/Web-Content/tomcat.txt",
    "Discovery/Web-Content/oracle.txt",
    "Discovery/Web-Content/websphere.txt",
    "Discovery/Web-Content/jboss.txt",
    "Discovery/Web-Content/jenkins.txt",
    "Discovery/Web-Content/gitlab.txt",
    "Discovery/Web-Content/graphql.txt",
    "Discovery/Web-Content/config.php.txt",
    "Discovery/Web-Content/bak.txt",
    "Discovery/Web-Content/log.txt",
    "Discovery/Web-Content/backup.txt",
    "Discovery/Web-Content/db.txt",
    "Discovery/Web-Content/archive.txt",
    "Discovery/Web-Content/debug.txt",
    "Discovery/Web-Content/api.txt",
    "Discovery/Web-Content/swagger.txt",
    "Discovery/Web-Content/dev.txt",
    "Discovery/Web-Content/staging.txt",
    "Discovery/Web-Content/test.txt",
    "Discovery/Web-Content/upload.txt",
    "Discovery/Web-Content/uploads.txt",
    "Discovery/Web-Content/phpinfo.txt",
    "Discovery/Web-Content/shell.txt",
    "Discovery/Web-Content/RobotsDisallowed/top1000.txt",
    "Discovery/Web-Content/URLs/urls-with-extension-all-dirs.txt",
]
ADMIN_LISTS = [
    "Discovery/Web-Content/admin-panels.txt",
    "Discovery/Web-Content/AdminPanels/admin-panels.txt",
    "Discovery/Web-Content/ ConstellationsAdmin.txt".strip(),
    "Discovery/Web-Content/manager.txt",
    "Discovery/Web-Content/admin.txt",
    "Discovery/Web-Content/login.txt",
    "Discovery/Web-Content/cpanel.txt",
    "Discovery/Web-Content/django.txt",
    "Discovery/Web-Content/laravel.txt",
    "Discovery/Web-Content/springboot.txt",
]
SUBDOMAIN_LISTS = [
    "Discovery/DNS/subdomains-top1million-5000.txt",
    "Discovery/DNS/subdomains-top1million-20000.txt",
    "Discovery/DNS/subdomains-top1million-110000.txt",
    "Discovery/DNS/deepmine.txt",
    "Discovery/DNS/fierce-hostlists.txt",
    "Discovery/DNS/n0m1s.txt",
    "Discovery/DNS/combined_subdomains.txt",
    "Discovery/DNS/bitquark-subdomains-top100000.txt",
    "Discovery/DNS/namelist.txt",
    "Discovery/DNS/dns-Jhaddix.txt",
    "Discovery/DNS/bug-bounty-logs/thc-org-subdomains-wildcard.txt",
    "Discovery/DNS/bug-bounty-logs/bugcrowd-txt-subdomains-wildcard.txt",
]

# ---------------- WORDLIST DOWNLOAD ----------------
def download_wordlists(mode, admin):
    os.makedirs(WORDDIR, exist_ok=True)
    zippath = os.path.join(WORDDIR, "seclists.zip")
    src = os.path.join(WORDDIR, "SecLists-master")
    if not os.path.isdir(src):
        print("[*] Downloading SecLists (large, one time ~100MB)...")
        if not os.path.exists(zippath):
            urllib.request.urlretrieve(SECLISTS_URL, zippath)
        import zipfile
        with zipfile.ZipFile(zippath) as z:
            z.extractall(WORDDIR)
        os.remove(zippath)
    lists = []
    if mode == "-b":
        lists += SUBDOMAIN_LISTS
    else:
        lists += PATH_LISTS
    if admin:
        lists += ADMIN_LISTS
    files = []
    seen = set()
    for rel in lists:
        p = os.path.join(src, rel)
        if os.path.isfile(p) and p not in seen:
            seen.add(p)
            files.append(p)
        elif not os.path.isfile(p):
            print(f"[!] missing list: {rel}")
    return files

def load_words(files, host_for_dns=None):
    words = set()
    total = 0
    for f in files:
        try:
            with open(f, "r", errors="ignore") as fh:
                for line in fh:
                    w = line.strip()
                    if not w or w.startswith("#"):
                        continue
                    if host_for_dns:  # subdomain mode: strip wildcards, validate chars
                        w = w.split(".")[0].lower()
                        if not w or not all(c in string.ascii_lowercase + string.digits + "-" for c in w):
                            continue
                    if len(w) > 60:
                        continue
                    words.add(w)
                    total += 1
        except Exception as e:
            print(f"[!] read error {f}: {e}")
    print(f"[*] Loaded {total} raw entries -> {len(words)} unique words")
    return list(words)

# ---------------- PROGRESS BAR ----------------
def bar(done, total, hits, width=40):
    pct = done / total if total else 0
    filled = int(width * pct)
    print("\r|" + "=" * filled + " " * (width - filled) +
          f"| {pct:.0%} [{done}/{total}] hits:{hits}", end="", flush=True)

# ---------------- BASELINE / SOFT-404 DETECTION ----------------
def fetch(url):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
            body = r.read(4096)
            return r.status, len(body), body
    except urllib.error.HTTPError as e:
        return e.code, 0, b""
    except Exception:
        return None, 0, b""

def get_baseline(base_url):
    rnd = "".join(random.choices(string.ascii_lowercase, k=24))
    code, length, body = fetch(f"{base_url}/{rnd}")
    print(f"[*] Baseline random path -> status={code} len={length}")
    return code, length, body

# ---------------- PATH BUSTER (-f) ----------------
def bust_paths(base_url, words, baseline):
    bl_code, bl_len, bl_body = baseline
    hits = []
    total = len(words)
    done = 0
    lock_hits = []
    print(f"[*] Busting {total} paths with {THREADS} threads...")

    def worker(w):
        url = f"{base_url}/{urllib.parse.quote(w)}"
        code, length, body = fetch(url)
        return w, url, code, length, body

    with ThreadPoolExecutor(max_workers=THREADS) as ex:
        futs = {ex.submit(worker, w): w for w in words}
        for fut in as_completed(futs):
            done += 1
            try:
                w, url, code, length, body = fut.result()
            except Exception:
                w, url, code, length, body = futs[fut], "", None, 0, b""
            if code and code != 404:
                # filter soft-404s: same size & body as baseline = fake 200
                is_soft = (code == bl_code and length == bl_len and body == bl_body)
                if not is_soft and code not in (500, 502, 503):
                    hits.append((code, url))
                    print(f"\n[+] {code}  {url}")
            if done % 20 == 0 or done == total:
                bar(done, total, len(hits))
    print()
    return hits

# ---------------- SUBDOMAIN BUSTER (-b) ----------------
def bust_subdomains(domain, words):
    hits = []
    total = len(words)
    done = 0
    print(f"[*] Resolving {total} subdomains against {domain}...")
    import threading
    resolver = socket.gethostbyname

    def worker(w):
        sub = f"{w}.{domain}"
        try:
            ip = resolver(sub)
            return sub, ip
        except Exception:
            return sub, None

    with ThreadPoolExecutor(max_workers=THREADS) as ex:
        futs = {ex.submit(worker, w): w for w in words}
        for fut in as_completed(futs):
            done += 1
            try:
                sub, ip = fut.result()
            except Exception:
                sub, ip = futs[fut], None
            if ip:
                hits.append((sub, ip))
                print(f"\n[+] {sub} -> {ip}")
            if done % 50 == 0 or done == total:
                bar(done, total, len(hits))
    print()
    return hits

# ---------------- MAIN / INTERACTIVE ----------------
def clean_target(t):
    t = t.strip()
    if not t:
        sys.exit("[x] empty target")
    if t.startswith("http"):
        t = re.sub(r"^https?://", "", t) if False else t
    return t.rstrip("/")

import re

def main():
    print("=" * 60)
    print("  BYMIN v1.0 - dir/subdomain/admin buster")
    print("=" * 60)
    target = input("Input target site: ").strip()
    mode = input("Input type of find (-f = paths, -b = subdomains): ").strip().lower()
    admin = input("Admin hunt? -a or press enter: ").strip().lower()
    admin = (admin == "-a")

    if mode not in ("-f", "-b"):
        sys.exit("[x] mode must be -f or -b")

    files = download_wordlists(mode, admin)
    if not files:
        sys.exit("[x] no wordlists found")

    if mode == "-b":
        host = clean_target(target).replace("http://", "").replace("https://", "").split("/")[0]
        words = load_words(files, host_for_dns=True)
        hits = bust_subdomains(host, words)
        print("\n" + "=" * 60)
        print(f"RESULTS: {len(hits)} live subdomains")
        for sub, ip in hits:
            print(f"  {sub} -> {ip}")
    else:
        host = clean_target(target)
        for pfx in ("https://", "http://"):
            if host.startswith(pfx):
                host = host[len(pfx):]
                break
        base = f"https://{host}"
        code, _, _ = fetch(base)
        if code is None:
            base = f"http://{host}"
            code, _, _ = fetch(base)
            if code is None:
                sys.exit(f"[x] {host} unreachable")
        print(f"[*] Target alive: {base} (status {code})")
        baseline = get_baseline(base)
        words = load_words(files)
        hits = bust_paths(base, words, baseline)
        print("=" * 60)
        print(f"RESULTS: {len(hits)} working links (no 404):")
        for c, u in sorted(hits):
            print(f"  [{c}] {u}")

if __name__ == "__main__":
    main()
