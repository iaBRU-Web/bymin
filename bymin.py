%%writefile bymin.py
#!/usr/bin/env python3
"""
 ██████╗ ██╗   ██╗███╗   ███╗██╗███╗   ██╗
 ██╔══██╗╚██╗ ██╔╝████╗ ████║██║████╗  ██║
 ██████╔╝ ╚████╔╝ ██╔████╔██║██║██╔██╗ ██║
 ██╔══██╗  ╚██╔╝  ██║╚██╔╝██║██║██║╚██╗██║
 ██████╔╝   ██║   ██║ ╚═╝ ██║██║██║ ╚████║
 ╚═════╝    ╚═╝   ╚═╝     ╚═╝╚═╝╚═╝  ╚═══╝
        v2.0 :: RECON PROTOCOL
   dir buster / subdomain mapper / admin hunter
"""

import sys, os, socket, ssl, time, re, itertools, threading, random, string, zipfile, json
import urllib.request, urllib.error, urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------------- CONFIG ----------------
WORDDIR      = "/root/bymin_wordlists"
SECLISTS_URL = "https://github.com/danielmiessler/SecLists/archive/refs/heads/master.zip"
THREADS      = 50
TIMEOUT      = 8
RETRIES      = 1
USER_AGENT   = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
RESULT_FILE  = "/root/bymin_results.txt"

PATH_LISTS = [
    "Discovery/Web-Content/common.txt", "Discovery/Web-Content/big.txt",
    "Discovery/Web-Content/raft-large-files.txt", "Discovery/Web-Content/raft-large-directories.txt",
    "Discovery/Web-Content/raft-large-words.txt", "Discovery/Web-Content/directory-list-2.3-medium.txt",
    "Discovery/Web-Content/directory-list-lowercase-2.3-medium.txt", "Discovery/Web-Content/quickhits.txt",
    "Discovery/Web-Content/admin-panels.txt", "Discovery/Web-Content/CMS.txt",
    "Discovery/Web-Content/WordPress.fuzz.txt", "Discovery/Web-Content/Joomla.fuzz.txt",
    "Discovery/Web-Content/Drupal.fuzz.txt", "Discovery/Web-Content/apache.txt",
    "Discovery/Web-Content/nginx.txt", "Discovery/Web-Content/iis.txt",
    "Discovery/Web-Content/tomcat.txt", "Discovery/Web-Content/jenkins.txt",
    "Discovery/Web-Content/gitlab.txt", "Discovery/Web-Content/graphql.txt",
    "Discovery/Web-Content/bak.txt", "Discovery/Web-Content/log.txt",
    "Discovery/Web-Content/backup.txt", "Discovery/Web-Content/db.txt",
    "Discovery/Web-Content/debug.txt", "Discovery/Web-Content/api.txt",
    "Discovery/Web-Content/swagger.txt", "Discovery/Web-Content/dev.txt",
    "Discovery/Web-Content/staging.txt", "Discovery/Web-Content/test.txt",
    "Discovery/Web-Content/upload.txt", "Discovery/Web-Content/uploads.txt",
    "Discovery/Web-Content/phpinfo.txt", "Discovery/Web-Content/RobotsDisallowed/top1000.txt",
]
ADMIN_LISTS = [
    "Discovery/Web-Content/admin-panels.txt", "Discovery/Web-Content/ConstellationsAdmin.txt",
    "Discovery/Web-Content/manager.txt", "Discovery/Web-Content/login.txt",
    "Discovery/Web-Content/cpanel.txt", "Discovery/Web-Content/django.txt",
    "Discovery/Web-Content/laravel.txt", "Discovery/Web-Content/springboot.txt",
]
SUBDOMAIN_LISTS = [
    "Discovery/DNS/subdomains-top1million-5000.txt", "Discovery/DNS/subdomains-top1million-20000.txt",
    "Discovery/DNS/deepmine.txt", "Discovery/DNS/n0m1s.txt",
    "Discovery/DNS/combined_subdomains.txt", "Discovery/DNS/bitquark-subdomains-top100000.txt",
    "Discovery/DNS/dns-Jhaddix.txt",
]

# ---------------- CINEMATIC LAYER ----------------
GREEN, DIM, CYAN, RED, YELLOW, WHITE, RESET, BOLD = \
    "\033[92m", "\033[90m", "\033[96m", "\033[91m", "\033[93m", "\033[97m", "\033[0m", "\033[1m"

_stop = threading.Event()

def typewriter(text, delay=0.004, color=GREEN):
    for ch in text:
        sys.stdout.write(f"{color}{ch}{RESET}")
        sys.stdout.flush()
        time.sleep(delay)
    print()

