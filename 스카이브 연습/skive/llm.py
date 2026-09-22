import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()


def get_llm(model: str | None = None) -> ChatOpenAI:
    return ChatOpenAI(model=model or os.getenv("SKIVE_MODEL", "gpt-4o-mini"), temperature=0)


def get_judge_llm() -> ChatOpenAI:
    return get_llm(os.getenv("SKIVE_JUDGE_MODEL", "gpt-4o"))
