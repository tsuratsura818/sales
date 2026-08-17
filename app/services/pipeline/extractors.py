"""情報抽出モジュール（eigyoから移植）"""
import re
from .config import TARGET_AREAS, EXCLUDE_NAMES

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

# HTML内の文字コード宣言（<meta charset=...> / <meta http-equiv=... charset=...>）
_META_CHARSET_RE = re.compile(
    rb"""<meta[^>]+charset\s*=\s*["']?\s*([a-zA-Z0-9_\-]+)""", re.IGNORECASE
)


def decode_html(resp) -> str:
    """httpx のレスポンスを正しい文字コードで文字列にする。

    `resp.text` は Content-Type ヘッダの charset を信じるが、古い日本語サイトは
    ヘッダに charset を書かず HTML の meta タグにだけ書いていることが多い。
    その場合 httpx が UTF-8 と誤推定し、Shift_JIS のページが
    「�}�Y���[」のように化ける（収集した会社名がそのまま営業メールの宛名に入る）。

    優先順位: ヘッダのcharset → HTMLのmeta宣言 → 文字コード自動判定。
    """
    content = resp.content
    if not content:
        return ""

    # 1) ヘッダに明示されていればそれを使う
    header_charset = None
    ctype = resp.headers.get("content-type", "")
    m = re.search(r"charset=([a-zA-Z0-9_\-]+)", ctype, re.IGNORECASE)
    if m:
        header_charset = m.group(1)

    # 2) HTML の meta 宣言（先頭4KBを見れば十分）
    meta_charset = None
    mm = _META_CHARSET_RE.search(content[:4096])
    if mm:
        meta_charset = mm.group(1).decode("ascii", "ignore")

    for enc in (header_charset, meta_charset):
        if not enc:
            continue
        try:
            decoded = content.decode(enc, errors="strict")
        except (LookupError, UnicodeDecodeError):
            continue
        return decoded

    # 3) 自動判定（bs4 同梱。日本語の Shift_JIS / EUC-JP を拾える）
    try:
        from bs4 import UnicodeDammit
        dammit = UnicodeDammit(content, is_html=True)
        if dammit.unicode_markup:
            return dammit.unicode_markup
    except Exception:
        pass

    return content.decode("utf-8", errors="replace")
EXCLUDE_EMAIL_DOMAINS = {"example.com", "test.com", "sentry.io", "wixpress.com", "shopify.com"}


def extract_emails(text: str) -> list[str]:
    """テキストからメールアドレスを抽出（除外フィルタ付き）"""
    matches = EMAIL_RE.findall(text)
    result = []
    for e in matches:
        e_lower = e.lower()
        domain = e_lower.split("@")[1]
        if domain in EXCLUDE_EMAIL_DOMAINS:
            continue
        if e_lower.startswith(("noreply", "no-reply", "test@", "example@", "abuse@", "postmaster@")):
            continue
        if e_lower.endswith((".png", ".jpg", ".gif", ".svg", ".webp")):
            continue
        if "rakuten" in domain or "yahoo.co.jp" == domain or "amazon" in domain:
            continue
        result.append(e)
    return list(dict.fromkeys(result))


# 会社名の前後に紛れ込む項目ラベル。
# 特商法ページは表組みが多く、テキスト化すると
# 「販売業者：（商号）株式会社◯◯郵便番号〒141-0021」のように
# 前後のセルが繋がってしまう。会社名は営業メールの宛名に使うので必ず落とす。
_COMPANY_LEADING_LABELS = re.compile(
    r"^[\s　]*(?:[（(]\s*(?:商号|屋号|名称|会社名|法人名)\s*[）)]|"
    r"(?:商号|屋号|名称|会社名|法人名|販売業者|事業者)[：:\s]*)"
)
_COMPANY_TRAILING_LABELS = re.compile(
    r"\s*(?:郵便番号|〒|所在地|住所|代表者|代表取締役|責任者|電話番号|電話|TEL|Tel|FAX|Fax|"
    r"メールアドレス|メール|E-?mail|URL|ホームページ|事業内容|運営統括|運営|"
    r"販売価格|支払|送料|返品|お問い合わせ).*$",
    re.IGNORECASE,
)


