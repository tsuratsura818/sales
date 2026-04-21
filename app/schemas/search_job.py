from pydantic import BaseModel


class SearchRequest(BaseModel):
    query: str
    industry: str | None = None
    region: str | None = None
    num_results: int = 100
    search_method: str = "serpapi"  # "serpapi" or "local"
    filter_http_only: bool = False
    filter_no_mobile: bool = False
    filter_cms_list: list[str] = []
    # 収集後にローカル Claude Code で提案文を自動生成(default: True)
    auto_generate_proposal: bool = True
    # 自動生成の最低スコア(これ未満はスキップ。コスト抑制)
    auto_proposal_min_score: int = 50


class SearchJobResponse(BaseModel):
    job_id: int
    status: str
    message: str
