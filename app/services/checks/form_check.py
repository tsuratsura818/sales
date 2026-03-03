import logging
from bs4 import BeautifulSoup
import httpx

logger = logging.getLogger(__name__)


async def check_form(url: str, client: httpx.AsyncClient) -> dict:
    """問い合わせフォームの有無と複雑さを分析する"""
    result = {
        "has_contact_form": False,
        "form_field_count": 0,
        "has_file_upload": False,
    }

    try:
        # まずメインページのフォームをチェック
        resp = await client.get(url)
        if resp.status_code == 200:
            form_data = _analyze_forms(resp.text)
            if form_data["has_contact_form"]:
                return form_data

        # メインページにフォームがなければ、問い合わせページを探す
        contact_url = _find_contact_page(resp.text, url)
        if contact_url:
            try:
                resp2 = await client.get(contact_url)
                if resp2.status_code == 200:
                    form_data = _analyze_forms(resp2.text)
                    if form_data["has_contact_form"]:
                        return form_data
            except Exception:
                pass

    except Exception as e:
        logger.debug(f"フォーム分析エラー ({url}): {e}")

    return result


def _analyze_forms(html: str) -> dict:
    """HTMLからフォームを分析する"""
    result = {
        "has_contact_form": False,
        "form_field_count": 0,
        "has_file_upload": False,
    }

    soup = BeautifulSoup(html, "html.parser")
    forms = soup.find_all("form")

    if not forms:
        return result

    # 最も入力フィールドが多いフォームを採用（検索フォームを除外）
    best_form = None
    best_count = 0

    for form in forms:
        # 検索フォーム除外（role="search" or 1フィールドのみ）
        if form.get("role") == "search":
            continue

        fields = form.find_all(["input", "select", "textarea"])
        # hidden と submit を除外してカウント
        visible_fields = [
            f for f in fields
            if f.get("type") not in ("hidden", "submit", "button", "reset", "search")
        ]

        if len(visible_fields) > best_count:
            best_count = len(visible_fields)
            best_form = form

    if best_form and best_count >= 2:
        result["has_contact_form"] = True
        result["form_field_count"] = best_count

        # ファイルアップロード検出
        file_inputs = best_form.find_all("input", {"type": "file"})
        result["has_file_upload"] = len(file_inputs) > 0

    return result


def _find_contact_page(html: str, base_url: str) -> str | None:
    """HTMLからお問い合わせページのURLを探す"""
    soup = BeautifulSoup(html, "html.parser")

    contact_keywords = [
        "contact", "inquiry", "お問い合わせ", "問い合わせ",
        "問合せ", "お問合せ", "otoiawase", "toiawase",
    ]

    for a_tag in soup.find_all("a", href=True):
        href = a_tag.get("href", "")
        text = a_tag.get_text(strip=True).lower()
        href_lower = href.lower()

        for kw in contact_keywords:
            if kw in href_lower or kw in text:
                # 相対URLを絶対URLに変換
                if href.startswith("http"):
                    return href
                elif href.startswith("/"):
                    from urllib.parse import urlparse
                    parsed = urlparse(base_url)
                    return f"{parsed.scheme}://{parsed.netloc}{href}"

    return None
