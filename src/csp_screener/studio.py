"""LangGraph Studio exports for inspecting the application's live graphs."""

from dotenv import load_dotenv

from csp_screener.config import load_settings
from csp_screener.services import ApplicationService


load_dotenv()
service = ApplicationService(load_settings())

if service.agent is None:
    raise RuntimeError("OPENAI_API_KEY is required to load the research graph")

research_graph = service.agent.graph
shortlist_graph = service.agent.shortlist_graph