def glitch_banner():
    banner = [
        " ██████╗ ██╗   ██╗███╗   ███╗██╗███╗   ██╗",
        " ██╔══██╗╚██╗ ██╔╝████╗ ████║██║████╗  ██║",
        " ██████╔╝ ╚████╔╝ ██╔████╔██║██║██╔██╗ ██║",
        " ██╔══██╗  ╚██╔╝  ██║╚██╔╝██║██║██║╚██╗██║",
        " ██████╔╝   ██║   ██║ ╚═╝ ██║██║██║ ╚████║",
        " ╚═════╝    ╚═╝   ╚═╝     ╚═╝╚═╝╚═╝  ╚═══╝",
    ]
    print()
    for line in banner:
        for color in (RED, YELLOW, WHITE, GREEN):   # flicker-in effect
            sys.stdout.write(f"\r{color}{line}{RESET}")
            sys.stdout.flush()
            time.sleep(0.012)
        print(f"{GREEN}{line}{RESET}")
    print(f"{DIM}        v2.0 :: RECON PROTOCOL :: quiet-ops mode{RESET}")
    print(f"{DIM}   ────────────────────────────────────────────────{RESET}")

def status(msg, color=GREEN):
    print(f"{color}[▲]{RESET} {msg}")

def alert(msg):
    print(f"{YELLOW}[!]{RESET} {msg}")

def start_spin(label):
    global _spin_thread
    _stop.clear()
    def spin():
        frames = itertools.cycle("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")   # braille spinner, terminal-native
        while not _stop.is_set():
            sys.stdout.write(f"\r{CYAN}{next(frames)}{RESET} {DIM}{label}{RESET}")
            sys.stdout.flush()
            time.sleep(0.08)
    _spin_thread = threading.Thread(target=spin, daemon=True)
    _spin_thread.start()

def stop_spin():
    _stop.set()
    t = globals().get("_spin_thread")
    if t:
        t.join()

def bar(done, total, hits, width=44):
    pct   = min(done / total, 1.0) if total else 0
    filled = int(width * pct)
    color  = GREEN if hits == 0 else (CYAN if hits < 50 else YELLOW)
    sys.stdout.write(
        f"\r{color}[{'█' * filled}{'░' * (width - filled)}]{RESET} "
        f"{BOLD}{pct:5.1%}{RESET} {DIM}[{done}/{total}]{RESET} "
        f"{GREEN}hits:{hits}{RESET}   "
    )
    sys.stdout.flush()

# ---------------- WORDLISTS ----------------
def download_wordlists(mode, admin):
    os.makedirs(WORDDIR, exist_ok=True)
    src = os.path.join(WORDDIR, "SecLists-master")
    if not os.path.isdir(src):
        zippath = os.path.join(WORDDIR, "seclists.zip")
        typewriter("» acquiring arsenal: SecLists (~100MB, one-time)", color=DIM)
        if not os.path.exists(zippath):
            urllib.request.urlretrieve(SECLISTS_URL, zippath)
        start_spin("extracting payloads")
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

# ---------------- HTTP ENGINE ----------------
_tls_ctx = ssl.create_default_context()
_tls_ctx.check_hostname = False
_tls_ctx.verify_mode = ssl.CERT_NONE

def fetch(url):
    for attempt in range(RETRIES + 1):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=_tls_ctx) as r:
                body = r.read(4096)
                return r.status, len(body), body
        except urllib.error.HTTPError as e:
            return e.code, 0, b""
        except Exception:
            if attempt < RETRIES:
                time.sleep(0.3)
                continue
            return None, 0, b""

def get_baseline(base_url):
    rnd = "".join(random.choices(string.ascii_lowercase, k=24))
    return fetch(f"{base_url}/{rnd}")

# ---------------- PATH BUSTER ----------------
def bust_paths(base_url, words, baseline):
    bl_code, bl_len, bl_body = baseline
    hits, done, total = [], 0, len(words)
    start_spin(f"scanning {total} paths @ {THREADS} threads")
    try:
        with ThreadPoolExecutor(max_workers=THREADS) as ex:
            futs = [ex.submit(fetch, f"{base_url}/{urllib.parse.quote(w)}") for w in words]
            for fut in as_completed(futs):
                done += 1
                url = None
                try:
                    code, length, body = fut.result()
                except Exception:
                    code, length, body = None, 0, b""
                if code and code not in (404, 500, 502, 503):
                    is_soft = (code == bl_code and abs(length - bl_len) < 32 and body == bl_body)
                    if not is_soft:
                        idx = done  # recover URL
                        hits.append((code, pending_urls[fut]))
                if done % 25 == 0 or done == total:
                    stop_spin(); bar(done, total, len(hits)); start_spin("scanning")
    finally:
        stop_spin()
    bar(done, total, len(hits)); print()
    return hits

