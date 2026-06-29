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
    "u003e", "u0040", "test@test", "name@", "mail@mail", "@email",
]
PRIORITY_LOCALPARTS = (
    "info", "contact", "sales", "mail", "support", "shop", "office",
    "inquiry", "order", "webmaster", "mailmag", "service",
)

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

    # 重複排除 + ゴミ除外
    out: list[str] = []
    seen: set[str] = set()
    for em in found:
        e = em.strip().strip(".,;")
        low = e.lower()
        if low in seen or len(e) > 100:
            continue
        if any(j in low for j in JUNK_EMAIL_SUBSTR):
            continue
        seen.add(low)
        out.append(e)

    # 並べ替え: 同一ドメイン > info等 > no-reply は後ろ
    base_dom = (page_domain or "").replace("www.", "")

    def rank(e: str) -> int:
        local, _, edom = e.lower().partition("@")
        r = 0
        if base_dom and base_dom in edom:
            r -= 10
        if local in PRIORITY_LOCALPARTS:
            r -= 5
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
