import logging
import re
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import httpx

logger = logging.getLogger(__name__)

# 業種判定キーワード辞書
INDUSTRY_KEYWORDS = {
    "飲食": [
        "レストラン", "飲食", "居酒屋", "カフェ", "cafe", "restaurant",
        "ラーメン", "寿司", "sushi", "焼肉", "パン屋", "ベーカリー",
        "弁当", "ケータリング", "食堂", "bar", "ダイニング", "グルメ",
    ],
    "美容": [
        "美容室", "ヘアサロン", "hair", "salon", "エステ", "ネイル",
        "nail", "beauty", "脱毛", "まつげ", "アイラッシュ", "理容",
        "スパ", "リラクゼーション", "massage", "マッサージ",
    ],
    "医療/介護": [
        "病院", "クリニック", "clinic", "歯科", "dental", "医院",
        "薬局", "pharmacy", "介護", "福祉", "デイサービス", "整骨院",
        "整体", "接骨院", "鍼灸", "眼科", "皮膚科", "内科", "外科",
    ],
    "建設/不動産": [
        "不動産", "建設", "建築", "工務店", "リフォーム", "住宅",
        "マンション", "賃貸", "real estate", "construction", "設計事務所",
        "塗装", "外壁", "屋根", "エクステリア", "造園",
    ],
    "小売/EC": [
        "ショップ", "shop", "store", "通販", "オンラインショップ",
        "ネットショップ", "販売", "セレクト", "ストア",
    ],
    "教育": [
        "学校", "塾", "スクール", "school", "教室", "academy",
        "予備校", "学習", "教育", "幼稚園", "保育", "大学",
    ],
    "製造": [
        "製造", "工場", "factory", "manufacturing", "メーカー",
        "加工", "部品", "金属", "プラスチック", "化学",
    ],
    "士業": [
        "弁護士", "税理士", "会計士", "司法書士", "行政書士",
        "社労士", "弁理士", "法律事務所", "税理士事務所", "法務",
    ],
    "IT/Web": [
        "システム開発", "ソフトウェア", "software", "IT", "web制作",
        "ホームページ制作", "アプリ", "SaaS", "クラウド", "プログラミング",
    ],
    "サービス": [
        "サービス", "コンサルティング", "consulting", "人材", "派遣",
        "清掃", "引越し", "運送", "物流", "旅行", "ホテル", "旅館",
        "ウェディング", "葬儀", "ペット", "写真", "フォト",
    ],
}


async def check_company(url: str, client: httpx.AsyncClient) -> dict:
    """会社規模と業種を推定する"""
    result = {
        "estimated_page_count": None,
        "company_size_estimate": None,
        "industry_category": None,
    }

    try:
        # メインページからタイトル・メタ情報取得
        resp = await client.get(url)
        if resp.status_code != 200:
            return result

        soup = BeautifulSoup(resp.text, "html.parser")

        # 業種判定
        result["industry_category"] = _detect_industry(soup, url)

        # sitemapからページ数推定
        page_count = await _count_sitemap_pages(url, client)
        result["estimated_page_count"] = page_count

        # 会社規模推定
        result["company_size_estimate"] = _estimate_company_size(page_count)

    except Exception as e:
        logger.debug(f"会社チェックエラー ({url}): {e}")

    return result


def _detect_industry(soup: BeautifulSoup, url: str) -> str:
    """HTML内容から業種を推定する"""
    # テキスト収集（title + meta description + h1 + URL）
    texts = []

    title_tag = soup.find("title")
    if title_tag:
        texts.append(title_tag.get_text(strip=True))

    meta_desc = soup.find("meta", {"name": "description"})
    if meta_desc:
        texts.append(meta_desc.get("content", ""))

    for h1 in soup.find_all("h1"):
        texts.append(h1.get_text(strip=True))

    # URLのパス部分も参考に
    texts.append(url)

    combined = " ".join(texts).lower()

    # スコアベースで業種判定
    scores = {}
    for industry, keywords in INDUSTRY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in combined)
        if score > 0:
            scores[industry] = score

    if scores:
        return max(scores, key=scores.get)

    # schema.orgによる判定
    schema_type = _detect_schema_type(soup)
    if schema_type:
        return schema_type

    return "その他"


def _detect_schema_type(soup: BeautifulSoup) -> str | None:
    """schema.orgの型から業種を推定"""
    import json

    for script in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, list):
                data = data[0] if data else {}
            schema_type = data.get("@type", "")

            type_map = {
                "Restaurant": "飲食",
                "FoodEstablishment": "飲食",
                "BarOrPub": "飲食",
                "BeautySalon": "美容",
                "HairSalon": "美容",
                "HealthAndBeautyBusiness": "美容",
                "MedicalBusiness": "医療/介護",
                "Dentist": "医療/介護",
                "Hospital": "医療/介護",
                "Physician": "医療/介護",
                "RealEstateAgent": "建設/不動産",
                "Store": "小売/EC",
                "EducationalOrganization": "教育",
                "School": "教育",
                "LegalService": "士業",
                "Attorney": "士業",
            }

            if schema_type in type_map:
                return type_map[schema_type]
        except Exception:
            pass

    return None


async def _count_sitemap_pages(url: str, client: httpx.AsyncClient) -> int | None:
    """sitemapからページ数をカウントする"""
    parsed = urlparse(url)
    sitemap_url = f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"

    try:
        resp = await client.get(sitemap_url, timeout=10)
        if resp.status_code != 200:
            return None

        content = resp.text
        # <loc>タグの数をカウント
        loc_count = len(re.findall(r"<loc>", content, re.IGNORECASE))

        # sitemapindex の場合、子sitemapの数 × 推定ページ数
        if "<sitemapindex" in content.lower():
            return loc_count * 50  # 各子sitemapに平均50ページと推定

        return loc_count if loc_count > 0 else None
    except Exception:
        return None


def _estimate_company_size(page_count: int | None) -> str | None:
    """ページ数から会社規模を推定する"""
    if page_count is None:
        return None

    if page_count <= 10:
        return "small"
    elif page_count <= 50:
        return "medium"
    elif page_count <= 200:
        return "mid_large"
    else:
        return "large"
