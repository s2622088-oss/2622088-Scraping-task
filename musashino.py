from __future__ import annotations

import argparse
import csv
import time
from collections import deque
from urllib.parse import urljoin, urldefrag, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

START_URL = "https://www.musashino-u.ac.jp/"
OUTPUT_CSV = "musashino_sitemap.csv"
USER_AGENT = "MusashinoSitemapCrawler/1.0 (educational use)"

# HTML以外とみられる拡張子はアクセスしない
SKIP_EXTENSIONS = (
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico",
    ".zip", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".mp3", ".mp4", ".mov", ".avi", ".css", ".js", ".xml", ".json",
)


def normalize(url: str) -> str:
    """フラグメント(#...)を除去してURLを正規化する。"""
    url, _ = urldefrag(url)
    return url


def is_same_domain(url: str, base_netloc: str) -> bool:
    return urlparse(url).netloc == base_netloc


def extract_title(soup: BeautifulSoup) -> str:
    """<title>と</title>で挟まれた文字列を返す(なければ空文字)。"""
    if soup.title and soup.title.string:
        return " ".join(soup.title.string.split())
    if soup.title:
        return " ".join(soup.title.get_text().split())
    return ""


def crawl(start_url: str, sleep_sec: float, max_pages: int | None) -> dict[str, str]:
    base_netloc = urlparse(start_url).netloc

    # robots.txt を確認する
    robots = RobotFileParser()
    robots.set_url(urljoin(start_url, "/robots.txt"))
    try:
        robots.read()
    except Exception as e:
        print(f"[warn] robots.txt を読めませんでした: {e}")
        robots = None
    time.sleep(sleep_sec)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    sitemap: dict[str, str] = {}      # key: URL, value: <title>
    visited: set[str] = set()
    queue: deque[str] = deque([normalize(start_url)])

    while queue:
        if max_pages is not None and len(visited) >= max_pages:
            print(f"[info] 上限 {max_pages} ページに達したため終了します")
            break

        url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        if robots and not robots.can_fetch(USER_AGENT, url):
            print(f"[skip] robots.txtで禁止: {url}")
            continue

        try:
            resp = session.get(url, timeout=15)
        except requests.RequestException as e:
            print(f"[error] {url}: {e}")
            time.sleep(sleep_sec)   # エラー時も必ず待つ
            continue

        # アクセス1回ごとに必ず待機して負荷を軽減する
        time.sleep(sleep_sec)

        content_type = resp.headers.get("Content-Type", "")
        if resp.status_code != 200 or "text/html" not in content_type:
            print(f"[skip] status={resp.status_code} type={content_type}: {url}")
            continue

        # 文字化け対策(ヘッダに文字コードがない場合は推定値を使う)
        resp.encoding = resp.encoding if "charset" in content_type.lower() else resp.apparent_encoding
        soup = BeautifulSoup(resp.text, "html.parser")

        sitemap[url] = extract_title(soup)
        print(f"[{len(sitemap)}] {url} | {sitemap[url]}")

        # 同一ドメインのリンクをキューに追加
        for a in soup.find_all("a", href=True):
            link = normalize(urljoin(url, a["href"]))
            parsed = urlparse(link)
            if parsed.scheme not in ("http", "https"):
                continue
            if not is_same_domain(link, base_netloc):
                continue
            if parsed.path.lower().endswith(SKIP_EXTENSIONS):
                continue
            if link not in visited:
                queue.append(link)

    return sitemap


def save_csv(sitemap: dict[str, str], path: str) -> None:
    # utf-8-sig: Excelで開いても日本語が文字化けしない
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["url", "title"])
        for url, title in sitemap.items():
            writer.writerow([url, title])


def main() -> None:
    parser = argparse.ArgumentParser(description="武蔵野大学Webサイトのサイトマップ抽出")
    parser.add_argument("--start", default=START_URL, help="開始URL")
    parser.add_argument("--output", default=OUTPUT_CSV, help="出力CSVファイル名")
    parser.add_argument("--sleep", type=float, default=2.0, help="1アクセスごとの待機秒数(既定: 2秒)")
    parser.add_argument("--max-pages", type=int, default=None, help="最大取得ページ数(テスト用)")
    args = parser.parse_args()

    sitemap = crawl(args.start, args.sleep, args.max_pages)
    save_csv(sitemap, args.output)
    print(f"完了: {len(sitemap)} ページを {args.output} に保存しました")


if __name__ == "__main__":
    main()