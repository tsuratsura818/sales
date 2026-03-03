from pydantic import BaseModel
import json


class LeadSummary(BaseModel):
    id: int
    url: str
    domain: str | None
    title: str | None
    status: str
    score: int
    is_https: bool | None
    has_viewport: bool | None
    copyright_year: int | None
    cms_type: str | None
    contact_email: str | None

    class Config:
        from_attributes = True


class LeadDetail(BaseModel):
    id: int
    url: str
    domain: str | None
    title: str | None
    status: str
    is_https: bool | None
    ssl_expiry_days: int | None
    domain_age_years: float | None
    copyright_year: int | None
    has_viewport: bool | None
    has_flash: bool | None
    cms_type: str | None
    cms_version: str | None
    pagespeed_score: int | None
    contact_email: str | None
    contact_page_url: str | None
    score: int
    score_breakdown: dict | None
    generated_email_subject: str | None
    generated_email_body: str | None
    analysis_error: str | None

    class Config:
        from_attributes = True

    @classmethod
    def from_orm(cls, obj):
        data = {c.name: getattr(obj, c.name) for c in obj.__table__.columns}
        if data.get("score_breakdown") and isinstance(data["score_breakdown"], str):
            try:
                data["score_breakdown"] = json.loads(data["score_breakdown"])
            except Exception:
                data["score_breakdown"] = {}
        return cls(**data)


class EmailUpdateRequest(BaseModel):
    subject: str
    body: str


class StatusUpdateRequest(BaseModel):
    status: str
