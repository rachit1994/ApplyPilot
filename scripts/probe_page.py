"""Probe a live page: print URL, title, clickables, fields, login signals."""
import sys, json
from applypilot.config import load_env, ensure_dirs
from applypilot.apply import chrome
from applypilot.apply.direct import unblock, extractor

load_env(); ensure_dirs()
url = sys.argv[1]
steps = sys.argv[2:] if len(sys.argv) > 2 else []
port = chrome.BASE_CDP_PORT
chrome.launch_chrome(0, port=port, headless=False)
from playwright.sync_api import sync_playwright
pw = sync_playwright().start()
b = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=15000)
ctx = b.contexts[0] if b.contexts else b.new_context()
page = ctx.new_page()
page.goto(url, wait_until="domcontentloaded", timeout=40000)
page.wait_for_timeout(2500)

def dump(tag):
    snap = unblock._snapshot(page)
    print(f"\n===== {tag} =====")
    print("URL:", snap["url"])
    print("TITLE:", snap["title"])
    print("has_password:", snap["has_password_field"])
    print("CLICKABLES:", snap["clickables"])
    print("FIELDS:", json.dumps(snap["fields"], ensure_ascii=False))
    print("BODY[:600]:", snap["body_excerpt"][:600])

dump("initial")
for s in steps:
    print(f"\n>>> clicking: {s}")
    ok = unblock._click_text(page, s)
    print("clicked:", ok)
    page.wait_for_timeout(2500)
    dump(f"after click {s!r}")
page.close()
pw.stop()
