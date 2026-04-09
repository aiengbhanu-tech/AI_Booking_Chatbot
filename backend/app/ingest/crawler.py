import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.core.config import settings


def _normalize_url(u: str) -> str:
    # strip fragments
    parsed = urlparse(u)
    return parsed._replace(fragment="").geturl()


def fetch_sitemap_urls(website_url: str) -> list[str]:
    """
    Try:
      - {site}/sitemap.xml
    Return list of urls.
    """
    base = website_url.rstrip("/")
    sitemap = urljoin(base + "/", "sitemap.xml")
    urls: list[str] = []

    with httpx.Client(timeout=settings.CRAWL_TIMEOUT_SECONDS, follow_redirects=True) as client:
        r = client.get(sitemap)
        if r.status_code >= 400:
            return []
        soup = BeautifulSoup(r.text, "xml")
        for loc in soup.find_all("loc"):
            if loc.text:
                urls.append(_normalize_url(loc.text.strip()))
    return urls


def crawl_internal_pages(website_url: str, max_pages: int | None = None) -> list[str]:
    """
    Simple internal crawler starting from homepage.
    """
    max_pages = max_pages or settings.CRAWL_MAX_PAGES
    base = website_url.rstrip("/") + "/"
    base_host = urlparse(base).netloc

    visited: set[str] = set()
    queue: list[str] = [base]

    with httpx.Client(timeout=settings.CRAWL_TIMEOUT_SECONDS, follow_redirects=True,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; AI-Agent/1.0)"}) as client:
        while queue and len(visited) < max_pages:
            url = _normalize_url(queue.pop(0))
            if url in visited:
                continue
            if urlparse(url).netloc != base_host:
                continue

            try:
                r = client.get(url)
                if r.status_code >= 400:
                    visited.add(url)
                    continue
                visited.add(url)

                html = r.text
                soup = BeautifulSoup(html, "lxml")
                for a in soup.find_all("a", href=True):
                    href = a["href"].strip()
                    if href.startswith("mailto:") or href.startswith("tel:"):
                        continue
                    if href.startswith("#"):
                        continue
                    nxt = urljoin(url, href)
                    nxt = _normalize_url(nxt)
                    if urlparse(nxt).netloc == base_host:
                        queue.append(nxt)
            except Exception:
                visited.add(url)
                continue

    # Avoid weird urls like javascript:void
    cleaned = [u for u in visited if not re.search(r"javascript:|void\(0\)", u, re.I)]
    # stable ordering
    cleaned.sort()
    return cleaned


def fetch_html(url: str) -> str:
    with httpx.Client(timeout=settings.CRAWL_TIMEOUT_SECONDS, follow_redirects=True,
    headers={"User-Agent": "Mozilla/5.0 (compatible; AI-Agent/1.0)"}) as client:
        r = client.get(url)
        r.raise_for_status()
        return r.text