# 法人格を含む社名。ページタイトルから社名部分だけを取り出すために使う。
_CORP = r"(?:株式会社|有限会社|合同会社|合資会社|合名会社|一般社団法人|一般財団法人|公益社団法人|公益財団法人|医療法人|学校法人)"
# 「株式会社◯◯」（前置）を先に試す。日本語の社名はこちらが多数で、
# 「◯◯株式会社」を先に試すと「神戸のあんこやさん株式会社」のように
# 直前の説明文まで社名として拾ってしまう。
# 社名の直後に付く売場・サイト名。社名の一部ではないので落とす。
_SHOP_SUFFIX = re.compile(
    r"(?:オンラインショップ|オンラインストア|公式(?:通販)?(?:サイト|ショップ|ストア)?|"
    r"通販(?:サイト|ショップ)?|本店|ネットショップ|ショップ|ストア|WEBSHOP|Web[Ss]hop)$"
)

# ページ名がそのまま社名の後ろに付いたもの。社名の一部ではないので落とす。
# 例:「まいど！おおきに屋クラクラ [会社概要]」「特定商取引法に基づく表記 - 大浜海苔店」
_PAGE_LABEL = re.compile(
    r"\s*[\[［(（【]?\s*(?:会社概要|企業情報|店舗情報|特定商取引法に基づく表記|"
    r"特定商取引法|お問い合わせ|返品について|プライバシーポリシー|利用規約)"
    r"\s*[\]］)）】]?\s*"
)

_CORP_NAME_RES = [
    re.compile(rf"({_CORP}[^\s　｜|/／、。（()\[\]【】]{{2,20}})"),
    re.compile(rf"([^\s　｜|/／、。（()\[\]【】]{{2,20}}{_CORP})"),
]


def clean_company_name(name: str) -> str:
    """抽出した会社名から前後のラベル・住所等のノイズを落とす"""
    if not name:
        return ""
    name = name.strip()

    # ページ名（[会社概要] 等）は社名の前後どちらにも付くので先に落とす
    name = _PAGE_LABEL.sub(" ", name).strip(" -‐-–—|｜")

    # 先に前後のラベルを落とす（「（商号）」等が残ると社名の抽出を誤る）
    for _ in range(3):
        new = _COMPANY_LEADING_LABELS.sub("", name).strip()
        if new == name:
            break
        name = new
    name = _COMPANY_TRAILING_LABELS.sub("", name).strip()

    # ページタイトルがそのまま入っている場合は社名だけ取り出す。
    # 例: 「赤穂市の老舗和菓子屋 株式会社岡友恵堂 | 株式会社岡友惠堂は、兵庫県…です。19」
    #  →「株式会社岡友恵堂」
    if len(name) > 24 or "｜" in name or "|" in name or "は、" in name:
        for pat in _CORP_NAME_RES:
            m = pat.search(name)
            if m and len(m.group(1)) > len("株式会社"):
                # 社名の後ろに付く売場名（オンラインショップ等）は落とす
                return _SHOP_SUFFIX.sub("", m.group(1)).strip()
        # 法人格が無ければ区切り文字の手前までを社名とみなす
        name = re.split(r"[｜|/／]|は、", name)[0].strip()
    # 記号のみの残骸や区切り文字を落とす
    name = re.sub(r"^[\s　:：\-–—|｜/]+", "", name)
    name = re.sub(r"[\s　:：\-–—|｜/]+$", "", name)
    return name.strip()


