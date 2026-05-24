"""
Yahoo Fantasy scoring fetcher.
Uses browser automation (via Playwright/Selenium fallback) to log in and
pull the league's scoring settings from the Yahoo Fantasy web UI.

This is called from the ⚙️ Yahoo Settings tab in the dashboard when the
user enters their credentials.
"""

import json
import time
import re
from pathlib import Path

CACHE_FILE = Path(__file__).parent / "cache" / "yahoo_scoring.json"

YAHOO_BASE        = "https://football.fantasysports.yahoo.com"
YAHOO_LOGIN_URL   = "https://login.yahoo.com"
YAHOO_SCORING_URL = "{base}/f1/{league_id}/settings"   # league_id is numeric


def fetch_yahoo_scoring(email: str, password: str, league_id: str = "") -> dict | None:
    """
    Log into Yahoo Fantasy via Playwright and scrape scoring settings.
    Falls back to a manual instructions path if Playwright isn't available.

    Returns a dict of scoring rules, or None on failure.
    """

    # ── Try Playwright ─────────────────────────────────────────────────────
    try:
        return _fetch_with_playwright(email, password, league_id)
    except ImportError:
        pass
    except Exception as e:
        print(f"[Yahoo/Playwright] Error: {e}")

    # ── Try Selenium ───────────────────────────────────────────────────────
    try:
        return _fetch_with_selenium(email, password, league_id)
    except ImportError:
        pass
    except Exception as e:
        print(f"[Yahoo/Selenium] Error: {e}")

    return None


def _fetch_with_playwright(email: str, password: str, league_id: str) -> dict | None:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx     = browser.new_context(user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 Chrome/120.0.0 Safari/537.36"
        ))
        page = ctx.new_page()

        try:
            # 1) Navigate to Yahoo login
            page.goto(YAHOO_LOGIN_URL, timeout=15000)
            page.fill('input[name="username"]', email)
            page.click('input[type="submit"]')
            page.wait_for_timeout(2000)
            page.fill('input[name="password"]', password)
            page.click('button[type="submit"]')
            page.wait_for_timeout(3000)

            # 2) Go to Fantasy Football
            page.goto(f"{YAHOO_BASE}/f1", timeout=15000)
            page.wait_for_timeout(2000)

            # 3) If league_id provided, go straight there; else auto-detect
            if league_id:
                settings_url = f"{YAHOO_BASE}/f1/{league_id}/settings"
            else:
                # Try to find the first league link
                links = page.query_selector_all('a[href*="/f1/"]')
                found_url = None
                for link in links:
                    href = link.get_attribute("href") or ""
                    m = re.search(r"/f1/(\d+)", href)
                    if m:
                        found_url = f"{YAHOO_BASE}/f1/{m.group(1)}/settings"
                        break
                settings_url = found_url or f"{YAHOO_BASE}/f1"

            page.goto(settings_url, timeout=15000)
            page.wait_for_timeout(2000)
            html = page.content()

            scoring = _parse_yahoo_settings_html(html)
            if scoring:
                CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
                with open(CACHE_FILE, "w") as f:
                    json.dump(scoring, f, indent=2)
                return scoring

        except PWTimeout:
            print("[Yahoo] Page timed out")
        finally:
            browser.close()

    return None


def _fetch_with_selenium(email: str, password: str, league_id: str) -> dict | None:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.options import Options

    opts = Options()
    opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(options=opts)
    wait   = WebDriverWait(driver, 15)

    try:
        driver.get(YAHOO_LOGIN_URL)
        wait.until(EC.presence_of_element_located((By.NAME, "username")))
        driver.find_element(By.NAME, "username").send_keys(email)
        driver.find_element(By.CSS_SELECTOR, 'input[type="submit"]').click()
        time.sleep(2)
        wait.until(EC.presence_of_element_located((By.NAME, "password")))
        driver.find_element(By.NAME, "password").send_keys(password)
        driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
        time.sleep(3)

        driver.get(f"{YAHOO_BASE}/f1")
        time.sleep(2)

        if league_id:
            settings_url = f"{YAHOO_BASE}/f1/{league_id}/settings"
        else:
            links = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/f1/"]')
            found = None
            for link in links:
                href = link.get_attribute("href") or ""
                m = re.search(r"/f1/(\d+)", href)
                if m:
                    found = f"{YAHOO_BASE}/f1/{m.group(1)}/settings"
                    break
            settings_url = found or f"{YAHOO_BASE}/f1"

        driver.get(settings_url)
        time.sleep(2)
        html = driver.page_source

        scoring = _parse_yahoo_settings_html(html)
        if scoring:
            CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(CACHE_FILE, "w") as f:
                json.dump(scoring, f, indent=2)
            return scoring

    finally:
        driver.quit()

    return None


def _parse_yahoo_settings_html(html: str) -> dict | None:
    """Extract scoring rules from the Yahoo Fantasy settings page HTML."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")

        scoring = {}

        # Yahoo renders scoring in tables with class "ysf-settings"
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cells = row.find_all(["td", "th"])
                if len(cells) >= 2:
                    stat_name = cells[0].get_text(strip=True)
                    pts_text  = cells[-1].get_text(strip=True)
                    try:
                        pts = float(pts_text)
                        if stat_name:
                            scoring[stat_name] = pts
                    except ValueError:
                        pass

        # Also try JSON embedded in page scripts
        scripts = soup.find_all("script")
        for script in scripts:
            if script.string and "scoringSettings" in script.string:
                m = re.search(r'"scoringSettings"\s*:\s*(\{[^{}]+\})', script.string)
                if m:
                    try:
                        extra = json.loads(m.group(1))
                        scoring.update(extra)
                    except Exception:
                        pass

        return scoring if scoring else None

    except Exception as e:
        print(f"[Yahoo parse] {e}")
        return None


def load_cached_scoring() -> dict | None:
    """Load previously fetched Yahoo scoring from cache."""
    if CACHE_FILE.exists():
        with open(CACHE_FILE) as f:
            return json.load(f)
    return None
