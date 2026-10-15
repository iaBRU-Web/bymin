%%writefile bymin.py
#!/usr/bin/env python3
"""
 ██████╗ ██╗   ██╗███╗   ███╗██╗███╗   ██╗
 ██╔══██╗╚██╗ ██╔╝████╗ ████║██║████╗  ██║
 ██████╔╝ ╚████╔╝ ██╔████╔██║██║██╔██╗ ██║
 ██╔══██╗  ╚██╔╝  ██║╚██╔╝██║██║██║╚██╗██║
 ██████╔╝   ██║   ██║ ╚═╝ ██║██║██║ ╚████║
 ╚═════╝    ╚═╝   ╚═╝     ╚═╝╚═╝╚═╝  ╚═══╝
        v3.0 :: ASYNC RECON ENGINE
"""

import sys, os, socket, ssl, time, re, random, string, zipfile, asyncio, itertools, threading
import urllib.request, urllib.parse
import aiohttp

# ---------------- CONFIG ----------------
WORDDIR      = "/root/bymin_wordlists"
SECLISTS_URL = "https://github.com/danielmiessler/SecLists/archive/refs/heads/master.zip"
CONCURRENCY  = 200          # aiohttp handles this easily vs 50 threads
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
        sys.stdout.write(f"{color}{ch}{RESET}"); sys.stdout.flush(); time.sleep(delay)
    print()

def glitch_banner():
    banner = [
        " ██████╗ ██╗   ██╗███╗   ███╗██╗███╗   ██╗",
        " ██╔══██╗╚██╗ ██╔╝████╗ ████║██║████╗  ██║",
        " ██████╔╝ ╚████╔╝ ██╔████╔██║██║██╔██╗ ██║",
        " ██╔══██╗  ╚██╔╝  ██║╚██╔╝██║██║╚██╗██║",
        " ██████╔╝   ██║   ██║ ╚═╝ ██║██║██║ ╚████║",
        " ╚═════╝    ╚═╝   ╚═╝     ╚═╝╚═╝╚═╝  ╚═══╝",
    ]
    print()
    for line in banner:
        for color in (RED, YELLOW, WHITE, GREEN):
            sys.stdout.write(f"\r{color}{line}{RESET}"); sys.stdout.flush(); time.sleep(0.012)
        print(f"{GREEN}{line}{RESET}")
    print(f"{DIM}        v3.0 :: ASYNC RECON ENGINE{RESET}")
    print(f"{DIM}   ────────────────────────────────────────────────{RESET}")

def status(msg): print(f"{GREEN}[▲]{RESET} {msg}")
def alert(msg):  print(f"{YELLOW}[!]{RESET} {msg}")

def start_spin(label):
    global _spin_thread
    _stop.clear()
    def spin():
        frames = itertools.cycle("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")
        while not _stop.is_set():
            sys.stdout.write(f"\r{CYAN}{next(frames)}{RESET} {DIM}{label}{RESET}")
            sys.stdout.flush(); time.sleep(0.08)
    _spin_thread = threading.Thread(target=spin, daemon=True); _spin_thread.start()

def stop_spin():
    _stop.set()
    t = globals().get("_spin_thread")
    if t: t.join()

