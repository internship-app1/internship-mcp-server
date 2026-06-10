"""httpx client for the backend /api/v1 surface.

- Injects X-API-Key from INTERNSHIP_API_KEY.
- 401 → actionable "regenerate at /developer" message.
- 429 → surfaces Retry-After (remote compile concurrency cap).
- Network errors → retry with 2/4/8s backoff, then a legible failure.
- Responses are validated against the OpenAPI-mirrored models in schemas.py.

NO model calls here, ever.
"""
import time
from typing import Dict, Optional

import httpx

from . import config
from .schemas import CompileResponse, JobDetail, JobsResponse, PrefilterResponse

_RETRY_DELAYS = (2, 4, 8)


class BackendError(RuntimeError):
    """A legible, agent-displayable backend failure."""


def _request(method: str, path: str, **kwargs) -> httpx.Response:
    url = f"{config.api_url()}/api/v1{path}"
    headers = {"X-API-Key": config.api_key()}
    last_exc: Optional[Exception] = None
    for attempt, delay in enumerate((0,) + _RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            resp = httpx.request(method, url, headers=headers, timeout=60, **kwargs)
        except httpx.HTTPError as exc:
            last_exc = exc
            continue
        if resp.status_code == 401:
            raise BackendError(
                "Invalid or revoked API key — regenerate one at "
                f"{config.api_url()}/developer"
            )
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After", "60")
            raise BackendError(
                f"Rate limited by the backend (retry after {retry_after}s). "
                "For compiles, prefer COMPILE=local (Docker) — it has no limits."
            )
        if resp.status_code == 404:
            raise BackendError(resp.json().get("detail", "Not found"))
        if resp.status_code >= 500:
            last_exc = BackendError(f"Backend error {resp.status_code}")
            continue
        return resp
    raise BackendError(
        f"Backend unreachable after {len(_RETRY_DELAYS) + 1} attempts: {last_exc}"
    )


def jobs_list(
    since_hours: Optional[int] = None,
    max_days_old: int = 30,
    location: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> JobsResponse:
    params: Dict = {"max_days_old": max_days_old, "limit": limit, "offset": offset}
    if since_hours is not None:
        params["since_hours"] = since_hours
    if location:
        params["location"] = location
    if q:
        params["q"] = q
    resp = _request("GET", "/jobs", params=params)
    return JobsResponse.model_validate(resp.json())


def job_get(job_hash: str) -> JobDetail:
    resp = _request("GET", f"/jobs/{job_hash}")
    return JobDetail.model_validate(resp.json())


def jobs_prefilter(
    resume_profile: Dict, filters: Optional[Dict] = None, target_count: int = 40
) -> PrefilterResponse:
    body = {"resume_profile": resume_profile, "target_count": target_count}
    if filters:
        body["filters"] = filters
    resp = _request("POST", "/jobs/prefilter", json=body)
    return PrefilterResponse.model_validate(resp.json())


def resume_compile_remote(resume_json: Dict, options: Optional[Dict] = None) -> CompileResponse:
    body = {"resume_json": resume_json}
    if options:
        body["options"] = options
    resp = _request("POST", "/resume/compile", json=body)
    return CompileResponse.model_validate(resp.json())
