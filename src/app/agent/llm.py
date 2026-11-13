from langchain_core.language_models import BaseChatModel

from app.config import settings


def get_chat_model() -> BaseChatModel:
    provider = settings.agent_provider.lower()

    if provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            temperature=settings.agent_temperature,
            num_ctx=settings.ollama_num_ctx,
        )

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required when AGENT_PROVIDER=anthropic")
        return ChatAnthropic(
            model=settings.agent_model,
            api_key=settings.anthropic_api_key,
            temperature=settings.agent_temperature,
        )

    raise ValueError(f"Unknown AGENT_PROVIDER: {settings.agent_provider}")