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


class SearchJobResponse(BaseModel):
    job_id: int
    status: str
    message: str
