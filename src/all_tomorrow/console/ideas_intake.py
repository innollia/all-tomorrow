"""Free-form intake for the idea desk: whatever the user researched on their own, in any shape.

Accepts pasted text (chat logs, notes, article bodies), links (a bare URL is enough) and uploaded files
(md, txt, pdf; other text-like files are read as text). Turns each into an item
{kind, label, url, title, body, note} that `IdeaStore.intake` files under an idea. Nothing here calls Jev
and nothing here may make the intake fail as a whole: a link that cannot be fetched is still kept as a link,
a PDF whose text cannot be read is still kept as a file.
"""
from __future__ import annotations

import base64
import binascii
import ipaddress
import re
import socket
import zlib
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

URL = re.compile(r"https?://[^\s<>\"'`)\]]+", re.I)
MAX_BODY = 500_000
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_PAGE_BYTES = 3 * 1024 * 1024
TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".text", ".csv", ".json", ".log", ".rst"}
NOISE_TAGS = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "iframe"}
BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "pre", "blockquote"}


def only_urls(text: str) -> list[str]:
    """The URLs when the text is nothing but links (one or more, any whitespace between); else []."""
    rest = URL.sub(" ", text)
    return [m.group(0).rstrip(".,;") for m in URL.finditer(text)] if not re.search(r"\w", rest) else []


def first_line(text: str, limit: int = 60) -> str:
    for line in text.replace("\r\n", "\n").split("\n"):
        line = re.sub(r"^[#>*\-\s]+", "", line).strip()
        if line:
            return line[:limit]
    return "(제목 없음)"


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self.skip = 0
        self.in_title = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "title":
            self.in_title = True
        elif tag in NOISE_TAGS:
            self.skip += 1
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        elif tag in NOISE_TAGS and self.skip:
            self.skip -= 1
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title += data
        elif not self.skip:
            self.parts.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    """(title, readable text) of an HTML page; a parser error returns what was read so far."""
    parser = _Text()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - broken markup is common; keep what was read
        pass
    lines = [re.sub(r"[ \t ]+", " ", line).strip() for line in "".join(parser.parts).split("\n")]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return re.sub(r"\s+", " ", parser.title).strip(), text


def decode_text(data: bytes) -> str | None:
    for encoding in ("utf-8-sig", "cp949"):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        return None if "\x00" in text else text
    return None


