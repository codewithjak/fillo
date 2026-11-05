import http.client
import ipaddress
import re
import socket
import ssl
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import SplitResult, urljoin, urlsplit


MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
MAX_REDIRECTS = 4
REQUEST_TIMEOUT_SECONDS = 12
SUPPORTED_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png", ".heic", ".docx", ".txt"}

MIME_SUFFIXES = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/plain": ".txt",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/heic": ".heic",
    "image/heif": ".heic",
}


@dataclass
class FetchedResource:
    body: bytes
    content_type: str
    final_url: str


def _resolve_public_ip(host: str, port: int) -> str:
    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as e:
        raise ValueError("The link host could not be resolved") from e
    addresses = {record[4][0].split("%", 1)[0] for record in records}
    if not addresses:
        raise ValueError("The link host has no network address")

    parsed = [ipaddress.ip_address(address) for address in addresses]
    if any(not address.is_global for address in parsed):
        raise ValueError("Links to private or reserved network addresses are not allowed")
    return sorted(addresses)[0]


def _validate_target(url: str) -> tuple[SplitResult, str, int]:
    parts = urlsplit(url)
    if parts.scheme.lower() not in {"http", "https"}:
        raise ValueError("Only public HTTP and HTTPS links are supported")
    if not parts.hostname or parts.username or parts.password:
        raise ValueError("The link must have a public host and cannot contain credentials")
    try:
        port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
    except ValueError as e:
        raise ValueError("The link has an invalid port") from e
    if port not in {80, 443}:
        raise ValueError("Only standard HTTP and HTTPS ports are supported")
    ip = _resolve_public_ip(parts.hostname, port)
    return parts, ip, port


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, ip: str):
        super().__init__(host, port, timeout=REQUEST_TIMEOUT_SECONDS)
        self._resolved_ip = ip

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._resolved_ip, self.port), timeout=self.timeout
        )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, ip: str):
        super().__init__(host, port, timeout=REQUEST_TIMEOUT_SECONDS, context=ssl.create_default_context())
        self._resolved_ip = ip

    def connect(self) -> None:
        raw = socket.create_connection((self._resolved_ip, self.port), timeout=self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


def fetch_public_url(url: str) -> FetchedResource:
    """Fetch one user-supplied public URL with pinned DNS and bounded redirects/body size."""
    current = url
    for redirect_number in range(MAX_REDIRECTS + 1):
        parts, ip, port = _validate_target(current)
        host = parts.hostname
        if host is None:
            raise ValueError("The link has no host")
        connection: http.client.HTTPConnection
        if parts.scheme.lower() == "https":
            connection = _PinnedHTTPSConnection(host, port, ip)
        else:
            connection = _PinnedHTTPConnection(host, port, ip)

        path = parts.path or "/"
        if parts.query:
            path = f"{path}?{parts.query}"
        try:
            connection.request(
                "GET",
                path,
                headers={
                    "Host": parts.netloc,
                    "User-Agent": "Fillo/0.1 document intake",
                    "Accept": "text/html,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,image/*,text/plain,application/octet-stream;q=0.8,*/*;q=0.1",
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                },
            )
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                response.read(1024)
                if not location:
                    raise ValueError("The link redirected without a destination")
                if redirect_number >= MAX_REDIRECTS:
                    raise ValueError("The link redirected too many times")
                current = urljoin(current, location)
                continue

            if response.status < 200 or response.status >= 300:
                raise ValueError(f"The link returned HTTP {response.status}")
            content_length = response.getheader("Content-Length")
            if content_length:
                try:
                    declared_length = int(content_length)
                except ValueError as e:
                    raise ValueError("The link returned an invalid content length") from e
                if declared_length < 0:
                    raise ValueError("The link returned an invalid content length")
                if declared_length > MAX_DOWNLOAD_BYTES:
                    raise ValueError("The linked file is larger than the 20 MB limit")
            body = response.read(MAX_DOWNLOAD_BYTES + 1)
            if len(body) > MAX_DOWNLOAD_BYTES:
                raise ValueError("The linked file is larger than the 20 MB limit")
            content_type = response.getheader("Content-Type", "application/octet-stream")
            return FetchedResource(
                body=body,
                content_type=content_type.split(";", 1)[0].strip().lower(),
                final_url=current,
            )
        finally:
            connection.close()
    raise ValueError("The link could not be fetched")


class BasicHTMLParser(HTMLParser):
    """Extract visible text and static form metadata without executing page scripts."""

    _IGNORED_TAGS = {"script", "style", "noscript", "svg", "template"}
    _NON_INPUT_TYPES = {"hidden", "submit", "button", "reset", "image"}
    _BLOCK_TAGS = {
        "address", "article", "blockquote", "br", "dd", "div", "dl", "dt",
        "fieldset", "figcaption", "footer", "form", "h1", "h2", "h3", "h4",
        "h5", "h6", "header", "hr", "li", "main", "ol", "p", "section",
        "table", "tbody", "td", "th", "thead", "tr", "ul",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.labels: dict[str, list[str]] = {}
        self.fields: list[dict] = []
        self._in_title = False
        self._ignored_depth = 0
        self._ignored_stack: list[str] = []
        self._label_for: str | None = None
        self._label_parts: list[str] = []
        self._label_field_start: int | None = None
        self._active_select: int | None = None
        self._active_option: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: value or "" for key, value in attrs}
        if tag in self._IGNORED_TAGS:
            self._ignored_depth += 1
            self._ignored_stack.append(tag)
            return
        if self._ignored_depth:
            return
        if tag in self._BLOCK_TAGS:
            self.text_parts.append("\n")
        if tag == "title":
            self._in_title = True
        elif tag == "label":
            self._label_for = attributes.get("for") or None
            self._label_parts = []
            self._label_field_start = len(self.fields)
        elif tag == "input":
            input_type = (attributes.get("type") or "text").lower()
            if input_type not in self._NON_INPUT_TYPES:
                self.fields.append(self._field(attributes, input_type))
        elif tag == "textarea":
            self.fields.append(self._field(attributes, "textarea"))
        elif tag == "select":
            self.fields.append(self._field(attributes, "select"))
            self.fields[-1]["options"] = []
            self._active_select = len(self.fields) - 1
        elif tag == "option" and self._active_select is not None:
            self._active_option = self._active_select

    def handle_endtag(self, tag: str) -> None:
        if self._ignored_depth:
            if self._ignored_stack and self._ignored_stack[-1] == tag:
                self._ignored_stack.pop()
                self._ignored_depth -= 1
            return
        if tag in self._BLOCK_TAGS:
            self.text_parts.append("\n")
        if tag == "title":
            self._in_title = False
        elif tag == "label":
            label = " ".join(" ".join(self._label_parts).split())
            if self._label_for and label:
                self.labels[self._label_for] = [label]
            elif (label and self._label_field_start is not None
                  and len(self.fields) > self._label_field_start):
                self.fields[self._label_field_start]["label"] = label
            self._label_for = None
            self._label_parts = []
            self._label_field_start = None
        elif tag == "select":
            self._active_select = None
            self._active_option = None
        elif tag == "option":
            self._active_option = None

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        self.text_parts.append(text)
        if self._label_for is not None:
            self._label_parts.append(text)
        if self._active_option is not None:
            options = self.fields[self._active_option]["options"]
            if len(options) < 30:
                options.append(text)

    def _field(self, attrs: dict[str, str], field_type: str) -> dict:
        return {
            "name": attrs.get("name") or None,
            "id": attrs.get("id") or None,
            "label": attrs.get("aria-label") or None,
            "type": field_type,
            "required": "required" in attrs,
            "placeholder": attrs.get("placeholder") or None,
            "options": [],
            "constraints": {
                key: attrs[key]
                for key in ("min", "max", "minlength", "maxlength", "pattern", "step",
                            "multiple", "accept", "autocomplete")
                if key in attrs
            },
        }

    def result(self) -> dict:
        for field in self.fields:
            if not field["label"] and field["id"]:
                labels = self.labels.get(field["id"])
                if labels:
                    field["label"] = labels[0]
        title = " ".join(" ".join(self.title_parts).split())[:300]
        pieces: list[str] = []
        for part in self.text_parts:
            if part == "\n":
                pieces.append("\n")
                continue
            value = " ".join(part.split())
            if not value:
                continue
            if pieces and pieces[-1] not in {" ", "\n"}:
                pieces.append(" ")
            pieces.append(value)
        text = re.sub(r" *\n *", "\n", "".join(pieces))
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return {"title": title or None, "text": text[:16000], "fields": self.fields[:100]}
