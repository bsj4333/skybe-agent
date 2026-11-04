import os

from langchain_openai import ChatOpenAI

from skive.config import load_environment

load_environment()


def get_llm(model: str | None = None) -> ChatOpenAI:
    return ChatOpenAI(model=model or os.getenv("SKIVE_MODEL", "gpt-4o-mini"), temperature=0)


def get_judge_llm() -> ChatOpenAI:
    return get_llm(os.getenv("SKIVE_JUDGE_MODEL", "gpt-4o"))
