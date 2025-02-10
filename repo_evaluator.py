import re
from urllib.parse import urlparse
import json
import markdown
from bs4 import BeautifulSoup
import requests
import zipfile
import io
import os
from pathlib import Path
import tempfile
import shutil

class Repo:
    def __init__(self, username, repo_name):
        self.username = username
        self.repo_name = repo_name
        self.repo_path = f"{username}/{repo_name}"
        self.full_url = f"https://github.com/{self.repo_path}"
        self.zip_url = f"https://github.com/{self.repo_path}/archive/refs/heads/main.zip"
        
        self.issues = []
        self.temp_dir = None
        self.repo_dir = None
        
        # Download and extract the repository
        try:
            self.download_repo()
            self.readme = self.read_readme()
        except Exception as e:
            self.issues.append(f"* Failed to download repository: {str(e)}")
            self.readme = None

    def download_repo(self):
        """Download and extract the repository ZIP file"""
        response = requests.get(self.zip_url)
        if response.status_code == 404:
            # Try 'master' branch if 'main' doesn't exist
            self.zip_url = f"https://github.com/{self.repo_path}/archive/refs/heads/master.zip"
            response = requests.get(self.zip_url)
            
        if response.status_code != 200:
            raise Exception(f"Failed to download repository (status code: {response.status_code})")
            
        # Create temporary directory
        self.temp_dir = tempfile.mkdtemp()
        
        # Extract ZIP content
        with zipfile.ZipFile(io.BytesIO(response.content)) as zip_ref:
            zip_ref.extractall(self.temp_dir)
            
        # Get the extracted directory name (usually repo-name-branch)
        extracted_dirs = os.listdir(self.temp_dir)
        if not extracted_dirs:
            raise Exception("ZIP file was empty")
            
        self.repo_dir = os.path.join(self.temp_dir, extracted_dirs[0])

    def read_readme(self):
        """Read the README.md file content"""
        readme_path = os.path.join(self.repo_dir, "README.md")
        if not os.path.exists(readme_path):
            return None
        
        with open(readme_path, 'r', encoding='utf-8') as f:
            return f.read()

    def check_for_data(self):
        """Check for proper data file organization and documentation"""
        data_extensions = {'.csv', '.xlsx', '.json', '.geojson', '.shp', '.db', '.sqlite'}
        data_files = []
        
        # Walk through all files in the repository
        for root, _, files in os.walk(self.repo_dir):
            for file in files:
                if any(file.endswith(ext) for ext in data_extensions):
                    data_files.append(os.path.relpath(os.path.join(root, file), self.repo_dir))
                
        if not data_files:
            self.issues.append("* No data files found. Include your raw/processed data or document where it can be accessed")

    def check_links(self):
        if not self.readme:
            return
            
        # Convert markdown to HTML
        html = markdown.markdown(self.readme)
        soup = BeautifulSoup(html, 'html.parser')
        
        # Get all links
        links = [a.get('href') for a in soup.find_all('a')]
        
        # Check each link
        for link in links:
            if not link or link.startswith(('/', '#', 'mailto:')):
                continue

            try:
                response = requests.head(link, timeout=5, allow_redirects=True)
                if response.status_code >= 400:
                    self.issues.append(f"* Dead link found: {link}")
            except:
                self.issues.append(f"* Could not verify link: {link}")

    def check_notebooks(self):
        notebooks = []
        
        # Walk through all files in the repository
        for root, _, files in os.walk(self.repo_dir):
            for file in files:
                if file.endswith('.ipynb'):
                    notebooks.append(os.path.join(root, file))

        if not notebooks:
            self.issues.append("* No Jupyter notebooks found, please add your analysis.")
        else:
            # Check notebook content
            for nb_path in notebooks:
                try:
                    with open(nb_path, 'r', encoding='utf-8') as f:
                        nb_content = json.load(f)
                    
                    cells = nb_content.get('cells', [])
                    nb_name = os.path.basename(nb_path)
                    
                    # Check for markdown cells at the top
                    if not cells or cells[0]['cell_type'] != 'markdown':
                        self.issues.append(f"* Notebook `{nb_name}` should start with markdown explanation")
                    
                    # Check for mixed markdown and code cells
                    markdown_cells = sum(1 for cell in cells if cell['cell_type'] == 'markdown')
                    if markdown_cells < len(cells) * 0.15:  # At least 15% should be markdown
                        self.issues.append(f"* Notebook `{nb_name}` needs more markdown documentation")
                except Exception as e:
                    self.issues.append(f"* Could not analyze notebook {os.path.basename(nb_path)}: {str(e)}")

    def check_readme(self):
        if not self.readme:
            self.issues.append("* [README](https://jonathansoma.com/fancy-github/readme/) not found")
            return

        # Check for project page link
        if "github.io" not in self.readme.lower():
            self.issues.append("* README needs link to project page")

        if self.readme.count(" ") < 150:
            self.issues.append("* [README](https://jonathansoma.com/fancy-github/readme/) looks short, not enough content")
        
        if self.readme.count("\n#") < 4:
            self.issues.append("* README not organized into sections, use [h2/h3 headers](https://www.markdownguide.org/basic-syntax/)")

        # Check README sections
        required_sections = {
            "description": ["aim", "goal", "purpose", "about", "inten"],
            "data collection": ["collect", "download", "scrap", "acquir"],
            "data analysis": ["analys", "analyz", "process", "pandas"],
            "skills": ["used", "skill", "learn", "grow", "develop"],
            "reflections or future work": ["future", "next step", "limitation", "challenge", "tried to"]
        }

        # Check for required content
        readme_lower = self.readme.lower()
        missing_sections = []
        
        for section, keywords in required_sections.items():
            if not any(kw in readme_lower for kw in keywords):
                missing_sections.append(section)
        
        if missing_sections:
            self.issues.append(f"* README seems to be missing required sections: {', '.join(missing_sections)}")

    def check_files(self):
        # Check for .gitignore
        gitignore_path = os.path.join(self.repo_dir, ".gitignore")
        if not os.path.exists(gitignore_path):
            self.issues.append("* Missing [`.gitignore`](https://jonathansoma.com/fancy-github/organization/gitignore.html) file")
        else:
            with open(gitignore_path, 'r', encoding='utf-8') as f:
                gitignore_content = f.read()
                if len(gitignore_content.strip()) < 10:
                    self.issues.append("* .gitignore file seems empty or too small")

        # Check for unwanted files
        bad_files = [".DS_Store", ".ipynb_checkpoints", "__pycache__"]
        bad_files_included = []
        for root, _, files in os.walk(self.repo_dir):
            for file in files:
                if file in bad_files:
                    rel_path = os.path.relpath(os.path.join(root, file), self.repo_dir)
                    bad_files_included.append(rel_path)
        if len(bad_files_included) > 0:
            self.issues.append("* Should not include these file(s), please remove:")
            for filename in bad_files_included:
                self.issues.append(f"    * `{filename}`")

    def run_checks(self):
        if not self.readme:
            return

        self.check_readme()
        self.check_files()
        self.check_notebooks()
        self.check_links()
        self.check_for_data()

    def cleanup(self):
        """Remove temporary directory and its contents"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    @classmethod
    def from_site(cls, url):
        # Parse the URL and get the hostname + path
        parsed = urlparse(url if '://' in url else f'https://{url}')
        
        # Extract username from github.io domain
        match = re.match(r'([^.]+)\.github\.io$', parsed.netloc)
        if not match:
            raise ValueError("Invalid GitHub Pages URL")
            
        username = match.group(1)
        
        # Clean the path (remove leading/trailing slashes and any file extensions)
        clean_path = re.sub(r'/.*$', '', parsed.path.strip('/')) if parsed.path else ''
        
        # For username.github.io sites, the repo name is username.github.io
        repo_name = f"{username}.github.io" if not clean_path else clean_path
        
        return cls(username, repo_name)

    def __del__(self):
        """Ensure cleanup of temporary files when object is destroyed"""
        self.cleanup()