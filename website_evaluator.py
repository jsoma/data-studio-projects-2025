from pathlib import Path
import logging
from urllib.parse import urlparse
from PIL import Image
import time
import json
from ai_editor import get_ap_feedback
from repo_evaluator import Repo
from bs4 import BeautifulSoup
import requests
import tempfile
from doctr.io import DocumentFile
from doctr.models import detection_predictor
import mimetypes
from urllib.parse import urljoin
import tempfile
import os
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OUTPUT_DIR = "screenshots"
FEEDBACK_DIR = "feedback"
SIZES = {"mobile": 400, "medium": 900, "wide": 1300}
TEXT_DETECTION_MODEL = detection_predictor(pretrained=True)

class Website:
    def __init__(self, url):
        self.url = url

        pieces = urlparse(url)
        self.hostname = pieces.hostname
        if pieces.path.endswith("html"):
            self.urlpath = pieces.path.strip("/")
        else:
            self.urlpath = pieces.path.strip("/") + "/index.html"
        self.urlpath = self.urlpath.strip("/")
        self.portfolio_page = self.urlpath == "" or self.urlpath == "index.html"
        self.repo = Repo.from_site(url)
        self.issues = []

    async def load(self, page):
        """Load the web page"""
        logger.info(f"{self.url}: Loading")

        self.page = page
        self.page_title = "REQUEST FAILED"
        try:
            response = await self.page.goto(self.url, timeout=60000)
        except:
            logger.info(f"{self.url}: Failed to load page")
            # Exit early if fails to load
            self.successful_request = False
            return

        if response and response.ok:
            self.successful_request = True
        else:
            self.successful_request = False
        time.sleep(1)
        await self.page.evaluate(
            "window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });"
        )
        time.sleep(2)
        await self.get_desc_details()

    async def get_all_meta_tags(self):
        self.meta = {}
        self.meta['og:title'] = await self.get_meta("og:title")
        # self.meta['og:type'] = self.get_meta("og:type")
        self.meta['og:description'] = await self.get_meta("og:description")
        self.meta['og:image'] = await self.get_meta("og:image")
        # self.meta['twitter:card'] = self.get_meta("twitter:card", "name")

    async def get_meta(self, property, property_type='property'):
        logger.info(f"Getting {property}")
        qs = await self.page.query_selector(f"meta[{property_type}='{property}']")
        if qs:
            return await qs.get_attribute('content')
        else:
            return None

    async def screenshot_all(self):
        """Take a screenshot at each screen size"""
        for size in SIZES.keys():
            await self.screenshot_one(size)

    async def get_desc_details(self):
        logger.info(f"{self.url}: Getting desc details")
        self.page_title = await self.page.title() or self.urlpath

        logger.info(f"{self.url}: Page title is {self.page_title}")
        for character in ['|', '[', ']']:
            self.page_title = self.page_title.replace(character, "")

        await self.get_all_meta_tags()

    def build_desc(self):
        page_link = f"[{self.page_title}]({self.url})"
        try:
            metas = '<br>'.join([f":x: {key}" for key, value in self.meta.items() if value is None])

            if metas:
                desc = f"|{page_link}<br>{metas}<br>[how to fix](https://jonathansoma.com/everything/web/social-tags/)|"
            else:
                desc = f"|{page_link}|"
        except:
                desc = f"|{page_link}|"
        return desc


    def get_table_row(self):
        """Markdown display of screenshots for this web page"""
        desc = self.build_desc()
        if self.successful_request:
            images = [
                f"[![{size}]({self.shot_path(size, 'thumb')})]({self.shot_path(size)})"
                for size in SIZES.keys()
            ]
        else:
            images = [ f"request failed" for size in SIZES.keys() ]

        return desc + "|".join(images) + "|"

    def feedback_path(self):
        basename = self.urlpath.replace("/", "_").replace(" ", "%20").replace("/index.html", "")
        path = Path(FEEDBACK_DIR).joinpath(self.hostname).joinpath(f"{basename}.md")
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    
    async def build_feedback(self):
        feedback_file = self.feedback_path()

        if feedback_file.exists():
            return
        
        logger.info(f"{self.url}: Getting LLM feedback")

        # get page html
        html = await self.page.content()
        feedback = get_ap_feedback(html)
        text = f"# Feedback for [{self.page_title}]({self.url})\n\n[Request updated copy edits](https://github.com/jsoma/data-studio-projects-2024/issues/new/choose)\n\n## AP Style Feedback\n\n{feedback}"
        feedback_file.write_text(text)

    def shot_path(self, size, version="full"):
        """Returns the file path for a given screenshot size and version"""
        basename = self.urlpath.replace("/", "_").replace(" ", "%20")
        filename = f"{basename}-{size}-{version}.jpg"
        return Path(OUTPUT_DIR).joinpath(self.hostname).joinpath(filename)

    async def screenshot_one(self, size):
        """Create a screenshot at a given screen width"""
        width = SIZES[size]
        filepath = self.shot_path(size)
        await self.page.set_viewport_size({"width": width, "height": 700})
        time.sleep(0.5)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"{self.url}: {width}px screenshot to {filepath}")

        await self.page.screenshot(path=filepath, full_page=True, type='jpeg')

        thumb_path = self.shot_path(size, "thumb")
        logger.info(f"{self.url}: Creating thumbnail at {thumb_path}")
        with Image.open(filepath) as img:
            box = (0, 0, img.size[0], img.size[0])
            img.crop(box).resize((400, 400)).save(thumb_path)
    
    async def check_links(self):
        soup = BeautifulSoup(await self.page.content(), 'html.parser')
        
        # Get all links
        links = [a.get('href') for a in soup.find_all('a')]
        
        # Check each link
        for link in links:
            if not link or link.startswith(('/', '#', 'mailto:')):
                continue

            try:
                headers = { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36' }
                response = requests.head(link, timeout=10, allow_redirects=True, headers=headers)
                if response.status_code >= 400:
                    self.issues.append(f"* Dead link found: {link}")
            except:
                self.issues.append(f"* Could not verify link: {link}")

    async def run_checks(self):
        logger.info(f"{self.url}: Running automatic checks")
        self.issues = []
        tiny_text = await self.page.evaluate("""
        () => [...document.querySelectorAll(".ai2html p")]
            .filter(d => window.getComputedStyle(d)['font-size'].indexOf("px") != -1)
            .filter(d => parseFloat(window.getComputedStyle(d)['font-size']) < 11)
            .map((d) => {
                return {
                    text: d.innerText,
                    size: window.getComputedStyle(d)['font-size']
                }
            })
        """)
        await self.page.set_viewport_size({"width": SIZES['mobile'], "height": 700})
        has_sideways_scroll = await self.page.evaluate("() => document.body.scrollWidth > window.innerWidth")
        missing_viewport_tag = await self.page.evaluate("() => !document.querySelector('meta[name=viewport]')")
        overlapping_elements = []
        for width in SIZES.values():
            await self.page.set_viewport_size({"width": width, "height": 700})
            new_overlaps = await self.page.evaluate("""
                () => {
                    function overlaps(e1, e2) {
                        const buffer = 5;
                        const rect1 = e1.getBoundingClientRect();
                        const rect2 = e2.getBoundingClientRect();
                        if(rect1.width == 0 || rect2.width == 0) {
                            return false
                        }
                        return !(rect1.right - buffer < rect2.left || 
                            rect1.left + buffer > rect2.right || 
                            rect1.bottom - buffer < rect2.top || 
                            rect1.top + buffer > rect2.bottom)
                    }

                    const elements = [...document.querySelectorAll('.ai2html p')];
                    const overlappingElements = []
                    for(let i = 0; i < elements.length; i++) {
                        const e1 = elements[i];
                        for(let j = i+1; j < elements.length; j++) {
                            const e2 = elements[j];
                            if(overlaps(e1, e2) && e1.innerText.trim() !== '' && e2.innerText.trim() !== '') {
                                overlappingElements.push({
                                    text1: e1.innerText,
                                    text2: e2.innerText,
                                    width: window.innerWidth
                                })
                            }
                        }
                    }
                    return overlappingElements
                }
            """)
            overlapping_elements.extend(new_overlaps)

        missing_fonts = await self.page.evaluate("""
            () => {
                function groupBy(objectArray, property) {
                    return objectArray.reduce((acc, obj) => {
                    const key = obj[property];
                    if (!acc[key]) {
                        acc[key] = [];
                    }
                    // Add object to list for given key's value
                    acc[key].push(obj);
                    return acc;
                    }, { });
                }
                
                const objects = [...document.querySelectorAll(".ai2html p")]
                    .filter(d => !(document.fonts.check("12px " + window.getComputedStyle(d)['font-family'])))
                    .map(d => {
                        return {
                            text: d.innerText,
                            font: window.getComputedStyle(d)['font-family']
                        }
                    })

                return groupBy(objects, 'font')
            }
        """)

        if not self.successful_request:
            self.issues.append("* **Could not access the page** - if you moved it, [let me know](https://github.com/jsoma/data-studio-projects-2024/issues/new/choose)!")
            return
    
        if not await self.page.title():
            self.issues.append("* Needs a title, add a `<title>` tag to the `<head>`")

        if str(self.urlpath).strip('/').count('/') > 1:
            self.issues.append("* URL should be first level, `/volcanoes` not `/stories/volcanoes`")

        if 'project' in str(self.urlpath).lower() or 'story' in str(self.urlpath).lower():
            self.issues.append("* URL should be descriptive, not including `project` or `story`")

        if not self.urlpath.endswith("index.html"):
            name = self.urlpath.split("/")[-1].replace(".html", "")
            self.issues.append(f"* All HTML files should be named `index.html`. If this is a personal project, move `{self.urlpath}` into a folder (or repo) called `{name}`, then rename the file `index.html`. That way the project can be found at **/{name}** instead of **/{name}.html**. [Read more about index.html here](https://www.thoughtco.com/index-html-page-3466505) or how it works specifically with GitHub repos [on Fancy GitHub](https://jonathansoma.com/fancy-github/github-pages/#choosing-your-url)")

        if ' ' in self.url or '_' in self.url:
            self.issues.append("* Change URL to use `-` instead of spaces or underscores")

        if self.url != self.url.lower():
            self.issues.append("* Change URL to be all in lowercase")

        if missing_viewport_tag:
            self.issues.append('* Missing viewport meta tag in `<head>`, needed to tell browser it\'s responsive. Add `<meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no">`')
        if has_sideways_scroll:
            self.issues.append(f"* Has sideways scrollbars in mobile version – check padding, margins, image widths")

        # alt tags
        img_missing_alt_tags = await self.page.query_selector_all('img:not([alt])')
        if img_missing_alt_tags:
            self.issues.append(f"* Image(s) need `alt` tags, [info here](https://abilitynet.org.uk/news-blogs/five-golden-rules-compliant-alt-text) and [tips here](https://twitter.com/FrankElavsky/status/1469023374529765385)")
            for img in img_missing_alt_tags[:5]:
                self.issues.append(f"    * Image `{await img.get_attribute('src')}` missing `alt` tag")
            if len(img_missing_alt_tags) > 5:
                self.issues.append(f"    * *and {len(img_missing_alt_tags) - 5} more*")

        if self.portfolio_page:
            return

        # Page load doesn't really work with async?
        # self.load_duration_s = await self.page.evaluate(
        #     "() => performance.getEntriesByType('navigation')[0]['duration']"
        # ) / 1000
        # if self.load_duration_s > 5:
        #     self.issues.append(f"* Page took {round(self.load_duration_s, 2)}s to load, check image/table sizes")

        github_link = await self.page.query_selector("a[href*='github.com']")
        if not github_link:
            self.issues.append("* Add a link to your project's GitHub repo, so people can review your code")

        # Descriptions for datawrapper charts
        datawrapper_charts = await self.page.query_selector_all(".dw-chart")
        for chart in datawrapper_charts:
            if not await chart.query_selector_all(".sr-only"):
                self.issues.append("* Datawrapper chart missing description, fill out *Alternative description for screen readers* section on Annotate tab, [tips here](https://twitter.com/FrankElavsky/status/1469023374529765385)")

        if tiny_text:
            self.issues.append("* Minimum font size should be 12px, enlarge text in CSS or Illustrator")
            for text in tiny_text[:7]:
                if text['text'] != "":
                    self.issues.append(f"    * Text `{text['text']}` is too small at {text['size']}")
            if len(tiny_text) > 7:
                self.issues.append(f"    * *and {len(tiny_text) - 7} more*")

        await self.check_images()
        await self.check_links()

        self.repo.run_checks()
        if len(self.repo.issues) > 0:
            self.issues.append(f"\n#### [Project repository]({self.repo.full_url}) issues\n")
            self.issues.extend(self.repo.issues)

        # TODO
        # if overlapping_elements:
        #     self.issues.append("* Overlapping elements in ai2html, check [the overflow video](https://www.youtube.com/watch?v=6vHsnjTp3_w) or make a smaller size")
        #     for overlap in overlapping_elements[:7]:
        #         self.issues.append(f"   * Text `{overlap['text1']}` overlaps with `{overlap['text2']}` at screen width {overlap['width']}")
        #     if len(overlapping_elements) > 7:
        #         self.issues.append(f"   * *and {len(overlapping_elements) - 7} more*")

        # TODO
        # if missing_fonts:
        #     self.issues.append("* Missing font(s), you might need web fonts – [text explanation](https://gist.github.com/jsoma/631621e0807b26d49f5aef5260f79162), [video explanation](https://www.youtube.com/watch?v=HNhIeb_jEYM&list=PLewNEVDy7gq3MSrrO3eMEW8PhGMEVh2X2&index=3)")
        #     for key, values in missing_fonts.items():
        #         self.issues.append(f"    * `{key}` font not found, used in {len(values)} text objects. Example: _{', '.join([v['text'] for v in values[:3]])}_")

        # Make sure this isn't just a root domain
        if not self.portfolio_page:
            await self.build_feedback()

    async def check_images(self):
        html = await self.page.content()
        doc = BeautifulSoup(html, 'html.parser')
        images = doc.find_all('img')
        
        base_url = await self.page.evaluate('document.baseURI')
        
        for img in images:
            image_issues = []
            src = img.get('src')
            if not src:
                continue
            
            # Resolve relative URLs
            url = urljoin(base_url, src)
            try:
                # Download image
                response = requests.get(url)
                
                # Get correct extension from content-type
                content_type = response.headers['content-type']
                extension = mimetypes.guess_extension(content_type) or '.jpg'
                
                filename = src.split("/")[-1]

                # Save to temp file
                with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as tmp:
                    tmp.write(response.content)
                    tmp_path = tmp.name
                
                try:
                    pil_image = Image.open(tmp_path)
                    if pil_image.height > 2500 or pil_image.height > 2500:
                        image_issues.append(f"Image is too big at {pil_image.width}x{pil_image.height}")

                    # Process with docTR
                    doc = DocumentFile.from_images(tmp_path)
                    result = TEXT_DETECTION_MODEL(doc)
                    
                    words = [word for word in result[0]['words'] if word[-1] > 0.7]
                    if len(words) > 4:
                        image_issues.append(f"Image has text, should use [ai2html](https://www.youtube.com/playlist?list=PLewNEVDy7gq3MSrrO3eMEW8PhGMEVh2X2) for accessibility")

                    ratio = pil_image.height / pil_image.width

                    heights = [word[3] - word[1] for word in result[0]['words'] if word[-1] > 0.5]
                    heights = [height * ratio * 375 for height in heights]

                    min_height = min(heights)
                    max_height = max(heights)
                    if min_height <= 12:
                        image_issues.append(f"Text is too small: on phones, text is as small as {min_height:.1f}px. Minimum is 12px, more [here](https://service-manual.ons.gov.uk/data-visualisation/build-specifications/typography) and [here](https://nightingaledvs.com/choosing-fonts-for-your-data-visualization/)")
                finally:
                    # Clean up temp file
                    os.unlink(tmp_path)
                    
            except Exception as e:
                print(e)
                image_issues.append(f"Could not analyze image `{filename}`")

            if len(image_issues) == 1:
                self.issues.append(f"* Image: `{filename}` {issue}")
            elif len(image_issues) > 0:
                self.issues.append(f"* Image: `{filename}`")
                for issue in image_issues:
                    self.issues.append(f"    * {issue}")

    async def process_as_new_page(self, context):
        await self.load(await context.new_page())
        if self.successful_request:
            await self.screenshot_all()
        await self.run_checks()
