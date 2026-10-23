"""Fetch a saved link's title and length for the reading list. stdlib only:
urllib with a short timeout and a size cap, html.parser for the text.
Only called when the user saves a link and fetching isn't switched off."""
import math
import re
import urllib.error
import urllib.request
from html.parser import HTMLParser

TIMEOUT = 6
MAX_BYTES = 3 * 1024 * 1024
WPM = 230
_SKIP = {"script", "style", "noscript", "svg", "template", "head", "nav", "footer"}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.og_title = ""
        self._in_title = False
        self._skip = 0
        self.words = 0

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            a = dict(attrs)
            if a.get("property") == "og:title" and a.get("content"):
                self.og_title = a["content"].strip()
        if tag in _SKIP:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in _SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.words += len(re.findall(r"\w+", data))


def parse(html: str) -> dict:
    """{title, words, minutes} from an HTML page; minutes is None for an empty page."""
    p = _Text()
    try:
        p.feed(html)
        p.close()
    except Exception:  # html.parser is lenient, but never let a bad page break a save
        pass
    # The title comes from someone else's page: keep it plain text, no markup.
    title = re.sub(r"\s+", " ", re.sub(r"[<>]", "", p.og_title or p.title)).strip()
    minutes = max(1, math.ceil(p.words / WPM)) if p.words else None
    return {"title": title, "words": p.words, "minutes": minutes}


def fetch(url: str) -> dict:
    """Fetch and parse url. Raises OSError/ValueError on any failure."""
    req = urllib.request.Request(url, headers={"User-Agent": "hq (reading list)"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        ctype = resp.headers.get("Content-Type", "")
        if ctype and "html" not in ctype:
            raise ValueError(f"not an HTML page ({ctype.split(';')[0]})")
        raw = resp.read(MAX_BYTES)
        charset = resp.headers.get_content_charset() or "utf-8"
    try:
        text = raw.decode(charset, errors="replace")
    except LookupError:
        text = raw.decode("utf-8", errors="replace")
    return parse(text)
