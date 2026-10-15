%%writefile bymin.py
#!/usr/bin/env python3
"""Bymin v1.1 - dir/subdomain/admin buster, quiet mode"""

import sys, os, socket, ssl, time, re, itertools, threading
import urllib.request, urllib.error, urllib.parse
import random, string, zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed

WORDDIR = "/root/bymin_wordlists"
SECLISTS_URL = "https://github.com/danielmiessler/SecLists/archive/refs/heads/master.zip"
THREADS = 40
TIMEOUT = 8
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

PATH_LISTS = [
    "Discovery/Web-Content/common.txt",
    "Discovery/Web-Content/big.txt",
    "Discovery/Web-Content/raft-large-files.txt",
    "Discovery/Web-Content/raft-large-directories.txt",
    "Discovery/Web-Content/raft-large-words.txt",
    "Discovery/Web-Content/directory-list-2.3-medium.txt",
    "Discovery/Web-Content/directory-list-lowercase-2.3-medium.txt",
    "Discovery/Web-Content/quickhits.txt",
    "Discovery/Web-Content/admin-panels.txt",
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
]
ADMIN_LISTS = [
    "Discovery/Web-Content/admin-panels.txt",
    "Discovery/Web-Content/ConstellationsAdmin.txt",
    "Discovery/Web-Content/manager.txt",
    "Discovery/Web-Content/login.txt",
    "Discovery/Web-Content/cpanel.txt",
    "Discovery/Web-Content/django.txt",
    "Discovery/Web-Content/laravel.txt",
    "Discovery/Web-Content/springboot.txt",
]
SUBDOMAIN_LISTS = [
    "Discovery/DNS/subdomains-top1million-5000.txt",
    "Discovery/DNS/subdomains-top1million-20000.txt",
    "Discovery/DNS/deepmine.txt",
    "Discovery/DNS/n0m1s.txt",
    "Discovery/DNS/combined_subdomains.txt",
    "Discovery/DNS/bitquark-subdomains-top100000.txt",
    "Discovery/DNS/dns-Jhaddix.txt",
]

# ---------------- QUIET OUTPUT + SPINNER ----------------
_stop_spin = threading.Event()
_spin_thread = None
_quiet_msgs = []

def start_spin(label):
    global _spin_thread
    _stop_spin.clear()
    def spin():
        for ch in itertools.cycle("|/-\\"):
            if _stop_spin.is_set():
                break
            print(f"\r{ch} {label}", end="", flush=True)
            time.sleep(0.1)
    _spin_thread = threading.Thread(target=spin, daemon=True)
    _spin_thread.start()

def stop_spin():
    _stop_spin.set()
    if _spin_thread:
        _spin_thread.join()

def quiet_print(msg):
    _quiet_msgs.append(msg)

def bar(done, total, hits, width=40):
    pct = done / total if total else 0
    filled = int(width * pct)
    print("\r|" + "=" * filled + " " * (width - filled) +
          f"| {pct:.0%} [{done}/{total}] hits:{hits}", end="", flush=True)

# ---------------- WORDLISTS ----------------
def download_wordlists(mode, admin):
    os.makedirs(WORDDIR, exist_ok=True)
    zippath = os.path.join(WORDDIR, "seclists.zip")
    src = os.path.join(WORDDIR, "SecLists-master")
    start_spin("Fetching SecLists")
    if not os.path.isdir(src):
        if not os.path.exists(zippath):
            urllib.request.urlretrieve(SECLISTS_URL, zippath)
        with zipfile.ZipFile(zippath) as z:
            z.extractall(WORDDIR)
        os.remove(zippath)
    stop_spin()
    lists = SUBDOMAIN_LISTS if mode == "-b" else PATH_LISTS
    if admin:
        lists = lists + ADMIN_LISTS
    files, seen = [], set()
    for rel in lists:
        p = os.path.join(src, rel)
        if os.path.isfile(p) and p not in seen:
            seen.add(p)
            files.append(p)
    return files

def load_words(files, dns_mode=False):
    words = set()
    for f in files:
        try:
            with open(f, "r", errors="ignore") as fh:
                for line in fh:
                    w = line.strip()
                    if not w or w.startswith("#"):
                        continue
                    if dns_mode:
                        w = w.split(".")[0].lower()
                        if not w or not all(c in string.ascii_lowercase + string.digits + "-" for c in w):
                            continue
                    if len(w) > 60:
                        continue
                    words.add(w)
        except Exception:
            pass
    return list(words)

