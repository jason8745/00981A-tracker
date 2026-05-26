# scraper.py
import csv
import json
import re
import shutil
import sys
import time
from datetime import date
from pathlib import Path

def compute_diff(prev: dict | None, curr: dict) -> dict:
    """Compare two daily snapshots. Returns categorized changes."""
    result = {"added": [], "removed": [], "increased": [], "decreased": []}
    if prev is None:
        return result

    prev_map = {h["code"]: h for h in prev["holdings"]}
    curr_map = {h["code"]: h for h in curr["holdings"]}

    for code, h in curr_map.items():
        if code not in prev_map:
            result["added"].append({
                "code": code,
                "name": h["name"],
                "shares": h["shares"],
                "weight": h["weight"],
            })
        else:
            delta = h["shares"] - prev_map[code]["shares"]
            if delta == 0:
                continue
            pct = delta / prev_map[code]["shares"] * 100
            weight_delta = round(h["weight"] - prev_map[code]["weight"], 4)
            entry = {
                "code": code,
                "name": h["name"],
                "shares_delta": delta,
                "shares_pct": round(pct, 2),
                "weight_delta": weight_delta,
                "weight_curr": h["weight"],
            }
            if delta > 0:
                result["increased"].append(entry)
            else:
                result["decreased"].append(entry)

    for code, h in prev_map.items():
        if code not in curr_map:
            result["removed"].append({
                "code": code,
                "name": h["name"],
                "shares_prev": h["shares"],
                "weight_prev": h["weight"],
            })

    return result


def save_data(data: dict, date_str: str, data_dir: Path = Path("data")) -> None:
    """Write dated JSON/CSV snapshots and overwrite latest.*"""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    json_path = data_dir / f"{date_str}.json"
    csv_path = data_dir / f"{date_str}.csv"

    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "code", "name", "shares", "amount", "weight"])
        writer.writeheader()
        for h in data["holdings"]:
            writer.writerow({
                "date": date_str,
                "code": h["code"],
                "name": h["name"],
                "shares": h["shares"],
                "amount": h["amount"],
                "weight": h["weight"],
            })

    shutil.copy(json_path, data_dir / "latest.json")
    shutil.copy(csv_path, data_dir / "latest.csv")


def load_previous(today: str, data_dir: Path = Path("data")) -> dict | None:
    """Return the most recent snapshot before today, or None."""
    data_dir = Path(data_dir)
    date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")
    candidates = sorted(
        (p for p in data_dir.glob("*.json") if date_pattern.match(p.name) and p.stem < today),
        reverse=True,
    )
    if not candidates:
        return None
    return json.loads(candidates[0].read_text(encoding="utf-8"))


def _build_daily_report(data: dict, diff: dict) -> str:
    total_asset_yi = data["total_asset"] / 1e8
    n_added = len(diff["added"])
    n_removed = len(diff["removed"])
    n_increased = len(diff["increased"])
    n_decreased = len(diff["decreased"])

    lines = [
        f"## 主動統一台股增長 (00981A) · 主動操作日報",
        f"",
        f"**資料日期：{data['date']}** | 基金規模：{total_asset_yi:,.2f} 億 | 每單位淨值：{data['nav']}",
        f"",
        f"| 新增持股 | 主動加碼 | 主動減碼 | 刪除持股 |",
        f"|:---:|:---:|:---:|:---:|",
        f"| {n_added} ➕ | {n_increased} ⬆️ | {n_decreased} ⬇️ | {n_removed} ❌ |",
    ]

    has_changes = n_added + n_removed + n_increased + n_decreased > 0
    if not has_changes:
        lines += ["", "### 今日無異動"]
        return "\n".join(lines)

    lines += ["", "### 成分股操作明細", ""]
    lines += ["| 代號 | 名稱 | 動作 | 股數變動 | 股數變動% | 權重變動% | 目前權重 |"]
    lines += ["|---|---|---|---:|---:|---:|---:|"]

    for h in diff["added"]:
        lines.append(f"| {h['code']} | {h['name']} | ➕ 新增 | +{h['shares']:,} | — | — | {h['weight']:.2f}% |")

    for h in diff["increased"]:
        sign = "+" if h["shares_delta"] > 0 else ""
        lines.append(
            f"| {h['code']} | {h['name']} | ⬆️ 加碼 | {sign}{h['shares_delta']:,} | "
            f"{sign}{h['shares_pct']:.2f}% | {sign}{h['weight_delta']:.2f}% | {h['weight_curr']:.2f}% |"
        )

    for h in diff["decreased"]:
        lines.append(
            f"| {h['code']} | {h['name']} | ⬇️ 減碼 | {h['shares_delta']:,} | "
            f"{h['shares_pct']:.2f}% | {h['weight_delta']:.2f}% | {h['weight_curr']:.2f}% |"
        )

    for h in diff["removed"]:
        lines.append(f"| {h['code']} | {h['name']} | ❌ 刪除 | -{h['shares_prev']:,} | — | -{h['weight_prev']:.2f}% | 0.00% |")

    return "\n".join(lines)


