%%writefile bymin.py
#!/usr/bin/env python3
"""
 ██████╗ ██╗   ██╗███╗   ███╗██╗███╗   ██╗
 ██╔══██╗╚██╗ ██╔╝████╗ ████║██║████╗  ██║
 ██████╔╝ ╚████╔╝ ██╔████╔██║██║██╔██╗ ██║
 ██╔══██╗  ╚██╔╝  ██║╚██╔╝██║██║╚██╗██║
 ██████╔╝   ██║   ██║ ╚═╝ ██║██║██║ ╚████║
 ╚═════╝    ╚═╝   ╚═╝     ╚═╝╚═╝╚═╝  ╚═══╝
        v4.0 :: ADAPTIVE RECON ENGINE
  scrapes the target -> builds its own wordlists
"""

import sys, os, socket, ssl, time, re, random, string, zipfile, asyncio, itertools, threading
import urllib.request, urllib.parse
from html.parser import HTMLParser
from collections import Counter
import aiohttp

# ---------------- CONFIG ----------------
WORDDIR      = "/root/bymin_wordlists"
SECLISTS_URL = "https://github.com/danielmiessler/SecLists/archive/refs/heads/master.zip"
CONCURRENCY  = 200
CRAWL_DEPTH  = 2          # how deep the scraper follows same-host links
CRAWL_MAX    = 150        # max pages scraped
TIMEOUT      = 8
RETRIES      = 1
MIN_WORD_LEN = 4
USER_AGENT   = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
RESULT_FILE  = "/root/bymin_results.txt"
CUSTOM_LIST  = "/root/bymin_custom_wordlist.txt"

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

# ---------------- UI LAYER ----------------
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
    print(f"{DIM}        v4.0 :: ADAPTIVE RECON ENGINE{RESET}")
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

def bar(done, total, hits, width=44, label="scanning"):
    pct    = min(done / total, 1.0) if total else 0
    filled = int(width * pct)
    color  = GREEN if hits == 0 else (CYAN if hits < 50 else YELLOW)
    sys.stdout.write(
        f"\r{color}[{'█' * filled}{'░' * (width - filled)}]{RESET} "
        f"{BOLD}{pct:5.1%}{RESET} {DIM}[{done}/{total}]{RESET} {GREEN}hits:{hits}{RESET} "
        f"{DIM}{label}{RESET}   "
    )
    sys.stdout.flush()

