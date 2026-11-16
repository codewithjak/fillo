import asyncio
import html
import http.client
import ipaddress
import re
import socket
import ssl
from dataclasses import dataclass
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


@dataclass
class PageScreenshot:
    page: int
    scroll_y: int
    png: bytes


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


def fetch_public_url(
    url: str,
    *,
    max_download_bytes: int = MAX_DOWNLOAD_BYTES,
) -> FetchedResource:
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
                if declared_length > max_download_bytes:
                    raise ValueError("The linked resource exceeds the download size limit")
            body = response.read(max_download_bytes + 1)
            if len(body) > max_download_bytes:
                raise ValueError("The linked resource exceeds the download size limit")
            content_type = response.getheader("Content-Type", "application/octet-stream")
            return FetchedResource(
                body=body,
                content_type=content_type.split(";", 1)[0].strip().lower(),
                final_url=current,
            )
        finally:
            connection.close()
    raise ValueError("The link could not be fetched")


MAX_WEB_PAGE_SCREENSHOTS = 8
MAX_WEB_PAGE_REQUESTS = 60
MAX_WEB_PAGE_BYTES = 40 * 1024 * 1024
MAX_WEB_PAGE_FORM_CONTROLS = 200
MAX_WEB_PAGE_FORM_OPTIONS = 100

