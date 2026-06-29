import re
import httpx
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

EMAIL_PATTERN = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')

# メールが載りやすいサブページ（優先度順: 特商法 > 会社概要 > 問い合わせ > プライバシー）
# (日本語キーワード, URL内英語キーワード, 優先度)
SUBPAGE_HINTS = [
    ("特定商取引", "tokusho", 0),
    ("特商法", "tokushoho", 0),
    ("商取引", "specified", 0),
    ("会社概要", "company", 1),
    ("会社案内", "about", 1),
    ("企業情報", "corporate", 1),
    ("運営者", "operator", 1),
    ("店舗情報", "store", 1),
    ("お問い合わせ", "contact", 2),
    ("問い合わせ", "inquiry", 2),
    ("問合せ", "toiawase", 2),
    ("プライバシー", "privacy", 3),
]

# メールアドレスとして無効・ノイズになりやすい文字列
JUNK_EMAIL_SUBSTR = [
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js",
    "example.com", "example.co", "example.org", "yourdomain", "your-domain",
    "domain.com", "sentry", "wixpress", "googlemail.com", "@2x", "@3x",
    "u003e", "u0040", "@email", "xyz.co", "xyz.com", "abc.com",
]
# ダミー/プレースホルダのローカルパート（abc@ / sample@ / test@ 等は実在しない）
PLACEHOLDER_LOCALPARTS = {
    "abc", "xyz", "sample", "test", "example", "dummy", "foo", "bar",
    "aaa", "bbb", "ccc", "hoge", "your", "yourname", "name", "mailaddress",
    "username", "mail-address", "address", "email", "yyy", "xxx", "mail",
}
PRIORITY_LOCALPARTS = (
    "info", "contact", "sales", "support", "shop", "office",
    "inquiry", "order", "webmaster", "mailmag", "service",
)
# 個人事業主がよく使うフリーメール（同一ドメインでなくても採用してよい）
FREEMAIL_DOMAINS = {
    "gmail.com", "yahoo.co.jp", "yahoo.com", "outlook.com", "outlook.jp",
    "hotmail.com", "hotmail.co.jp", "icloud.com", "me.com", "aol.com",
    "ymail.com", "live.jp", "msn.com", "nifty.com", "ezweb.ne.jp",
}
# ドメイン照合で無視するラベル
_TLDISH = {
    "co", "ne", "or", "go", "ac", "ed", "gr", "lg", "jp", "com", "net",
    "org", "info", "biz", "shop", "store", "online", "site", "tokyo", "work",
}


def _domain_core(domain: str) -> set[str]:
    """ドメインの主要ラベル(4文字以上, TLD除く)集合を返す。"""
    d = domain.lower().replace("www.", "")
    return {p for p in d.split(".") if len(p) >= 4 and p not in _TLDISH}


def _is_same_site(email_domain: str, site_domain: str) -> bool:
    e = email_domain.lower().replace("www.", "")
    s = site_domain.lower().replace("www.", "")
    if e == s or e.endswith("." + s) or s.endswith("." + e):
        return True
    return bool(_domain_core(e) & _domain_core(s))

# 難読化（info＠example.com / info[at]example.com 等）を素のメールに戻す
_DEOBF = [
    (re.compile(r'\s*[\[\(（【]\s*at\s*[\]\)）】]\s*', re.I), '@'),
    (re.compile(r'\s*[\[\(（【]\s*dot\s*[\]\)）】]\s*', re.I), '.'),
    (re.compile(r'\s*[\[\(（【]\s*アット\s*[\]\)）】]\s*'), '@'),
    (re.compile(r'\s*[\[\(（【]\s*ドット\s*[\]\)）】]\s*'), '.'),
]


def _deobfuscate(text: str) -> str:
    t = text.replace('＠', '@')
    for pat, rep in _DEOBF:
        t = pat.sub(rep, t)
    return t


def _emails_from_html(html: str, page_domain: str) -> list[str]:
    """HTML から有効なメール候補を優先順に返す。"""
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")

    found: list[str] = []

    # 1) mailto: リンク（最も信頼度が高い）
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().startswith("mailto:"):
            em = href[7:].split("?")[0].strip().strip(".,;")
            if EMAIL_PATTERN.fullmatch(em):
                found.append(em)

    # 2) テキスト/HTML 内（難読化解除してから正規表現）
    text = _deobfuscate(soup.get_text(" ")) + "\n" + _deobfuscate(html)
    found.extend(EMAIL_PATTERN.findall(text))

    # 重複排除 + ゴミ/ダミー/第三者ドメイン 除外
    out: list[str] = []
    seen: set[str] = set()
    for em in found:
        e = em.strip().strip(".,;")
        low = e.lower()
        if low in seen or len(e) > 100:
            continue
        local, _, edom = low.partition("@")
        if any(j in low for j in JUNK_EMAIL_SUBSTR):
            continue
        if local in PLACEHOLDER_LOCALPARTS:
            continue
        # サイトと同一ドメイン or フリーメール以外は第三者(埋め込み/ポータル運営者/例示)
        # の可能性が高いので採用しない
        if page_domain and not (_is_same_site(edom, page_domain) or edom in FREEMAIL_DOMAINS):
            continue
        seen.add(low)
        out.append(e)

    # 並べ替え: 同一ドメイン > info等 > no-reply/フリーメールは後ろ
    def rank(e: str) -> int:
        local, _, edom = e.lower().partition("@")
        r = 0
        if page_domain and _is_same_site(edom, page_domain):
            r -= 10
        if local in PRIORITY_LOCALPARTS:
            r -= 5
        if edom in FREEMAIL_DOMAINS:
            r += 3
        if local.startswith(("no-reply", "noreply", "donotreply")):
            r += 8
        return r

    out.sort(key=rank)
    return out


async def extract_contact(url: str, client: httpx.AsyncClient) -> dict:
    """サイトからメールアドレスと問い合わせページURLを抽出する。

    トップページに無ければ、特商法/会社概要/お問い合わせ ページも巡回して探す。
    """
    result = {"contact_email": None, "contact_page_url": None}

    try:
        resp = await client.get(url, follow_redirects=True, timeout=8)
        html = resp.text
        final = str(resp.url)
        domain = urlparse(final).netloc
        base = f"{urlparse(final).scheme}://{domain}"

        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            soup = BeautifulSoup(html, "html.parser")

        # サブページ候補を優先度つきで収集
        candidates: list[tuple[int, str]] = []
        seen_urls: set[str] = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            hl = href.lower()
            text = a.get_text().lower()
            for kw_jp, kw_en, prio in SUBPAGE_HINTS:
                if kw_jp in text or kw_jp in href or (kw_en and kw_en in hl):
                    full = urljoin(base, href)
                    if urlparse(full).netloc != domain:
                        break
                    if full not in seen_urls:
                        seen_urls.add(full)
                        candidates.append((prio, full))
                    if result["contact_page_url"] is None and prio == 2:
                        result["contact_page_url"] = full
                    break

        # トップページから抽出
        emails = _emails_from_html(html, domain)

        # 無ければ優先度順にサブページを巡回（最大3ページ）
        if not emails:
            candidates.sort(key=lambda x: x[0])
            for _prio, sp in candidates[:3]:
                try:
                    r2 = await client.get(sp, follow_redirects=True, timeout=6)
                    if r2.status_code == 200:
                        emails = _emails_from_html(r2.text, domain)
                        if emails:
                            if result["contact_page_url"] is None:
                                result["contact_page_url"] = sp
                            break
                except Exception:
                    continue

        if emails:
            result["contact_email"] = emails[0]

    except Exception:
        pass

    return result
