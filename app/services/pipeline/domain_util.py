"""ドメイン正規化ユーティリティ (eTLD+1 相当)

list_generator_v3_1/src/state.py から移植。
重複排除キーとして使う正規化ドメインを生成する。
"""
from __future__ import annotations

from urllib.parse import urlparse

# 日本の2段TLD + 英米豪
TWO_LEVEL_TLDS = {
    "co.jp", "or.jp", "ne.jp", "ac.jp", "go.jp",
    "ed.jp", "lg.jp", "gr.jp", "ad.jp",
    "co.uk", "ac.uk", "gov.uk", "org.uk",
    "com.au", "net.au", "org.au",
}


def normalize_domain(url: str) -> str:
    """URL を eTLD+1 相当のドメイン文字列に正規化する。

    例:
      https://www.example.com/path  → example.com
      http://sub.example.com:8080   → example.com
      https://office.example.co.jp/ → example.co.jp
      example.com (スキーマなし)     → example.com
    """
    if not url:
        return ""
    try:
        # スキーマ無しでも netloc を拾えるよう補完
        if "://" not in url:
            url = "http://" + url
        domain = urlparse(url).netloc.lower()
        if not domain:
            return ""

        # ポート除去
        if ":" in domain:
            domain = domain.split(":", 1)[0]

        # 末尾ドット除去
        domain = domain.rstrip(".")
        if not domain:
            return ""

        parts = domain.split(".")
        if len(parts) >= 3:
            last_two = ".".join(parts[-2:])
            if last_two in TWO_LEVEL_TLDS:
                # foo.example.co.jp → example.co.jp
                return ".".join(parts[-3:])
            # sub.example.com → example.com
            return ".".join(parts[-2:])
        return domain
    except Exception:
        return ""


def same_domain(url_a: str, url_b: str) -> bool:
    """2つのURLが同じ正規化ドメインを指すか"""
    a = normalize_domain(url_a)
    b = normalize_domain(url_b)
    return bool(a) and a == b
