from sqlalchemy.orm import Session
from app.models.portfolio import Portfolio
from app.models.lead import Lead


# 業種カテゴリ一覧（company_check.py と同じ）
INDUSTRY_CATEGORIES = [
    "飲食", "美容", "医療/介護", "建設/不動産", "小売/EC",
    "教育", "製造", "士業", "IT/Web", "サービス", "その他",
]

# サービス種別一覧
SERVICE_TYPES = {
    "web_renewal": "Webサイト制作・リニューアル",
    "ec": "ECサイト構築・改善",
    "seo": "SEO対策",
    "design": "デザイン改善",
    "other": "その他",
}


def get_portfolios_for_lead(db: Session, lead: Lead) -> list[Portfolio]:
    """リードの業種に合致するポートフォリオを取得する"""
    portfolios = []

    # 1. 業種一致で検索
    if lead.industry_category:
        portfolios = (
            db.query(Portfolio)
            .filter(
                Portfolio.industry_category == lead.industry_category,
                Portfolio.is_active == True,  # noqa: E712
            )
            .order_by(Portfolio.created_at.desc())
            .limit(3)
            .all()
        )

    # 2. 業種一致がなければ、全業種から最新を取得
    if not portfolios:
        portfolios = (
            db.query(Portfolio)
            .filter(Portfolio.is_active == True)  # noqa: E712
            .order_by(Portfolio.created_at.desc())
            .limit(2)
            .all()
        )

    return portfolios


def format_portfolio_for_prompt(portfolios: list[Portfolio]) -> str:
    """ポートフォリオ情報をClaudeプロンプト用テキストに整形する"""
    if not portfolios:
        return ""

    lines = ["自社の制作実績（ポートフォリオ）:"]
    for i, p in enumerate(portfolios, 1):
        line = f"  {i}. {p.title}"
        if p.client_name:
            line += f"（{p.client_name}様）"
        if p.industry_category:
            line += f" [業種: {p.industry_category}]"
        if p.description:
            line += f"\n     内容: {p.description}"
        if p.result_summary:
            line += f"\n     成果: {p.result_summary}"
        if p.url:
            line += f"\n     URL: {p.url}"
        lines.append(line)

    return "\n".join(lines)
