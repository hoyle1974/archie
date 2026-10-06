"""Plain text from HTML, for mail bodies with no text part (gmail.py) and fetched web pages (web.py)."""

from __future__ import annotations

import re
from html import unescape


def html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", html)
    return unescape(re.sub(r"<[^>]+>", "", html))


def page_text(html: str) -> str:
    """A web page's readable text: no head, scripts, styles or markup, and no runs of blank space."""
    html = re.sub(r"(?is)<(head|noscript|svg|template|nav|footer)\b.*?</\1>", "", html)
    html = re.sub(r"(?i)</h[1-6]>|</tr>|</section>|</article>", "\n", html)
    text = re.sub(r"[ \t\r\f\v]+", " ", html_to_text(html))
    return re.sub(r"\n\s*\n+", "\n\n", "\n".join(line.strip() for line in text.splitlines())).strip()


def html_title(html: str) -> str:
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    return " ".join(unescape(m.group(1)).split()) if m else ""