# NOTE: fetch doesn't carry the URL back — use a wrapper that does
def bust_paths(base_url, words, baseline):
    bl_code, bl_len, bl_body = baseline
    hits, done, total = [], 0, len(words)

    def worker(w):
        url = f"{base_url}/{urllib.parse.quote(w)}"
        code, length, body = fetch(url)
        return url, code, length, body

    start_spin(f"scanning {total} paths @ {THREADS} threads")
    try:
        with ThreadPoolExecutor(max_workers=THREADS) as ex:
            futs = [ex.submit(worker, w) for w in words]
            for fut in as_completed(futs):
                done += 1
                try:
                    url, code, length, body = fut.result()
                except Exception:
                    url, code, length, body = "", None, 0, b""
                if code and code not in (404, 500, 502, 503):
                    is_soft = (code == bl_code and abs(length - bl_len) < 32 and body == bl_body)
                    if not is_soft:
                        hits.append((code, url))
                if done % 25 == 0 or done == total:
                    stop_spin(); bar(done, total, len(hits)); start_spin("scanning")
    finally:
        stop_spin()
    bar(done, total, len(hits)); print()
    return hits

# ---------------- SUBDOMAIN BUSTER ----------------
def bust_subdomains(domain, words):
    hits, done, total = [], 0, len(words)
    # wildcard detection: fake sub shouldn't resolve
    wild = None
    fake = "bymin-null-" + "".join(random.choices(string.ascii_lowercase, k=16))
    try:
        wild = socket.gethostbyname(f"{fake}.{domain}")
    except Exception:
        pass
    if wild:
        alert(f"wildcard DNS detected ({wild}) — wildcard-matching IPs will be filtered")

    def worker(w):
        sub = f"{w}.{domain}"
        try:
            return sub, socket.gethostbyname(sub)
        except Exception:
            return sub, None

    start_spin(f"resolving {total} subdomains")
    try:
        with ThreadPoolExecutor(max_workers=THREADS) as ex:
            futs = [ex.submit(worker, w) for w in words]
            for fut in as_completed(futs):
                done += 1
                try:
                    sub, ip = fut.result()
                except Exception:
                    sub, ip = "", None
                if ip and ip != wild:
                    hits.append((sub, ip))
                if done % 50 == 0 or done == total:
                    stop_spin(); bar(done, total, len(hits)); start_spin("resolving")
    finally:
        stop_spin()
    bar(done, total, len(hits)); print()
    return hits

# ---------------- MAIN ----------------
def clean_host(t):
    t = t.strip().rstrip("/")
    t = re.sub(r"^https?://", "", t)
    return t.split("/")[0]

def save_results(hits):
    with open(RESULT_FILE, "w") as f:
        for h in hits:
            f.write(str(h) + "\n")

def main():
    glitch_banner()
    typewriter("target acquisition...", color=DIM)
    target = input(f"{BOLD}  :: target site{RESET} > ").strip()
    mode   = input(f"{BOLD}  :: mode  [-f paths | -b subdomains]{RESET} > ").strip().lower()
    admin  = input(f"{BOLD}  :: admin hunt  [-a or enter]{RESET} > ").strip().lower() == "-a"

    if mode not in ("-f", "-b"):
        sys.exit(f"{RED}[x] mode must be -f or -b{RESET}")

    files = download_wordlists(mode, admin)
    if not files:
        sys.exit(f"{RED}[x] no wordlists found{RESET}")

    if mode == "-b":
        host  = clean_host(target)
        words = load_words(files, dns_mode=True)
        status(f"DNS sweep on {CYAN}{host}{RESET} — {len(words)} candidates")
        hits = bust_subdomains(host, words)
        print(f"\n{BOLD}{GREEN}{'═' * 60}{RESET}")
        print(f"{BOLD}  ▸ RESULT: {len(hits)} live subdomains{RESET}")
        print(f"{BOLD}{GREEN}{'═' * 60}{RESET}")
        for sub, ip in sorted(hits):
            print(f"  {GREEN}●{RESET} {sub:<45} {DIM}{ip}{RESET}")
    else:
        host = clean_host(target)
        base = f"https://{host}"
        code, _, _ = fetch(base)
        if code is None:
            base = f"http://{host}"
            code, _, _ = fetch(base)
            if code is None:
                sys.exit(f"{RED}[x] {host} unreachable — target down or blocking{RESET}")
        status(f"target alive: {CYAN}{base}{RESET} (status {code})")
        baseline = get_baseline(base)
        words = load_words(files)
        status(f"payload: {len(words)} unique paths loaded")
        hits = bust_paths(base, words, baseline)
        print(f"\n{BOLD}{GREEN}{'═' * 60}{RESET}")
        print(f"{BOLD}  ▸ RESULT: {len(hits)} working links (non-404){RESET}")
        print(f"{BOLD}{GREEN}{'═' * 60}{RESET}")
        for c, u in sorted(hits):
            col = GREEN if c == 200 else (YELLOW if c in (301, 302, 401, 403) else WHITE)
            print(f"  {col}[{c}]{RESET} {u}")
    save_results(hits)
    print(f"{DIM}  ▸ saved to {RESULT_FILE}{RESET}")
    typewriter("operation complete.", color=GREEN)

if __name__ == "__main__":
    main()
