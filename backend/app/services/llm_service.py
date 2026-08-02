from functools import lru_cache

from langchain_core.language_models import BaseChatModel


@lru_cache
def get_check_in_llm() -> BaseChatModel:
    """Claude Haiku via LiteLLM — fast, low-cost for conversational extraction."""
    from app.utils.config import get_settings
    settings = get_settings()

    if settings.llm_provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=settings.check_in_model or "gpt-4o-mini",
            api_key=settings.openai_api_key or None,
            max_tokens=2048,
        )

    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(
        model=settings.check_in_model or "claude-haiku-4-5",
        api_key=settings.anthropic_api_key or None,
        max_tokens=2048,
        thinking={"type": "disabled"},
    )


@lru_cache
def get_analysis_llm() -> BaseChatModel:
    """Claude Sonnet — stronger model for Pattern Narrator / Hypothesis Surfacer."""
    from app.utils.config import get_settings
    settings = get_settings()

    if settings.llm_provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=settings.analysis_model or "gpt-4o",
            api_key=settings.openai_api_key or None,
        )

    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(
        model=settings.analysis_model or "claude-sonnet-4-5",
        api_key=settings.anthropic_api_key or None,
    )