_FORM_CONTROL_INSPECTION_SCRIPT = r"""limits => {
    const normalize = value => (value || "").replace(/\s+/g, " ").trim();
    const visible = element => {
        const style = window.getComputedStyle(element);
        return Boolean(element.getClientRects().length) &&
            style.display !== "none" && style.visibility !== "hidden" &&
            style.visibility !== "collapse";
    };
    const controls = Array.from(document.querySelectorAll(
        'input, select, textarea, [contenteditable="true"], [role="textbox"], '
        '[role="combobox"], [role="checkbox"], [role="radio"], '
        '[role="listbox"], [role="spinbutton"]'
    )).filter(element => {
        if (!visible(element)) return false;
        if (element.tagName === "INPUT" && element.type.toLowerCase() === "hidden") return false;
        if (element.tagName === "INPUT" &&
            ["button", "submit", "reset", "image"].includes(element.type.toLowerCase())) return false;
        return true;
    });
    const accessibleLabel = element => {
        const labelledBy = normalize((element.getAttribute("aria-labelledby") || "")
            .split(/\s+/)
            .map(id => document.getElementById(id)?.innerText || "")
            .join(" "));
        if (labelledBy) return labelledBy;
        const ariaLabel = normalize(element.getAttribute("aria-label"));
        if (ariaLabel) return ariaLabel;
        return normalize(Array.from(element.labels || [])
            .map(label => label.innerText || label.textContent || "")
            .join(" ")) || null;
    };
    const described = controls.map((element, index) => {
        const tag = element.tagName.toLowerCase();
        const type = tag === "input"
            ? (element.type || "text").toLowerCase()
            : tag === "select"
                ? (element.multiple ? "select-multiple" : "select-one")
                : tag === "textarea"
                    ? "textarea"
                    : element.getAttribute("role") ||
                        (element.isContentEditable ? "contenteditable" : "custom");
        const role = element.getAttribute("role") || null;
        const label = (accessibleLabel(element) || "").slice(0, 300) || null;
        const id = (element.id || "").slice(0, 200) || null;
        const name = (element.getAttribute("name") || "").slice(0, 200) || null;
        const testId = (element.getAttribute("data-testid") || "").slice(0, 200) || null;
        const optionValue = ["radio", "checkbox"].includes(type)
            ? element.getAttribute("value")
            : null;
        const formIndex = element.form
            ? Array.from(document.forms).indexOf(element.form)
            : -1;
        const placeholder = element.getAttribute("placeholder") || "";
        const identity = id
            ? "id:" + id
            : name
                ? "name:" + name + "|option:" + (optionValue || "") + "|label:" + (label || "")
                : "label:" + (label || "") + "|placeholder:" + placeholder + "|index:" + index;
        const key = [formIndex, tag, type, identity].join("|");
        const constraints = {};
        for (const attribute of ["min", "max", "step", "minlength", "maxlength",
            "pattern", "accept", "inputmode", "autocomplete", "aria-valuemin",
            "aria-valuemax"]) {
            if (element.hasAttribute(attribute)) {
                constraints[attribute] = element.getAttribute(attribute).slice(0, 500);
            }
        }
        const options = tag === "select"
            ? Array.from(element.options).slice(0, limits.max_options).map(option => ({
                label: normalize(option.label || option.textContent).slice(0, 200),
                value: option.value.slice(0, 200),
                disabled: option.disabled || Boolean(option.parentElement?.disabled),
            }))
            : ["combobox", "listbox"].includes(role)
                ? Array.from(element.querySelectorAll('[role="option"]')).slice(0, limits.max_options).map(option => ({
                    label: normalize(option.innerText || option.textContent).slice(0, 200),
                    value: (option.getAttribute("data-value") || option.getAttribute("value") || "").slice(0, 200),
                    disabled: option.getAttribute("aria-disabled") === "true",
                }))
            : ["radio", "checkbox"].includes(type)
                ? [{label: label || "", value: (element.getAttribute("value") || "on").slice(0, 200),
                    disabled: element.matches(":disabled")}]
                : [];
        const options_truncated = tag === "select"
            ? element.options.length > limits.max_options
            : ["combobox", "listbox"].includes(role)
                ? element.querySelectorAll('[role="option"]').length > limits.max_options
                : false;
        return {
            _key: key,
            label,
            placeholder: normalize(element.getAttribute("placeholder")).slice(0, 300) || null,
            tag,
            type,
            role,
            name,
            group_name: ["radio", "checkbox"].includes(type) ? name : null,
            required: Boolean(element.required) || element.getAttribute("aria-required") === "true",
            disabled: element.matches(":disabled") || element.getAttribute("aria-disabled") === "true",
            read_only: Boolean(element.readOnly) || element.getAttribute("aria-readonly") === "true",
            fillable: !element.matches(":disabled") && element.getAttribute("aria-disabled") !== "true" &&
                !element.readOnly && element.getAttribute("aria-readonly") !== "true",
            options,
            options_truncated,
            constraints,
            _id: id,
            _test_id: testId,
            _index: index,
        };
    });
    const labelCounts = new Map();
    for (const field of described) {
        if (field.label) labelCounts.set(field.label, (labelCounts.get(field.label) || 0) + 1);
    }
    const idCounts = new Map();
    for (const element of document.querySelectorAll("[id]")) {
        idCounts.set(element.id, (idCounts.get(element.id) || 0) + 1);
    }
    const testIdCounts = new Map();
    for (const element of document.querySelectorAll("[data-testid]")) {
        const value = element.getAttribute("data-testid");
        testIdCounts.set(value, (testIdCounts.get(value) || 0) + 1);
    }
    const nameCounts = new Map();
    for (const element of document.querySelectorAll("[name]")) {
        const value = element.getAttribute("name");
        nameCounts.set(value, (nameCounts.get(value) || 0) + 1);
    }
    const fields = described.slice(0, limits.max_controls).map(field => {
        const locators = [];
        if (field.label) locators.push({
            strategy: "label", value: field.label,
            unique: labelCounts.get(field.label) === 1, control_type: field.type,
        });
        if (field._test_id) locators.push({
            strategy: "test_id", value: field._test_id,
            unique: testIdCounts.get(field._test_id) === 1, control_type: field.type,
        });
        if (field._id) locators.push({
            strategy: "id", value: field._id,
            unique: idCounts.get(field._id) === 1, control_type: field.type,
        });
        if (field.name) {
            locators.push({
                strategy: "name", value: field.name,
                unique: nameCounts.get(field.name) === 1, control_type: field.type,
            });
        }
        const {_key, _id, _test_id, _index, ...publicField} = field;
        return {...publicField, _inspection_key: _key, locators};
    });
    return {
        fields,
        truncated: described.length > limits.max_controls ||
            fields.some(field => field.options_truncated),
    };
}"""


