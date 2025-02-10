from pathlib import Path
import logging
from website_evaluator import Website
import asyncio
from asyncio_pool import AioPool
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def scrape_all():
    urls = [w for w in Path("websites.txt").read_text().split("\n") if w != ""]
    websites = [Website(url) for url in urls]

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            args=[
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
            ]
        )
        context = await browser.new_context()

        async with AioPool(size=3) as pool:
            for site in websites:
                await pool.spawn(site.process_as_new_page(context))

        await browser.close()
    return websites

websites = asyncio.run(scrape_all())

table_starter = """
|url|mobile|medium|wide|
|---|---|---|---|
"""

toc_table = """<table><tr>"""
toc_image_num = 0

readme_md = """"""
issues_md = """"""
toc_md = """"""

prev_host = None
for site in websites:
    if site.hostname != prev_host:
        readme_md += issues_md
        readme_md += f"\n\n## {site.hostname}\n\n{table_starter}"
        toc_image_num += 1
        if site.successful_request:
            toc_table += f"""<td><a href="#{site.hostname.replace('.','')}"><img src="{site.shot_path('medium', 'thumb')}" alt="homepage screenshot"><br>{site.hostname}</a></td>\n"""
        else:
            toc_table += f"""<td>{site.hostname} request failed</td>\n"""
        if toc_image_num % 4 == 0:
            toc_table += "</tr><tr>\n"
        issues_md = f"\n\n### Automatic Checks\n\n"
        prev_host = site.hostname

    readme_md += site.get_table_row() + "\n"

    issues_md += f"**{site.url}**\n\n"
    if site.issues:
        issues_md += '\n'.join(site.issues)
        if not site.portfolio_page:
            issues_md += f"\n* 🤖 [Automatic feedback for copy edits]({site.feedback_path()})"
        issues_md += '\n\n'
    else:
        if not site.portfolio_page:
            issues_md += f"* 🤖 [Automatic feedback here]({site.feedback_path()})\n"
        issues_md += f"* No issues found! 🎉\n\n"


toc_table += "</tr></table>"

readme_md += issues_md

readme_md = (
    "# Data Studio 2025 Personal Projects Test Page\n\n" +
    "Quick checks to make sure our pages are looking their best!\n\n" +
    toc_md +
    toc_table + 
    "\n\n" +
    readme_md
)

Path("README.md").write_text(readme_md)