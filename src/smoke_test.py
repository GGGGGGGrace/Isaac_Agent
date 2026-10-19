import os
import sys
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import OpenAI

WIKI_BASE = "https://bindingofisaacrebirth.wiki.gg/wiki/"
TEST_PAGE = "Brimstone"

HEADERS = {"User-Agent": "IsaacRAG/0.1 (karry19990921mdy@gmail.com)"}


def test_wiki() -> None:
    '''
    fetch one wiki.gg page as HTML and list its section headers
    '''
    url = WIKI_BASE + TEST_PAGE
    print(f"[wiki] GET {url}")

    resp = requests.get(url, headers=HEADERS, timeout=10)
    if resp.status_code in (403, 429):
        sys.exit(f"[wiki] Got {resp.status_code}, stopping. Do not retry aggressively.")
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")

    content = soup.select_one("#mw-content-text .mw-parser-output")
    if content is None:
        sys.exit("[wiki] Could not find the article body; page layout may differ.")
 
    headers = [h2.get_text(strip=True) for h2 in content.find_all("h2")]
    print(f"[wiki] Found {len(headers)} sections:")
    for h in headers:
        print(f"  - {h}")

def test_deepseek() -> None:
    load_dotenv()
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        sys.exit("[llm] DEEPSEEK_API_KEY not found. Check your .env file.")
 
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
 
    print("[llm] Calling deepseek-flash ...")
    resp = client.chat.completions.create(
        model="deepseek-flash",
        messages=[{"role": "user", "content": "Say hi in five words."}],
        # Thinking mode is on by default for DeepSeek. That's fine for a smoke
        # test; later, for RAG answers, check DeepSeek's Thinking Mode guide
        # for how to turn it off (passed via extra_body with the OpenAI SDK).
    )
    print(f"[llm] Reply: {resp.choices[0].message.content}")
    print(f"[llm] Tokens used: {resp.usage.total_tokens}")
 
 
if __name__ == "__main__":
    test_wiki()
    print()
    test_deepseek()
    print("\nSmoke test passed.")