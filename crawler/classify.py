"""
Rough heuristic classification of what kind of page an address was found
on, based on keywords in the URL and page title.

This is a weak signal, not ground truth - a page titled "Support Our Work"
won't match "donate" and will fall through to "unknown". Treat source_type
as a hint worth weighting alongside domain_count when doing attribution,
not as a verified label. Extend _KEYWORDS as you learn what your actual
seed sites' pages look like.
"""

_KEYWORDS: dict[str, list[str]] = {
    "donation": ["donate", "donation", "support us", "charity", "tip jar"],
    "payment": ["pay with", "payment", "checkout", "invoice", "purchase", "buy now"],
    "exchange": ["exchange", "deposit address", "withdraw", "wallet address"],
    "forum": ["forum", "thread", "viewtopic", "showthread"],
    "social_media": ["twitter.com", "x.com", "reddit.com", "t.me", "telegram"],
    "code_repository": ["github.com", "gitlab.com"],
    "paste_site": ["pastebin", "paste.ee", "ghostbin"],
    "news_or_blog": ["/news/", "/blog/", "/article/", "/press/"],
    "contact_page": ["contact", "about us"],
}


def classify_source(url: str, page_title: str) -> str:
    haystack = f"{url} {page_title}".lower()
    for source_type, keywords in _KEYWORDS.items():
        if any(kw in haystack for kw in keywords):
            return source_type
    return "unknown"
