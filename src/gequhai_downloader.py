#!/usr/bin/env python3
"""Batch downloader for tracks exposed by gequhai.com's normal web player.

Input CSV columns: song,artist
Use only for audio you are entitled to download.
"""

import argparse
import asyncio
import csv
import html
import re
from pathlib import Path
from urllib.parse import quote, urlparse

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

BASE = "https://www.gequhai.com"


def safe_name(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    return value[:180] or "track"


def norm(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


async def choose_result(page, song: str, artist: str):
    # Song-only lookup has the broadest hit rate; artist is used for ranking below.
    keyword = song.strip()
    query = quote(keyword, safe="")
    search_url = f"{BASE}/s/{query}"
    raw_response = await page.context.request.get(search_url, timeout=45_000)
    raw_html = await raw_response.text()
    if "/play/" not in raw_html:
        await page.goto(search_url, wait_until="domcontentloaded", timeout=45_000)
        result = await page.evaluate("""async ({keyword}) => {
          const body = new URLSearchParams({keyword, page: '1'});
          const r = await fetch('/api/s', {method:'POST', headers:{
            'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8',
            'X-Requested-With':'XMLHttpRequest'}, body});
          return await r.json();
        }""", {"keyword": keyword})
        if result.get("code") == 2:
            for _ in range(20):
                await asyncio.sleep(3)
                mapped = await page.evaluate("""async ({keyword}) => {
                  const body = new URLSearchParams({keyword});
                  const r = await fetch('/api/query-map', {method:'POST', headers:{
                    'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8',
                    'X-Requested-With':'XMLHttpRequest'}, body});
                  return await r.json();
                }""", {"keyword": keyword})
                if mapped.get("code") == 1:
                    break
        raw_response = await page.context.request.get(search_url, timeout=45_000)
        raw_html = await raw_response.text()

    candidates = []
    pattern = re.compile(
        r'<a\s+href="(?P<href>/play/\d+)"[^>]*>(?P<title>.*?)</a>\s*</td>\s*'
        r'<td[^>]*>(?P<artist>.*?)</td>', re.I | re.S)
    strip_tags = lambda s: re.sub(r"<[^>]+>", "", html.unescape(s)).strip()
    for match in pattern.finditer(raw_html):
        title = strip_tags(match.group("title"))
        singer = strip_tags(match.group("artist"))
        href = match.group("href")
        score = 0
        if norm(title) == norm(song): score += 6
        elif norm(song) in norm(title): score += 3
        if norm(singer) == norm(artist): score += 6
        elif norm(artist) and norm(artist) in norm(singer): score += 3
        candidates.append((score, title, singer, href))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0]


async def fetch_track(context, page, song, artist, out_dir: Path, dry_run=False, href_hint=None):
    # A href saved in a previous report skips the expensive search step.
    hit = (12, song, artist, href_hint) if href_hint else await choose_result(page, song, artist)
    if not hit:
        return "not_found", "no search result"
    score, title, singer, href = hit
    if score < 6:
        return "ambiguous", f"best match: {title} - {singer}"
    if dry_run:
        return "matched", f"{title} - {singer} ({href})"

    stem = f"{safe_name(title)} - {safe_name(singer)}"
    for ext in (".mp3", ".flac", ".m4a", ".wav", ".ogg"):
        existing = out_dir / (stem + ext)
        if existing.exists() and existing.stat().st_size > 0:
            return "skipped_existing", str(existing.resolve())

    try:
        play_url = BASE + href
        play_response = await context.request.get(play_url, timeout=45_000)
        play_html = await play_response.text()
        id_match = re.search(r"window\.play_id\s*=\s*['\"]([^'\"]+)", play_html)
        type_match = re.search(r"window\.mp3_type\s*=\s*(\d+)", play_html)
        if not id_match:
            return "api_error", "play_id missing from play page"
        for attempt in range(1, 5):
            api_response = await context.request.post(
                BASE + "/api/music",
                form={"id": id_match.group(1), "type": type_match.group(1) if type_match else "0"},
                headers={
                    "Referer": play_url,
                    "X-Requested-With": "Http",
                    "X-Custom-Header": "Key",
                },
                timeout=45_000,
            )
            payload = await api_response.json()
            message = payload.get("msg", "")
            if payload.get("code") == 200:
                break
            wait_match = re.search(r"(\d+)\s*秒", message)
            if "请求过于频繁" in message and attempt < 4:
                wait_seconds = (int(wait_match.group(1)) if wait_match else 20) + 2
                print(f"  rate_limited: waiting {wait_seconds}s, retry {attempt}/3")
                await asyncio.sleep(wait_seconds)
                continue
            break
    except (PlaywrightTimeout, ValueError) as exc:
        return "api_error", str(exc)

    if payload.get("code") != 200 or not payload.get("data", {}).get("url"):
        return "api_error", payload.get("msg", repr(payload))

    media_url = payload["data"]["url"]
    suffix = Path(urlparse(media_url).path).suffix.lower()
    if suffix not in {".mp3", ".flac", ".m4a", ".wav", ".ogg"}:
        suffix = ".mp3"
    destination = out_dir / f"{safe_name(title)} - {safe_name(singer)}{suffix}"
    # The media CDN rejects Playwright's APIRequestContext fingerprint with 403,
    # while the system curl client follows the same normal URL successfully.
    process = await asyncio.create_subprocess_exec(
        "curl.exe", "-fL", "--http1.1", "--retry", "2",
        "--connect-timeout", "20", "--max-time", "180",
        "-A", "Mozilla/5.0",
        "-o", str(destination), media_url,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        destination.unlink(missing_ok=True)
        message = stderr.decode("utf-8", errors="replace").strip().splitlines()
        return "download_error", message[-1] if message else f"curl exit {process.returncode}"
    return "downloaded", str(destination.resolve())


async def main_async(args):
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(args.input, "r", encoding="utf-8-sig", newline="") as f:
        tracks = list(csv.DictReader(f))
    if not tracks or not {"song", "artist"}.issubset(tracks[0]):
        raise SystemExit("CSV header must be: song,artist")

    async with async_playwright() as p:
        # Use the locally installed Edge by default, avoiding a separate
        # `playwright install chromium` download on Windows.
        browser = await p.chromium.launch(
            channel=args.browser_channel,
            headless=not args.show_browser,
        )
        context = await browser.new_context(accept_downloads=False)
        page = await context.new_page()
        report = []
        for index, item in enumerate(tracks, 1):
            song, artist = item["song"].strip(), item["artist"].strip()
            href_hint = (item.get("href") or "").strip()
            if not href_hint:
                match = re.search(r"\(/play/(\d+)\)", item.get("detail", ""))
                href_hint = f"/play/{match.group(1)}" if match else None
            print(f"[{index}/{len(tracks)}] {song} - {artist}")
            if args.reuse_only and not href_hint:
                status, detail = "skipped", "report has no saved /play/ link"
                print(f"  {status}: {detail}")
                report.append({"song": song, "artist": artist, "href": "", "status": status, "detail": detail})
                continue
            try:
                status, detail = await fetch_track(
                    context, page, song, artist, out_dir, args.dry_run, href_hint
                )
            except Exception as exc:
                status, detail = "error", f"{type(exc).__name__}: {exc}"
            print(f"  {status}: {detail}")
            report.append({
                "song": song, "artist": artist, "href": href_hint or "",
                "status": status, "detail": detail,
            })
            await asyncio.sleep(args.delay)
        await browser.close()

    report_path = out_dir / "report.csv"
    with report_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["song", "artist", "href", "status", "detail"])
        writer.writeheader(); writer.writerows(report)
    print(f"Report: {report_path.resolve()}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="CSV file with song,artist columns")
    parser.add_argument("-o", "--output", default="downloads")
    parser.add_argument("--delay", type=float, default=3.0, help="seconds between tracks")
    parser.add_argument("--dry-run", action="store_true", help="search and match only")
    parser.add_argument("--show-browser", action="store_true")
    parser.add_argument(
        "--reuse-only", action="store_true",
        help="use only /play/ links already saved in a report; skip rows without one",
    )
    parser.add_argument(
        "--browser-channel", default="msedge",
        choices=["msedge", "chrome", "chromium"],
        help="installed browser channel (default: msedge)",
    )
    asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    main()
