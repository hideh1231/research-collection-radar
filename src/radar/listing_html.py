from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

LISTING_PAGES = {
    "apa-cfp": {
        "url": "https://www.apa.org/pubs/journals/resources/calls-for-papers",
        "out_name": "apa-cfp.html",
    },
    "sciencedirect-cfp": {
        "url": "https://www.sciencedirect.com/browse/calls-for-papers",
        "out_name": "sciencedirect-cfp.html",
    },
}

COOKIE_BUTTONS = (
    "#onetrust-accept-btn-handler",
    "#truste-consent-button",
    "button#onetrust-accept-btn-handler",
    'button:has-text("Accept all")',
    'button:has-text("Accept All")',
    'button:has-text("Accept")',
    'button:has-text("I agree")',
    'button:has-text("Agree")',
)


@dataclass(frozen=True)
class ListingProbe:
    ok: bool
    reason: str


def inspect_listing_html(key: str, html: str) -> ListingProbe:
    text = html or ""
    lowered = text.lower()
    if key == "apa-cfp":
        if "pardon our interruption" in lowered:
            return ListingProbe(False, "captcha or interruption page")
        if len(text) < 5000 and "incapsula" in lowered:
            return ListingProbe(False, "incapsula stub")
        if text.count("bodyleft") >= 1 and "/pubs/journals/" in lowered:
            return ListingProbe(True, "apa journal modules")
        return ListingProbe(False, "apa listing markers missing")
    if key == "sciencedirect-cfp":
        if "problem providing the content you requested" in lowered:
            return ListingProbe(False, "sciencedirect block page")
        if "/special-issue/" in lowered and ("js-publication" in lowered or "class=\"publication" in lowered or "publication js-publication" in lowered):
            return ListingProbe(True, "sciencedirect publication cards")
        return ListingProbe(False, "sciencedirect listing markers missing")
    return ListingProbe(False, f"unknown listing key {key}")


def _accept_cookies(page: Any) -> None:
    for selector in COOKIE_BUTTONS:
        try:
            button = page.locator(selector).first
            if button.count() == 0:
                continue
            button.click(timeout=2500)
            page.wait_for_timeout(500)
            return
        except Exception:
            continue


def _launch_browser(playwright: Any, *, headless: bool) -> Any:
    errors: list[str] = []
    for channel in ("chrome", None):
        try:
            kwargs: dict[str, Any] = {"headless": headless}
            if channel:
                kwargs["channel"] = channel
            return playwright.chromium.launch(**kwargs)
        except Exception as exc:
            errors.append(f"{channel or 'chromium'}: {exc}")
    raise RuntimeError("could not launch Chrome or Chromium: " + "; ".join(errors))


def render_listing_pages(
    out_dir: Path,
    keys: list[str] | None = None,
    *,
    headless: bool = False,
    timeout_ms: int = 90_000,
) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("playwright is not installed; pip install -e '.[listing]'") from exc

    selected = keys or list(LISTING_PAGES)
    out_dir.mkdir(parents=True, exist_ok=True)
    status: dict[str, Any] = {"ok": True, "pages": {}}

    with sync_playwright() as playwright:
        browser = _launch_browser(playwright, headless=headless)
        context = browser.new_context()
        page = context.new_page()
        for key in selected:
            spec = LISTING_PAGES[key]
            dest = out_dir / spec["out_name"]
            entry: dict[str, Any] = {"url": spec["url"], "path": str(dest), "ok": False}
            try:
                page.goto(spec["url"], wait_until="domcontentloaded", timeout=timeout_ms)
                _accept_cookies(page)
                html = ""
                probe = ListingProbe(False, "not loaded")
                for _ in range(int(timeout_ms / 2000)):
                    html = page.content()
                    probe = inspect_listing_html(key, html)
                    if probe.ok:
                        break
                    if "pardon our interruption" in html.lower():
                        break
                    page.wait_for_timeout(2000)
                    _accept_cookies(page)
                dest.write_text(html, encoding="utf-8")
                entry.update({"ok": probe.ok, "reason": probe.reason, "bytes": len(html)})
            except Exception as exc:
                entry.update({"ok": False, "reason": str(exc)})
            status["pages"][key] = entry
            if not entry["ok"]:
                status["ok"] = False
        context.close()
        browser.close()

    (out_dir / "status.json").write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    return status


def ingest_args_from_status(status: dict[str, Any]) -> list[str]:
    args: list[str] = []
    for key, entry in status.get("pages", {}).items():
        if entry.get("ok") and entry.get("path"):
            args.extend(["--ingest-html", f"{key}={entry['path']}"])
    return args