# ---------------- HTML SCRAPER ----------------
class PageScraper(HTMLParser):
    """Extracts title, meta keywords/description/generator, visible text, links, script srcs."""
    def __init__(self):
        super().__init__()
        self.title = ""
        self._in_title = False
        self.text_chunks = []
        self._skip = 0
        self.links = []
        self.metas = {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self._in_title = True
        elif tag in ("script", "style"):
            self._skip += 1
        elif tag == "meta":
            name = (a.get("name") or a.get("property") or "").lower()
            content = a.get("content", "")
            if name and content:
                self.metas[name] = content
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"])
        elif tag in ("script",) and a.get("src"):
            self.links.append(a["src"])

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.text_chunks.append(data)

    def text(self):
        return " ".join(self.text_chunks)

# ---------------- CRAWLER + WORDLIST GENERATOR ----------------
def tokenize(text):
    return re.findall(r"[A-Za-z][A-Za-z0-9_\-]{%d,}" % (MIN_WORD_LEN - 1), text)

def split_camel_snake(w):
    parts = re.split(r"[-_.]", w)
    parts += re.findall(r"[A-Z][a-z0-9]+", w)
    return [p for p in parts if len(p) >= MIN_WORD_LEN]

async def crawl_and_generate(session, base_url, sem):
    """
    BFS crawl of same-host pages. From each page harvest:
      - title words
      - meta name/description/keywords/author/generator
      - visible text words
      - URL path segments from links (incl. file/dir names)
      - script/api endpoint fragments
    Then mutate: camelCase splits, digit suffixes (1,2,123,2024), 'admin'-style combos.
    """
    seen, queue = set(), [(base_url, 0)]
    word_bag, seg_bag, titles, metas = Counter(), set(), [], {}
    pages_done = 0

    start_spin(f"crawling {base_url} (depth {CRAWL_DEPTH}, max {CRAWL_MAX} pages)")
    try:
        while queue and pages_done < CRAWL_MAX:
            url, depth = queue.pop(0)
            norm = url.rstrip("/")
            if norm in seen:
                continue
            seen.add(norm)
            async with sem:
                try:
                    async with session.get(url) as r:
                        ctype = r.headers.get("Content-Type", "")
                        if "html" not in ctype and "text" not in ctype:
                            continue
                        body = await r.text(errors="ignore")
                except Exception:
                    continue

            host = urllib.parse.urlparse(base_url).netloc
            parser = PageScraper()
            try:
                parser.feed(body)
            except Exception:
                pass

            title = parser.title.strip()
            if title:
                titles.append(title)
                for w in tokenize(title):
                    word_bag[w.lower()] += 5          # titles are gold, weight high
            for name, content in parser.metas.items():
                metas.setdefault(name, content)
                for w in tokenize(content):
                    word_bag[w.lower()] += 2
            for w in tokenize(parser.text())[:400]:   # cap per page
                word_bag[w.lower()] += 1

            for href in parser.links:
                absolute = urllib.parse.urljoin(url, href)
                p = urllib.parse.urlparse(absolute)
                # harvest path segments as words
                for seg in p.path.split("/"):
                    seg = seg.strip()
                    clean = re.sub(r"\.[a-zA-Z0-9]{1,5}$", "", seg)   # strip extension
                    if len(clean) >= MIN_WORD_LEN and clean.isascii():
                        for piece in split_camel_snake(clean):
                            seg_bag.add(piece.lower())
                if p.netloc == host and depth < CRAWL_DEPTH and absolute not in seen:
                    queue.append((absolute, depth + 1))
            pages_done += 1
            stop_spin(); bar(pages_done, CRAWL_MAX, len(word_bag) + len(seg_bag),
                             label=f"crawled:{pages_done}")
            start_spin("crawling")
    finally:
        stop_spin()
    bar(pages_done, CRAWL_MAX, len(word_bag) + len(seg_bag), label=f"crawled:{pages_done}")
    print()

    # ---- mutations ----
    final = set(word_bag) | seg_bag
    top = [w for w, _ in word_bag.most_common(50)]
    digits = ["", "1", "2", "123", "2023", "2024", "2025", "2026", "01", "admin", "dev", "test", "backup", "old", "new"]
    for w in top:
        lw = w.lower()
        for d in digits:
            if d == "" or len(d) <= 2 or d.isalpha():
                final.add(f"{lw}{d}")
    # title slug combos: "bru msg" -> brumsg, bru-msg
    for t in titles:
        slug = re.sub(r"[^a-z0-9 ]", "", t.lower())
        parts = slug.split()
        if 1 < len(parts) <= 4:
            final.add("".join(parts)); final.add("-".join(parts)); final.add("_".join(parts))

    final = {w for w in final if MIN_WORD_LEN <= len(w) <= 40}
    with open(CUSTOM_LIST, "w") as f:
        f.write("\n".join(sorted(final)))
    return final, titles, metas, pages_done

# ---------------- WORDLISTS (SECLISTS) ----------------
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

# ---------------- ASYNC BUSTERS ----------------
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
                await asyncio.sleep(0)
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

# ---------------- SYNC HELPERS ----------------
def clean_host(t):
    t = t.strip().rstrip("/")
    t = re.sub(r"^https?://", "", t)
    return t.split("/")[0]

def get_baseline_sync(base_url):
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    rnd = "".join(random.choices(string.ascii_lowercase, k=24))
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

# ---------------- MAIN FLOW ----------------
async def run(target, mode, admin, adaptive):
    host = clean_host(target)
    base = None
    for scheme in ("https", "http"):
        candidate = f"{scheme}://{host}"
        code, _ = get_baseline_sync(candidate)
        if code is not None:
            base = candidate
            break
    if base is None:
        sys.exit(f"{RED}[x] {host} unreachable{RESET}")
    status(f"target alive: {CYAN}{base}{RESET}")

    sem = asyncio.Semaphore(10)
    conn = aiohttp.TCPConnector(limit=20, ssl=False)
    to   = aiohttp.ClientTimeout(total=TIMEOUT)

    custom = set()
    if mode != "-b":     # crawling makes no sense for pure DNS sweeps
        status("phase 1/2 :: scraping target to build custom wordlist")
        async with aiohttp.ClientSession(connector=conn, timeout=to,
                                         headers={"User-Agent": USER_AGENT}) as session:
            custom, titles, metas, pages = await crawl_and_generate(session, base, sem)
        if titles:
            print(f"  {DIM}site title:{RESET} {CYAN}{titles[0]}{RESET}")
        for key in ("description", "keywords", "generator"):
            if key in metas:
                print(f"  {DIM}meta {key}:{RESET} {metas[key][:90]}")
        status(f"scraped {pages} pages → {len(custom)} custom words saved to {CUSTOM_LIST}")

    if mode == "-c":
        print(f"\n{BOLD}{GREEN}{'═' * 60}{RESET}")
        print(f"{BOLD}  ▸ CUSTOM WORDLIST ({len(custom)} entries){RESET}")
        print(f"{BOLD}{GREEN}{'═' * 60}{RESET}")
        for w in sorted(custom):
            print(f"  {GREEN}●{RESET} {w}")
        return

    files = download_wordlists(mode, admin)
    if not files:
        sys.exit(f"{RED}[x] no wordlists found{RESET}")

    if mode == "-b":
        words = load_words(files, dns_mode=True)
        # adaptive: also try custom words as subdomains
        if adaptive and custom:
            extra = {w for w in custom if re.fullmatch(r"[a-z0-9\-]+", w)}
            words = list(set(words) | extra)
            status(f"adaptive seed: +{len(extra)} scraped words into DNS candidates")
        status(f"DNS sweep on {CYAN}{host}{RESET} — {len(words)} candidates")
        hits = await bust_subdomains(host, words)
        print(f"\n{BOLD}{GREEN}{'═' * 60}{RESET}")
        print(f"{BOLD}  ▸ RESULT: {len(hits)} live subdomains{RESET}")
        print(f"{BOLD}{GREEN}{'═' * 60}{RESET}")
        for sub, ip in sorted(hits):
            print(f"  {GREEN}●{RESET} {sub:<45} {DIM}{ip}{RESET}")
    else:
        baseline = get_baseline_sync(base)
        words = load_words(files)
        if adaptive and custom:
            before = len(words)
            words = list(set(words) | custom)
            status(f"adaptive seed: +{len(words) - before} scraped words merged into path list")
        status(f"phase 2/2 :: payload of {len(words)} paths ({CYAN}{CONCURRENCY}{RESET} concurrent)")
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
    target   = input(f"{BOLD}  :: target site{RESET} > ").strip()
    mode     = input(f"{BOLD}  :: mode  [-f paths | -b subdomains | -c crawl+wordlist only]{RESET} > ").strip().lower()
    admin    = input(f"{BOLD}  :: admin hunt  [-a or enter]{RESET} > ").strip().lower() == "-a"
    adaptive = input(f"{BOLD}  :: adaptive scraping (build wordlist from site) [Y/n]{RESET} > ").strip().lower()
    adaptive = adaptive in ("", "y", "yes")
    if mode not in ("-f", "-b", "-c"):
        sys.exit(f"{RED}[x] mode must be -f, -b, or -c{RESET}")
    asyncio.run(run(target, mode, admin, adaptive))
    typewriter("operation complete.", color=GREEN)

if __name__ == "__main__":
    main()
!pip -q install aiohttp

!python bymin.py