# ---------------- HTTP ----------------
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
    return fetch(f"{base_url}/{rnd}")

# ---------------- PATH BUSTER (-f) ----------------
def bust_paths(base_url, words, baseline):
    bl_code, bl_len, bl_body = baseline
    hits, done = [], 0
    total = len(words)

    def worker(w):
        url = f"{base_url}/{urllib.parse.quote(w)}"
        code, length, body = fetch(url)
        return url, code, length, body

    start_spin(f"Busting {total} paths")
    try:
        with ThreadPoolExecutor(max_workers=THREADS) as ex:
            futs = [ex.submit(worker, w) for w in words]
            for fut in as_completed(futs):
                done += 1
                try:
                    url, code, length, body = fut.result()
                except Exception:
                    url, code, length, body = "", None, 0, b""
                if code and code != 404:
                    is_soft = (code == bl_code and length == bl_len and body == bl_body)
                    if not is_soft and code not in (500, 502, 503):
                        hits.append((code, url))
                        quiet_print(f"[+] {code}  {url}")
                if done % 25 == 0 or done == total:
                    stop_spin()
                    bar(done, total, len(hits))
                    start_spin(f"Busting {total} paths")
    finally:
        stop_spin()
    bar(done, total, len(hits))
    print()
    return hits

# ---------------- SUBDOMAIN BUSTER (-b) ----------------
def bust_subdomains(domain, words):
    hits, done = [], 0
    total = len(words)

    def worker(w):
        sub = f"{w}.{domain}"
        try:
            return sub, socket.gethostbyname(sub)
        except Exception:
            return sub, None

    start_spin(f"Resolving {total} subdomains")
    try:
        with ThreadPoolExecutor(max_workers=THREADS) as ex:
            futs = [ex.submit(worker, w) for w in words]
            for fut in as_completed(futs):
                done += 1
                try:
                    sub, ip = fut.result()
                except Exception:
                    sub, ip = "", None
                if ip:
                    hits.append((sub, ip))
                    quiet_print(f"[+] {sub} -> {ip}")
                if done % 50 == 0 or done == total:
                    stop_spin()
                    bar(done, total, len(hits))
                    start_spin(f"Resolving {total} subdomains")
    finally:
        stop_spin()
    bar(done, total, len(hits))
    print()
    return hits

# ---------------- MAIN ----------------
def clean_host(t):
    t = t.strip().rstrip("/")
    t = re.sub(r"^https?://", "", t)
    return t.split("/")[0]

def main():
    print("=" * 60)
    print("  BYMIN v1.1 - quiet mode")
    print("=" * 60)
    target = input("Input target site: ").strip()
    mode = input("Input type of find (-f = paths, -b = subdomains): ").strip().lower()
    admin = input("Admin hunt? -a or press enter: ").strip().lower() == "-a"

    if mode not in ("-f", "-b"):
        sys.exit("[x] mode must be -f or -b")

    files = download_wordlists(mode, admin)
    if not files:
        sys.exit("[x] no wordlists found")

    if mode == "-b":
        host = clean_host(target)
        words = load_words(files, dns_mode=True)
        hits = bust_subdomains(host, words)
        print("=" * 60)
        print(f"RESULTS: {len(hits)} live subdomains")
        for sub, ip in hits:
            print(f"  {sub} -> {ip}")
    else:
        host = clean_host(target)
        base = f"https://{host}"
        code, _, _ = fetch(base)
        if code is None:
            base = f"http://{host}"
            code, _, _ = fetch(base)
            if code is None:
                sys.exit(f"[x] {host} unreachable")
        baseline = get_baseline(base)
        words = load_words(files)
        hits = bust_paths(base, words, baseline)
        print("=" * 60)
        print(f"RESULTS: {len(hits)} working links (no 404):")
        for c, u in sorted(hits):
            print(f"  [{c}] {u}")
        if _quiet_msgs:
            print("--- detail ---")
            for m in _quiet_msgs:
                print(m)

if __name__ == "__main__":
    main()
