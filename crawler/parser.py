from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


def extract_text_and_links(html: str, base_url: str) -> tuple[str, str, list[str]]:
    """Returns (page_title, visible_text, absolute_links)."""
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""

    text = soup.get_text(" ", strip=True)

    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        absolute = urljoin(base_url, href).split("#")[0]
        if urlparse(absolute).scheme in ("http", "https"):
            links.append(absolute)

    return title, text, list(dict.fromkeys(links))  # de-dupe, keep order
