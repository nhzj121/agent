"""Composition adapter around HelloAgents configuration and its shared OpenAI client."""
import httpx
import openai
from services.execution_control import current_execution, checkpoint


class ProjectLLM:
    def __init__(self, llm, config):
        self._llm, self.config = llm, config

    def __getattr__(self, name):
        return getattr(self._llm, name)

    def _request(self, messages, stream, kwargs):
        control = current_execution()
        for attempt in range(self.config.model_max_retries + 1):
            checkpoint()
            remaining = control.remaining() if control else float("inf")
            timeout = httpx.Timeout(
                connect=min(self.config.model_connect_timeout, remaining),
                read=min(self.config.model_read_timeout, remaining),
                write=min(self.config.model_read_timeout, remaining),
                pool=min(self.config.model_connect_timeout, remaining))
            # with_options shares the HTTP connection pool; never close this view/client.
            client = self._llm._client.with_options(max_retries=0, timeout=timeout)
            try:
                return client.chat.completions.create(
                    model=self._llm.model, messages=messages, stream=stream,
                    temperature=kwargs.get("temperature", self._llm.temperature),
                    max_tokens=kwargs.get("max_tokens", self._llm.max_tokens),
                    **{k:v for k,v in kwargs.items()
                       if k not in ("temperature", "max_tokens", "timeout", "stream")})
            except (openai.APIConnectionError, openai.APIStatusError) as exc:
                checkpoint()
                retryable = isinstance(exc, openai.APIConnectionError) or (
                    exc.status_code in (408,409,429) or exc.status_code >= 500)
                if not retryable or attempt == self.config.model_max_retries:
                    raise
                delay = min(.1 * (2 ** attempt), 1.)
                if control:
                    control.wait_retry(delay)
                else:
                    # Project Agents always bind a context; retain bounded direct use.
                    import time
                    time.sleep(delay)

    def invoke(self, messages, **kwargs):
        checkpoint()
        if not hasattr(self._llm, "_client"):
            result = self._llm.invoke(messages, **kwargs)  # injectable Fake protocol
        else:
            result = self._request(messages, False, kwargs).choices[0].message.content or ""
        checkpoint()
        return result

    def stream_invoke(self, messages, **kwargs):
        checkpoint()
        control = current_execution()
        response = None
        try:
            if not hasattr(self._llm, "_client"):
                response = self._llm.stream_invoke(messages, **kwargs)
            else:
                response = self._request(messages, True, kwargs)
            if control:
                control.own_stream(response)
            # Retry creation only. Never replay a partially emitted stream.
            for chunk in response:
                checkpoint()
                if isinstance(chunk, str):
                    content = chunk
                else:
                    content = chunk.choices[0].delta.content if chunk.choices else None
                if content:
                    yield content
            checkpoint()
        finally:
            if response is not None:
                try:
                    close = getattr(response, "close", None)
                    if close:
                        close()
                finally:
                    if control:
                        control.disown_stream(response)

    def think(self, messages, temperature=None):
        kwargs = {} if temperature is None else {"temperature":temperature}
        yield from self.stream_invoke(messages, **kwargs)
