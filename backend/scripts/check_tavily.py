import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
from tavily import TavilyClient

from app.config import settings

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

client = TavilyClient(api_key=settings.tavily_api_key)
result = client.search("current CEO of OpenAI", max_results=3, include_answer=True)
print(result.get("answer"))
for item in result["results"]:
    print(item["title"], item["url"])
