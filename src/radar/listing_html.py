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
    "aps-cfp": {
        "url": "https://journals.physiology.org/calls",
        "out_name": "aps-cfp.html",
    },
    "science-robotics-cfp": {
        "url": "https://www.science.org/content/page/calls-papers",
        "out_name": "science-robotics-cfp.html",
    },
    "tandf-cfp": {
        "url": "https://authorservices.taylorandfrancis.com/call-for-papers/",
        "out_name": "tandf-cfp.html",
        "checkboxes": ("Psychology", "Neuroscience", "Behavioral Sciences", "Computer Science"),
        "click": ('button:has-text("Show call for papers")', 'button:has-text("Load")'),
    },
    "sage-cfp": {
        "url": "https://journals.sagepub.com/special-issue-calls-for-papers",
        "out_name": "sage-cfp.html",
    },
    "pnas-cfp": {
        "url": "https://www.pnas.org/author-center/call-for-papers",
        "out_name": "pnas-cfp.html",
    },
    "pnas-nexus-cfp": {
        "url": "https://academic.oup.com/pnasnexus",
        "out_name": "pnas-nexus-cfp.html",
        "urls": (
            "https://academic.oup.com/pnasnexus",
            "https://academic.oup.com/pnasnexus/pages/call-for-papers-in-machine-learning-and-geosciences",
        ),
    },
    "josa-a-features": {
        "url": "https://opg.optica.org/josaa/journal/josaa/feature.cfm",
        "out_name": "josa-a-features.html",
    },
    "wiley-bjp": {
        "url": "https://bpspsychub.onlinelibrary.wiley.com/hub/journal/20448295/homepage/call-for-papers",
        "out_name": "wiley-bjp.html",
    },
    "wiley-ethology": {
        "url": "https://onlinelibrary.wiley.com/page/journal/14390310/homepage/call-for-papers",
        "out_name": "wiley-ethology.html",
    },
    "wiley-developmental-science": {
        "url": "https://onlinelibrary.wiley.com/page/journal/14677687/homepage/call-for-papers",
        "out_name": "wiley-developmental-science.html",
    },
    "wiley-ejn": {
        "url": "https://onlinelibrary.wiley.com/page/journal/14609568/homepage/call-for-papers",
        "out_name": "wiley-ejn.html",
    },
    "wiley-jpr": {
        "url": "https://onlinelibrary.wiley.com/page/journal/14685884/homepage/call-for-papers",
        "out_name": "wiley-jpr.html",
    },
    "wiley-hippocampus": {
        "url": "https://onlinelibrary.wiley.com/page/journal/10981063/homepage/call-for-papers",
        "out_name": "wiley-hippocampus.html",
    },
    "wiley-hbm": {
        "url": "https://onlinelibrary.wiley.com/page/journal/10970193/homepage/call-for-papers",
        "out_name": "wiley-hbm.html",
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

WALL_SNIPPETS = (
    "pardon our interruption",
    "cf-browser-verification",
    "performing security verification",
    "captcha page",
    "access denied",
)


@dataclass(frozen=True)
class ListingProbe:
    ok: bool
    reason: str


def inspect_listing_html(key: str, html: str) -> ListingProbe:
    text = html or ""
    lowered = text.lower()
    if any(snippet in lowered for snippet in WALL_SNIPPETS) and len(text) < 20_000:
        return ListingProbe(False, "captcha or interruption page")
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
        if "/special-issue/" in lowered and ("js-publication" in lowered or 'class="publication' in lowered or "publication js-publication" in lowered):
            return ListingProbe(True, "sciencedirect publication cards")
        return ListingProbe(False, "sciencedirect listing markers missing")
    if key == "aps-cfp":
        if "journal of neurophysiology" in lowered and ("deadline" in lowered or "call for papers" in lowered):
            return ListingProbe(True, "aps journal sections")
        return ListingProbe(False, "aps listing markers missing")
    if key == "science-robotics-cfp":
        if "special issue" in lowered and "deadline" in lowered:
            return ListingProbe(True, "science robotics special issues")
        return ListingProbe(False, "science robotics listing markers missing")
    if key == "tandf-cfp":
        if "result" in lowered and ("deadline" in lowered or "call for papers" in lowered) and "0 result" not in lowered:
            return ListingProbe(True, "tandf call cards")
        if "search for current calls for papers" in lowered:
            return ListingProbe(False, "tandf search form without results")
        return ListingProbe(False, "tandf listing markers missing")
    if key == "sage-cfp":
        if "submission deadline" in lowered and ("psychology" in lowered or "special issue" in lowered):
            return ListingProbe(True, "sage special issue hub")
        return ListingProbe(False, "sage listing markers missing")
    if key == "pnas-cfp":
        if "call for papers" in lowered and ("pnas" in lowered or "national academy" in lowered):
            return ListingProbe(True, "pnas call for papers")
        return ListingProbe(False, "pnas listing markers missing")
    if key == "pnas-nexus-cfp":
        if "pnas nexus" in lowered and ("call for papers" in lowered or "special" in lowered):
            return ListingProbe(True, "pnas nexus page")
        return ListingProbe(False, "pnas nexus listing markers missing")
    if key == "josa-a-features":
        if "feature" in lowered and ("deadline" in lowered or "josa" in lowered):
            return ListingProbe(True, "josa a feature issues")
        return ListingProbe(False, "josa listing markers missing")
    if key.startswith("wiley-"):
        if "call for papers" in lowered or "special issue" in lowered:
            return ListingProbe(True, "wiley call for papers")
        return ListingProbe(False, "wiley listing markers missing")
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


def _prepare_listing(page: Any, spec: dict[str, Any]) -> None:
    for label in spec.get("checkboxes") or ():
        try:
            box = page.get_by_label(label, exact=False).first
            if box.count():
                box.check(timeout=2500)
                page.wait_for_timeout(200)
        except Exception:
            continue
    for selector in spec.get("click") or ():
        try:
            button = page.locator(selector).first
            if button.count() == 0:
                continue
            button.click(timeout=4000)
            page.wait_for_timeout(1500)
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


def _render_one_url(page: Any, key: str, url: str, spec: dict[str, Any], timeout_ms: int) -> tuple[str, ListingProbe]:
    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    _accept_cookies(page)
    _prepare_listing(page, spec)
    html = ""
    probe = ListingProbe(False, "not loaded")
    for _ in range(int(timeout_ms / 2000)):
        html = page.content()
        probe = inspect_listing_html(key, html)
        if probe.ok:
            break
        if any(snippet in html.lower() for snippet in ("pardon our interruption", "performing security verification")):
            break
        page.wait_for_timeout(2000)
        _accept_cookies(page)
        _prepare_listing(page, spec)
    return html, probe


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
                html, probe = _render_one_url(page, key, spec["url"], spec, timeout_ms)
                extras = []
                for extra_url in spec.get("urls") or ():
                    if extra_url == spec["url"]:
                        continue
                    extra_html, extra_probe = _render_one_url(page, key, extra_url, spec, timeout_ms)
                    extras.append(extra_html)
                    if extra_probe.ok:
                        probe = extra_probe
                if extras:
                    html = html + "\n".join(extras)
                    probe = inspect_listing_html(key, html) if not probe.ok else probe
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
