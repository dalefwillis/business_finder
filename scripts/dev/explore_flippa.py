"""Explore Flippa.com structure to discover selectors.

This script helps discover the actual page structure and selectors needed
for the Flippa scraper. Run with --headless=false to see the browser.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from playwright.async_api import async_playwright


async def explore_flippa(headless: bool = True, url: str | None = None):
    """Explore Flippa page structure."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context()
        page = await context.new_page()

        # Navigate to search page
        target_url = url or "https://flippa.com/search"
        print(f"Navigating to: {target_url}")
        await page.goto(target_url)
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(2)  # Let dynamic content load

        print("\n" + "=" * 60)
        print("PAGE STRUCTURE ANALYSIS")
        print("=" * 60)

        # Check page title
        title = await page.title()
        print(f"\nPage title: {title}")

        # Check for common card/listing selectors
        selectors_to_try = [
            # Common patterns
            "[data-testid*='listing']",
            "[data-testid*='card']",
            ".listing-card",
            ".ListingCard",
            ".listing",
            ".card",
            "article",
            # Flippa-specific guesses
            "[class*='Listing']",
            "[class*='listing']",
            "[class*='Card']",
            "[class*='card']",
            "[class*='result']",
            "[class*='Result']",
            "a[href*='/listing/']",
            "a[href*='/business/']",
            "a[href^='/'][href$='-']",  # Slug pattern like /listing-name-123
        ]

        print("\n--- Trying selectors ---")
        for selector in selectors_to_try:
            try:
                elements = await page.query_selector_all(selector)
                if elements:
                    print(f"  {selector}: {len(elements)} elements")
                    # Get first element's tag and classes
                    if len(elements) > 0:
                        tag = await elements[0].evaluate("el => el.tagName")
                        classes = await elements[0].evaluate("el => el.className")
                        print(f"    First: <{tag.lower()}> class='{classes[:100]}...' ")
            except Exception as e:
                print(f"  {selector}: ERROR - {e}")

        # Look for embedded JSON data
        print("\n--- Looking for embedded JSON data ---")
        scripts = await page.query_selector_all("script[type='application/json'], script#__NEXT_DATA__, script[id*='DATA']")
        print(f"Found {len(scripts)} potential JSON script tags")

        for i, script in enumerate(scripts):
            try:
                content = await script.inner_text()
                if len(content) > 100:
                    # Try to parse and summarize
                    data = json.loads(content)
                    print(f"\n  Script {i + 1}: Valid JSON ({len(content)} chars)")
                    if isinstance(data, dict):
                        print(f"    Top keys: {list(data.keys())[:10]}")
                        # Look for listings-like arrays
                        for key in data.keys():
                            if isinstance(data.get(key), list) and len(data[key]) > 0:
                                print(f"    {key}: array with {len(data[key])} items")
                                if isinstance(data[key][0], dict):
                                    print(f"      First item keys: {list(data[key][0].keys())[:8]}")
                        # Check props.pageProps for Next.js
                        if "props" in data and "pageProps" in data.get("props", {}):
                            pp = data["props"]["pageProps"]
                            print(f"    pageProps keys: {list(pp.keys())[:10]}")
            except json.JSONDecodeError:
                print(f"  Script {i + 1}: Not valid JSON")
            except Exception as e:
                print(f"  Script {i + 1}: Error - {e}")

        # Try to find links to individual listings
        print("\n--- Looking for listing links ---")
        links = await page.query_selector_all("a[href]")
        listing_links = []
        for link in links[:100]:  # Check first 100 links
            href = await link.get_attribute("href")
            if href and ("/listing" in href or "/business" in href or "/saas" in href):
                text = await link.inner_text()
                listing_links.append((href, text[:50] if text else ""))

        # Remove duplicates
        listing_links = list(set(listing_links))[:20]
        if listing_links:
            print(f"Found {len(listing_links)} potential listing links:")
            for href, text in listing_links[:10]:
                print(f"  {href}")
                if text:
                    print(f"    Text: {text[:40]}")
        else:
            print("No listing links found")
            # Try broader link patterns
            print("\n  Trying broader patterns...")
            for link in links[:50]:
                href = await link.get_attribute("href")
                if href and href.startswith("/") and len(href) > 5:
                    print(f"    {href}")

        # Get main content area structure
        print("\n--- Main content structure ---")
        main_content = await page.query_selector("main, #main, .main, [role='main']")
        if main_content:
            html = await main_content.inner_html()
            # Show first 2000 chars of structure
            print(f"Main content preview:\n{html[:2000]}...")
        else:
            print("No main content element found")
            body = await page.query_selector("body")
            if body:
                # Get first-level children
                children = await body.evaluate(
                    "el => Array.from(el.children).map(c => c.tagName + (c.className ? '.' + c.className.split(' ')[0] : ''))"
                )
                print(f"Body children: {children[:10]}")

        # If not headless, wait for user to explore
        if not headless:
            print("\n" + "=" * 60)
            print("Browser is open. Press Enter to close...")
            print("=" * 60)
            input()

        await browser.close()


def main():
    parser = argparse.ArgumentParser(description="Explore Flippa page structure")
    parser.add_argument(
        "--headless",
        type=str,
        default="true",
        help="Run browser in headless mode (true/false)",
    )
    parser.add_argument(
        "--url",
        type=str,
        default=None,
        help="URL to explore (default: flippa.com/search)",
    )
    args = parser.parse_args()

    headless = args.headless.lower() != "false"
    asyncio.run(explore_flippa(headless=headless, url=args.url))


if __name__ == "__main__":
    main()