def public_host(host: str) -> bool:
    """False for loopback, private, link-local and other non-public addresses (the console must not become a proxy
    into this PC or the tailnet)."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global:
            return False
    return bool(infos)


def fetch_page(url: str, timeout: float = 15) -> dict[str, str]:
    """{title, body, note}. A failure gives an empty body and a note saying why; it never raises."""
    import httpx

    current = url
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False,
                          headers={"User-Agent": "Mozilla/5.0 (all-tomorrow idea desk)"}) as client:
            for _ in range(5):
                parsed = urlparse(current)
                if parsed.scheme not in ("http", "https") or not parsed.hostname or not public_host(parsed.hostname):
                    return {"title": "", "body": "", "note": "공개 주소가 아니라 가져오지 않음"}
                with client.stream("GET", current) as response:
                    if response.is_redirect and response.headers.get("location"):
                        current = urljoin(current, response.headers["location"])
                        continue
                    if response.status_code >= 400:
                        return {"title": "", "body": "", "note": f"가져오기 실패: HTTP {response.status_code}"}
                    raw = b""
                    for chunk in response.iter_bytes():
                        raw += chunk
                        if len(raw) > MAX_PAGE_BYTES:
                            break
                    kind = response.headers.get("content-type", "").lower()
                    encoding = response.charset_encoding or "utf-8"
                break
            else:
                return {"title": "", "body": "", "note": "가져오기 실패: 리다이렉트가 너무 많음"}
    except Exception as error:  # noqa: BLE001 - network failures are data here
        return {"title": "", "body": "", "note": f"가져오기 실패: {type(error).__name__}"}
    if "pdf" in kind or raw[:5] == b"%PDF-":
        text = pdf_text(raw)
        return {"title": Path(urlparse(current).path).name, "body": text,
                "note": "" if text else "PDF 글자를 읽지 못함"}
    text = raw.decode(encoding, "replace")
    if "html" in kind or re.search(r"<html|<body|<p[ >]", text[:2000], re.I):
        title, body = html_to_text(text)
        return {"title": title, "body": body, "note": "" if body else "본문을 읽지 못함 (스크립트로 그리는 페이지일 수 있음)"}
    return {"title": "", "body": text.strip(), "note": ""}


PDF_STREAM = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)
PDF_STRING = re.compile(rb"\((?:\\.|[^\\()])*\)")
PDF_ESC = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f", b"(": b"(", b")": b")", b"\\": b"\\"}


def _pdf_literal(token: bytes) -> str:
    inner = token[1:-1]
    out = bytearray()
    i = 0
    while i < len(inner):
        c = inner[i:i + 1]
        if c == b"\\" and i + 1 < len(inner):
            n = inner[i + 1:i + 2]
            if n in PDF_ESC:
                out += PDF_ESC[n]
                i += 2
            elif n.isdigit():
                m = re.match(rb"[0-7]{1,3}", inner[i + 1:])
                if m:
                    out.append(int(m.group(0), 8) & 0xFF)
                i += 1 + (len(m.group(0)) if m else 1)
            else:
                i += 2
        else:
            out += c
            i += 1
    try:
        return out.decode("utf-16-be") if out[:2] == b"\xfe\xff" else out.decode("latin-1")
    except UnicodeDecodeError:
        return ""


def pdf_text(data: bytes) -> str:
    """Text of a PDF. pypdf when it is installed; otherwise a small reader that handles plain (non-subset-font)
    text streams. Scans and fonts it cannot decode give "" — the caller keeps the file anyway."""
    try:
        import io

        from pypdf import PdfReader  # type: ignore[import-not-found]
        text = "\n\n".join((page.extract_text() or "") for page in PdfReader(io.BytesIO(data)).pages).strip()
        if text:
            return text
    except Exception:  # noqa: BLE001 - missing library or broken file: use the fallback below
        pass
    pieces: list[str] = []
    for m in PDF_STREAM.finditer(data):
        raw = m.group(1)
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            pass
        if b"BT" not in raw or b"ET" not in raw:
            continue
        for bt in re.finditer(rb"BT(.*?)ET", raw, re.S):
            line = "".join(_pdf_literal(s) for s in PDF_STRING.findall(bt.group(1)))
            if line.strip():
                pieces.append(line)
    text = "\n".join(pieces)
    return text.strip() if len(re.findall(r"[가-힣A-Za-z]{2,}", text)) >= 5 else ""


def file_item(name: str, data_b64: str) -> dict[str, Any]:
    """One uploaded file as an item. Raises ValueError with a reason when the file cannot be used at all."""
    name = Path(name.replace("\\", "/")).name or "파일"
    try:
        data = base64.b64decode(data_b64, validate=False)
    except (binascii.Error, ValueError):
        raise ValueError(f"{name}: 파일을 읽지 못함") from None
    if not data:
        raise ValueError(f"{name}: 빈 파일")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(f"{name}: 8MB가 넘는다")
    suffix = Path(name).suffix.lower()
    item: dict[str, Any] = {"kind": "file", "label": name, "url": "", "title": Path(name).stem, "note": "", "raw": None}
    if suffix == ".pdf" or data[:5] == b"%PDF-":
        text = pdf_text(data)
        item.update(body=text or "(PDF 글자를 읽지 못함 — 스캔본이거나 특수 글꼴. 원본 파일은 저장함)", raw=data,
                    note="" if text else "PDF 글자를 읽지 못함")
        return item
    text = decode_text(data)
    if text is None:
        raise ValueError(f"{name}: md·txt·pdf 같은 글 파일만 받는다")
    if suffix in (".html", ".htm"):
        title, text = html_to_text(text)
        item["title"] = title or item["title"]
    item["body"] = text.strip()
    if not item["body"]:
        raise ValueError(f"{name}: 내용이 비어 있다")
    return item


def text_items(text: str, fetch=None) -> list[dict[str, Any]]:
    """Pasted text → items. A paste made only of links becomes one fetched item per link; anything else is one paste."""
    fetch = fetch or fetch_page
    text = text.strip()
    if not text:
        return []
    urls = only_urls(text)
    if not urls:
        return [{"kind": "paste", "label": "붙여넣기", "url": "", "title": first_line(text), "body": text, "note": "", "raw": None}]
    items = []
    for url in dict.fromkeys(urls):
        page = fetch(url)
        body = page["body"].strip()
        items.append({"kind": "url", "label": url, "url": url, "title": page["title"] or url,
                      "body": body or f"(본문을 가져오지 못해 링크만 저장: {url})", "note": page["note"], "raw": None})
    return items