def bar(done, total, hits, width=44):
    pct    = min(done / total, 1.0) if total else 0
    filled = int(width * pct)
    color  = GREEN if hits == 0 else (CYAN if hits < 50 else YELLOW)
    sys.stdout.write(
        f"\r{color}[{'█' * filled}{'░' * (width - filled)}]{RESET} "
        f"{BOLD}{pct:5.1%}{RESET} {DIM}[{done}/{total}]{RESET} {GREEN}hits:{hits}{RESET}   "
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
        with zipfile.ZipFile(zippath) as z: z.extractall(WORDDIR)
        os.remove(zippath); stop_spin()
    lists = SUBDOMAIN_LISTS if mode == "-b" else PATH_LISTS
    if admin: lists = lists + ADMIN_LISTS
    files, seen = [], set()
    for rel in lists:
        p = os.path.join(src, rel)
        if os.path.isfile(p) and p not in seen:
            seen.add(p); files.append(p)
    return files

def load_words(files, dns_mode=False):
    words = set()
    for f in files:
        try:
            with open(f, "r", errors="ignore") as fh:
                for line in fh:
                    w = line.strip()
                    if not w or w.startswith("#"): continue
                    if dns_mode:
                        w = w.split(".")[0].lower()
                        if not w or not all(c in string.ascii_lowercase + string.digits + "-" for c in w):
                            continue
                    if len(w) > 60: continue
                    words.add(w)
        except Exception: pass
    return list(words)

# ---------------- ASYNC HTTP ENGINE ----------------
async def fetch(session, url):
    for attempt in range(RETRIES + 1):
        try:
            async with session.get(url) as r:
                body = await r.content.read(4096)
                return r.status, body
        except Exception:
            if attempt < RETRIES:
                await asyncio.sleep(0.3); continue
            return None, b""

async def bust_paths(base_url, words, baseline):
    bl_code, bl_body = baseline
    hits, done, total = [], 0, len(words)
    sem = asyncio.Semaphore(CONCURRENCY)

    async def worker(w, session):
        url = f"{base_url}/{urllib.parse.quote(w)}"
        async with sem:
            code, body = await fetch(session, url)
        return url, code, body

    conn = aiohttp.TCPConnector(limit=CONCURRENCY, ssl=False)
    to   = aiohttp.ClientTimeout(total=TIMEOUT)
    start_spin(f"scanning {total} paths @ {CONCURRENCY} concurrent")
    try:
        async with aiohttp.ClientSession(connector=conn, timeout=to,
                                         headers={"User-Agent": USER_AGENT}) as session:
            chunk = 2000
            for i in range(0, total, chunk):
                batch = words[i:i + chunk]
                results = await asyncio.gather(*(worker(w, session) for w in batch))
                for url, code, body in results:
                    if code and code not in (404, 500, 502, 503):
                        if not (code == bl_code and body == bl_body):
                            hits.append((code, url))
                done += len(batch)
                stop_spin(); bar(done, total, len(hits)); start_spin("scanning")
                await asyncio.sleep(0)   # yield to event loop
    finally:
        stop_spin()
    bar(done, total, len(hits)); print()
    return hits

async def bust_subdomains(domain, words):
    hits, done, total = [], 0, len(words)
    loop = asyncio.get_event_loop()
    sem  = asyncio.Semaphore(CONCURRENCY)

    fake = "bymin-null-" + "".join(random.choices(string.ascii_lowercase, k=16))
    try:
        wild = await loop.run_in_executor(None, socket.gethostbyname, f"{fake}.{domain}")
        alert(f"wildcard DNS detected ({wild}) — filtering wildcard IPs")
    except Exception:
        wild = None

    async def worker(w):
        sub = f"{w}.{domain}"
        async with sem:
            try:
                ip = await loop.run_in_executor(None, socket.gethostbyname, sub)
            except Exception:
                ip = None
        return sub, ip

    start_spin(f"resolving {total} subdomains")
    try:
        chunk = 2000
        for i in range(0, total, chunk):
            batch = words[i:i + chunk]
            results = await asyncio.gather(*(worker(w) for w in batch))
            for sub, ip in results:
                if ip and ip != wild:
                    hits.append((sub, ip))
            done += len(batch)
            stop_spin(); bar(done, total, len(hits)); start_spin("resolving")
            await asyncio.sleep(0)
    finally:
        stop_spin()
    bar(done, total, len(hits)); print()
    return hits

# ---------------- MAIN ----------------
def clean_host(t):
    t = t.strip().rstrip("/")
    t = re.sub(r"^https?://", "", t)
    return t.split("/")[0]

def get_baseline_sync(base_url):
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    rnd = "".join(random.choices(string.ascii_lowercase, k=24))
    import urllib.request, urllib.error
    req = urllib.request.Request(f"{base_url}/{rnd}", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
            return r.status, r.read(4096)
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception:
        return None, b""

def save_results(hits):
    with open(RESULT_FILE, "w") as f:
        for h in hits: f.write(str(h) + "\n")

async def run(target, mode, admin):
    files = download_wordlists(mode, admin)
    if not files:
        sys.exit(f"{RED}[x] no wordlists found{RESET}")
    if mode == "-b":
        host  = clean_host(target)
        words = load_words(files, dns_mode=True)
        status(f"DNS sweep on {CYAN}{host}{RESET} — {len(words)} candidates")
        hits = await bust_subdomains(host, words)
        print(f"\n{BOLD}{GREEN}{'═' * 60}{RESET}")
        print(f"{BOLD}  ▸ RESULT: {len(hits)} live subdomains{RESET}")
        print(f"{BOLD}{GREEN}{'═' * 60}{RESET}")
        for sub, ip in sorted(hits):
            print(f"  {GREEN}●{RESET} {sub:<45} {DIM}{ip}{RESET}")
    else:
        host = clean_host(target)
        base = f"https://{host}"
        code, _ = get_baseline_sync(base)
        if code is None:
            base = f"http://{host}"
            code, _ = get_baseline_sync(base)
            if code is None:
                sys.exit(f"{RED}[x] {host} unreachable{RESET}")
        status(f"target alive: {CYAN}{base}{RESET} (status {code})")
        baseline = get_baseline_sync(base)
        words = load_words(files)
        status(f"payload: {len(words)} unique paths loaded")
        hits = await bust_paths(base, words, baseline)
        print(f"\n{BOLD}{GREEN}{'═' * 60}{RESET}")
        print(f"{BOLD}  ▸ RESULT: {len(hits)} working links (non-404){RESET}")
        print(f"{BOLD}{GREEN}{'═' * 60}{RESET}")
        for c, u in sorted(hits):
            col = GREEN if c == 200 else (YELLOW if c in (301, 302, 401, 403) else WHITE)
            print(f"  {col}[{c}]{RESET} {u}")
    save_results(hits)
    print(f"{DIM}  ▸ saved to {RESULT_FILE}{RESET}")

def main():
    glitch_banner()
    typewriter("target acquisition...", color=DIM)
    target = input(f"{BOLD}  :: target site{RESET} > ").strip()
    mode   = input(f"{BOLD}  :: mode  [-f paths | -b subdomains]{RESET} > ").strip().lower()
    admin  = input(f"{BOLD}  :: admin hunt  [-a or enter]{RESET} > ").strip().lower() == "-a"
    if mode not in ("-f", "-b"):
        sys.exit(f"{RED}[x] mode must be -f or -b{RESET}")
    asyncio.run(run(target, mode, admin))
    typewriter("operation complete.", color=GREEN)

if __name__ == "__main__":
    main()

!pip -q install aiohttp

!python bymin.py
