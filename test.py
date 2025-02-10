from website_evaluator import Website
import asyncio
from playwright.async_api import async_playwright

async def test(url):
    site = Website(url)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            args=[
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
            ]
        )
        context = await browser.new_context()
        await site.process_as_new_page(context)
        await browser.close()

    for issue in site.issues:
        print(issue)
url = "https://yiren54610.github.io/MVP/olympics.html"
asyncio.run(test(url))