def _add_base_url(body: bytes, base_url: str) -> bytes:
    base_tag = f'<base href="{html.escape(base_url, quote=True)}">'.encode("utf-8")
    head = re.search(rb"<head\b[^>]*>", body, re.IGNORECASE)
    if head:
        return body[:head.end()] + base_tag + body[head.end():]
    return b"<head>" + base_tag + b"</head>" + body


def looks_like_html(content_type: str, body: bytes) -> bool:
    if content_type in {"text/html", "application/xhtml+xml"}:
        return True
    sample = body[:4096].decode("utf-8", errors="ignore").lstrip("\ufeff\t\r\n ")
    while sample.startswith("<!--"):
        comment_end = sample.find("-->")
        if comment_end < 0:
            return False
        sample = sample[comment_end + 3 :].lstrip("\t\r\n ")
    return sample[:32].lower().startswith(("<!doctype html", "<html", "<head", "<body"))


async def capture_public_page(
    fetched: FetchedResource,
) -> tuple[str, list[PageScreenshot], bool, dict]:
    """Render a public HTML page, capture viewports, and inspect visible controls."""
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise RuntimeError("Playwright is required to render web pages") from e

    request_state = {
        "count": 1,
        "bytes": len(fetched.body),
        "initial_pending": True,
    }
    fetch_semaphore = asyncio.Semaphore(4)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                viewport={"width": 1365, "height": 900},
                device_scale_factor=1,
                service_workers="block",
            )
            async def fulfill_request(route) -> None:
                request = route.request
                if urlsplit(request.url).scheme.lower() not in {"http", "https"}:
                    await route.abort("blockedbyclient")
                    return
                if request_state["count"] >= MAX_WEB_PAGE_REQUESTS:
                    await route.abort("blockedbyclient")
                    return
                request_state["count"] += 1
                origin = request.headers.get("origin")
                cors_headers = {
                    "access-control-allow-origin": origin or "*",
                    "access-control-allow-methods": "GET, HEAD, OPTIONS",
                    "access-control-allow-headers": request.headers.get(
                        "access-control-request-headers", "*"
                    ),
                }
                if request.method == "OPTIONS":
                    await route.fulfill(status=204, headers=cors_headers)
                    return
                if request.method not in {"GET", "HEAD"}:
                    await route.abort("blockedbyclient")
                    return

                initial_url = fetched.final_url.split("#", 1)[0]
                request_url = request.url.split("#", 1)[0]
                if (
                    request_state["initial_pending"]
                    and request.is_navigation_request()
                    and request_url == initial_url
                ):
                    request_state["initial_pending"] = False
                    resource = fetched
                    body = _add_base_url(resource.body, fetched.final_url)
                    content_type = "text/html; charset=utf-8"
                else:
                    try:
                        async with fetch_semaphore:
                            resource = await asyncio.to_thread(
                                fetch_public_url,
                                request.url,
                                max_download_bytes=8 * 1024 * 1024,
                            )
                    except Exception:
                        await route.abort("blockedbyclient")
                        return
                    request_state["bytes"] += len(resource.body)
                    if request_state["bytes"] > MAX_WEB_PAGE_BYTES:
                        await route.abort("blockedbyclient")
                        return
                    body = resource.body
                    content_type = resource.content_type

                headers = {"content-type": content_type, **cors_headers}
                await route.fulfill(
                    status=200,
                    body=b"" if request.method == "HEAD" else body,
                    headers=headers,
                )

            async def block_websocket(websocket) -> None:
                await websocket.close(
                    code=1008,
                    reason="WebSocket access is disabled during page inspection",
                )

            await context.route("**/*", fulfill_request)
            await context.route_web_socket("**/*", block_websocket)
            page = await context.new_page()
            await page.goto(fetched.final_url, wait_until="domcontentloaded", timeout=20_000)
            await page.wait_for_timeout(2000)
            title = await page.title()

            screenshots: list[PageScreenshot] = []
            inspected_fields: dict[str, dict] = {}
            controls_truncated = False
            inspection_failed = False
            reached_bottom = False
            for screenshot_number in range(1, MAX_WEB_PAGE_SCREENSHOTS + 1):
                try:
                    snapshot = await page.evaluate(
                        _FORM_CONTROL_INSPECTION_SCRIPT,
                        {
                            "max_controls": MAX_WEB_PAGE_FORM_CONTROLS,
                            "max_options": MAX_WEB_PAGE_FORM_OPTIONS,
                        },
                    )
                    controls_truncated = controls_truncated or snapshot["truncated"]
                    for field in snapshot["fields"]:
                        inspection_key = field.pop("_inspection_key")
                        if inspection_key in inspected_fields:
                            inspected_fields[inspection_key] = field
                        elif len(inspected_fields) < MAX_WEB_PAGE_FORM_CONTROLS:
                            inspected_fields[inspection_key] = field
                        else:
                            controls_truncated = True
                except Exception:
                    inspection_failed = True

                position = await page.evaluate(
                    """() => ({
                        y: Math.round(window.scrollY),
                        height: window.innerHeight,
                        total: Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)
                    })"""
                )
                screenshots.append(PageScreenshot(
                    page=screenshot_number,
                    scroll_y=position["y"],
                    png=await page.screenshot(type="png", full_page=False, animations="disabled"),
                ))
                if position["y"] + position["height"] >= position["total"] - 2:
                    reached_bottom = True
                    break
                next_y = min(
                    position["y"] + max(300, position["height"] - 120),
                    position["total"] - position["height"],
                )
                if next_y <= position["y"]:
                    break
                await page.evaluate("y => window.scrollTo(0, y)", next_y)
                await page.wait_for_timeout(500)

            embedded_frame_count = max(0, len(page.frames) - 1)
            notes = [
                "Only visible controls in the rendered main document are included; current field values are omitted."
            ]
            unlabeled_count = sum(
                1 for field in inspected_fields.values() if not field.get("label")
            )
            if unlabeled_count:
                notes.append(
                    f"{unlabeled_count} inspected control(s) had no accessible label; "
                    "use screenshot OCR to interpret them."
                )
            if not reached_bottom:
                notes.append(
                    "Page capture stopped before reaching the bottom; more controls may exist below."
                )
            if embedded_frame_count:
                notes.append("Controls inside embedded frames were not inspected.")
            if controls_truncated:
                notes.append(
                    f"Inspection was limited to {MAX_WEB_PAGE_FORM_CONTROLS} controls "
                    f"and {MAX_WEB_PAGE_FORM_OPTIONS} options per control."
                )
            if inspection_failed:
                notes.append("DOM inspection failed for one or more page viewports; OCR results remain available.")
            fields = [
                {"field_id": f"web-field-{index}", **field}
                for index, field in enumerate(inspected_fields.values(), start=1)
            ]
            inspection_partial = (
                embedded_frame_count > 0
                or controls_truncated
                or inspection_failed
                or not reached_bottom
            )
            form_inspection = {
                "status": (
                    "partial"
                    if inspection_partial
                    else "completed" if fields else "no_controls"
                ),
                "fields": fields,
                "truncated": controls_truncated or not reached_bottom,
                "embedded_frame_count": embedded_frame_count,
                "notes": notes,
            }
            return title, screenshots, not reached_bottom, form_inspection
        finally:
            await browser.close()