def _build_holdings_table(data: dict) -> str:
    holdings_sorted = sorted(data["holdings"], key=lambda h: h["weight"], reverse=True)
    lines = [
        "### 完整持股清單（依權重排序）",
        "",
        "| 代號 | 名稱 | 持股數（張） | 市值（億） | 權重% |",
        "|---|---|---:|---:|---:|",
    ]
    for h in holdings_sorted:
        shares_k = h["shares"] // 1000
        amount_yi = h["amount"] / 1e8
        lines.append(f"| {h['code']} | {h['name']} | {shares_k:,} | {amount_yi:.2f} | {h['weight']:.2f}% |")
    return "\n".join(lines)


def update_readme(data: dict, diff: dict, readme_path: Path = Path("README.md")) -> None:
    """Replace content between marker comments in README.md."""
    readme_path = Path(readme_path)
    content = readme_path.read_text(encoding="utf-8")

    daily_report = _build_daily_report(data, diff)
    holdings_table = _build_holdings_table(data)

    def replace_block(text: str, start_marker: str, end_marker: str, new_content: str) -> str:
        pattern = rf"({re.escape(start_marker)}\n).*?(\n{re.escape(end_marker)})"
        if not re.search(pattern, text, flags=re.DOTALL):
            raise ValueError(f"Marker not found in README: {start_marker}")
        return re.sub(pattern, lambda m: m.group(1) + new_content + m.group(2), text, flags=re.DOTALL)

    content = replace_block(content, "<!-- DAILY_REPORT_START -->", "<!-- DAILY_REPORT_END -->", daily_report)
    content = replace_block(content, "<!-- HOLDINGS_TABLE_START -->", "<!-- HOLDINGS_TABLE_END -->", holdings_table)

    readme_path.write_text(content, encoding="utf-8")


URL = "https://www.ezmoney.com.tw/ETF/Fund/Info?fundCode=49YTW"
_DATA_ASSET_RE = re.compile(r"id=\"DataAsset\"\s+data-content='([^']+)'")


def parse_holdings_from_html(html: str) -> dict:
    """Extract fund holdings from raw HTML. Pure function — no network calls."""
    m = _DATA_ASSET_RE.search(html)
    if not m:
        raise ValueError("DataAsset element not found in HTML")

    asset_list = json.loads(m.group(1))
    asset_map = {a["AssetCode"]: a for a in asset_list}

    nav = asset_map.get("P_UNIT", {}).get("Value", 0.0)
    total_asset = asset_map.get("NAV", {}).get("Value", 0)
    details = asset_map.get("ST", {}).get("Details") or []

    # Extract data date from EditDate (e.g. "2026-05-26T16:30:28") — take date part only
    edit_date = asset_map.get("ST", {}).get("EditDate") or asset_map.get("P_UNIT", {}).get("EditDate", "")
    data_date = edit_date[:10] if edit_date else ""

    holdings = [
        {
            "code": d["DetailCode"],
            "name": d["DetailName"],
            "shares": int(d["Share"]),
            "amount": int(d["Amount"]),
            "weight": d["NavRate"],
        }
        for d in details
    ]
    holdings.sort(key=lambda h: h["weight"], reverse=True)

    return {
        "fund_code": "00981A",
        "date": data_date,
        "nav": nav,
        "total_asset": int(total_asset),
        "holdings": holdings,
    }


def fetch_holdings(max_retries: int = 3) -> dict:
    """Fetch holdings from ezmoney with retry. Calls sys.exit(1) on failure."""
    from scrapling.fetchers import Fetcher
    for attempt in range(max_retries):
        try:
            page = Fetcher.get(URL, impersonate="chrome", timeout=30)
            return parse_holdings_from_html(page.html_content)
        except Exception as e:
            wait = 2 ** attempt  # 1s, 2s, 4s
            print(f"[attempt {attempt + 1}/{max_retries}] Error: {e}. Retrying in {wait}s...")
            if attempt < max_retries - 1:
                time.sleep(wait)
    print("All retries exhausted. Exiting.")
    sys.exit(1)


def main():
    print("Fetching holdings...")
    data = fetch_holdings()
    data_date = data["date"]
    print(f"Fetched {len(data['holdings'])} holdings. Date={data_date} NAV={data['nav']}")

    prev = load_previous(data_date)
    diff = compute_diff(prev, data)

    print(f"Diff: {len(diff['added'])} added, {len(diff['increased'])} increased, "
          f"{len(diff['decreased'])} decreased, {len(diff['removed'])} removed")

    save_data(data, data_date)
    print(f"Saved data/{data_date}.json and data/{data_date}.csv")

    update_readme(data, diff)
    print("README.md updated.")


if __name__ == "__main__":
    main()
