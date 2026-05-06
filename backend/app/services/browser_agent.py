import asyncio
from playwright.async_api import async_playwright
import logging

logger = logging.getLogger(__name__)

class BrowserAgent:
    def __init__(self):
        self.browser_args = ["--disable-gpu", "---no-sandbox"]

    async def search_and_summarize(self, query: str):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=self.browser_args)
            page = await browser.new_page()

            logger.info(f"🌐 Browser Agent: Searching for '{query}'")

            try:
                await page.goto(f"https://duckduckgo.com/?q={query.replace(' ', '+')}")
                await page.wait_for_selector(".react-results--main")

                results = await page.evaluate("""
                    () => {
                        const items = Array.from(document.querySelectorAll('article')).slice(0, 3);
                        return items.map(item => ({
                            title: item.innerText,
                            url: item.querySelector('a')?.href
                        }));
                    }
                """)

                await browser.close()
                return results
            
            except Exception as e:
                logger.error(f"Browser Search Failed: {e}")
                await browser.close()
                return []
            
browser_agent = BrowserAgent()