# 会社名として成立しない文字列の特徴。
# 収集元がページタイトルなので、記事見出し・ページ分類名・楽曲名などが
# そのまま会社名欄に入ることがある（実測: 在庫18件中11件）。
# これが宛名になると「秋田観光スポット12選！… ご担当者様」のような
# メールが出来上がるため、生成前に落とす。
_NOT_COMPANY_PATTERNS = [
    r"\d+\s*選\b",                      # 「12選」
    # 感嘆符・疑問符は記事見出しの特徴だが、屋号の一部のこともある
    # （例:「まいど！おおきに屋クラクラ」）。文の途中に現れ、かつ長いものだけ落とす。
    r"[！!？?].{14,}",
    r"ランキング|おすすめ|まとめ|比較|口コミ|評判|徹底|完全ガイド|特集",
    r"とは[？?]?$",
    r"^(?:加盟|会員|参加)(?:企業|店舗|団体)",   # ページ分類名
    r"（?都道府県別）?$|一覧$|カテゴリ$|検索結果$",
    r"^Working at\b|^Jobs? at\b",        # 求人ページ
    r"feat\.|【.*】.*[×xX].*",            # 楽曲・コラボ表記
    r"の(?:観光|旅行)ガイド$",
    r"(?:オープン|開店|閉店|新発売|発売|登場)$",   # ニュース見出し
    r"^[^\s　]{2,6}(?:市内|県内|市|区)初",          # 「青森市内初 〜」
]
_NOT_COMPANY_RE = [re.compile(p, re.IGNORECASE) for p in _NOT_COMPANY_PATTERNS]


def looks_like_company(name: str) -> bool:
    """営業メールの宛名に使える会社名・屋号らしいか。

    法人格が無くても店名・屋号なら通す。判断がつかないものは False に倒す
    （レビュー無しで送るため、通すより落とす方が安全）。
    """
    if not name:
        return False
    n = name.strip()
    if len(n) < 2 or len(n) > 30:
        return False
    # 法人格があれば会社名とみなす
    if re.search(_CORP, n):
        return True
    for pat in _NOT_COMPANY_RE:
        if pat.search(n):
            return False
    # 日本語をまったく含まない（英文の記事見出し等）
    if not re.search(r"[ぁ-んァ-ヶ一-龠]", n):
        return False
    # 助詞や読点を含む文章はページタイトル
    if re.search(r"[、。]|[はがをにでとも]\s", n):
        return False
    # 空白区切りの語が3つ以上あるのは検索語の羅列（SEO用タイトル）。
    # 例:「神戸 洋菓子 ギフト専門店 神戸洋藝菓子ボックサン」
    if len(re.split(r"[\s　]+", n)) >= 3:
        return False
    return True


def extract_company(text: str) -> str:
    """特商法ページから販売業者名を抽出"""
    patterns = [
        r"(?:販売業者|事業者の名称|事業者名|会社名|運営会社|法人名)[：:\s]*([^\n\r]{2,60})",
        r"(?:ショップ名|店舗名|屋号)[：:\s]*([^\n\r]{2,60})",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            name = clean_company_name(m.group(1))
            if len(name) > 1:
                return name
    return ""


def extract_address(text: str) -> str:
    """住所を抽出"""
    patterns = [
        r"(?:所在地|事業者の所在地|事業者の住所|住所)[：:\s]*(〒?\d{3}-?\d{4}[^\n\r]{5,80})",
        r"(?:所在地|事業者の住所|住所)[：:\s]*([^\n\r]{5,80})",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            addr = m.group(1).strip()
            addr = re.sub(r"\s*(電話|TEL|Tel|代表|メール|FAX).*$", "", addr)
            return addr
    return ""


def is_kansai(text: str) -> bool:
    """関西エリアに該当するか"""
    return any(area in text for area in TARGET_AREAS)


def is_excluded(company: str) -> bool:
    """大手企業除外チェック"""
    return any(exc in company for exc in EXCLUDE_NAMES)


def detect_ec_platform(html: str) -> str:
    """HTMLからECプラットフォームを検出"""
    html_lower = html.lower()
    if "cdn.shopify.com" in html_lower or "myshopify.com" in html_lower:
        return "Shopify構築済み"
    if "base.shop" in html_lower or "thebase.in" in html_lower:
        return "BASE利用中"
    if "stores.jp" in html_lower:
        return "STORES利用中"
    if "shop-pro.jp" in html_lower:
        return "カラーミー利用中"
    if "makeshop" in html_lower:
        return "MakeShop利用中"
    if "futureshop" in html_lower:
        return "FutureShop利用中"
    # カート判定は複合条件で偽陽性を抑制（カートボタン+商品ページの両方が存在）
    has_cart = "cart" in html_lower or "カートに入れる" in html_lower or "add to cart" in html_lower
    has_product = "商品" in html_lower or "product" in html_lower or "price" in html_lower
    if has_cart and has_product:
        return "自社ECあり"
    return ""
