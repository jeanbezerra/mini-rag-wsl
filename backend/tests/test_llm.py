import json
from uuid import uuid4

import httpx
import pytest

from rag.config import Settings
from rag.llm import PROMPT_BYTE_BUDGET, Ollama, build_prompt


def sources(n=6):
    return [
        {
            "id": uuid4(),
            "document_id": uuid4(),
            "name": "Manual.pdf",
            "page": 4,
            "content": "Informação sobre reembolso de viagem. " * 60,
            "score": 0.02,
        }
        for _ in range(n)
    ]


def test_prompt_budget_sources_and_history():
    history = [{"role": "user", "content": "Pergunta anterior. " * 100}] * 20
    messages, used = build_prompt("Como pedir reembolso?", history, sources())
    assert sum(len(item["content"].encode()) for item in messages) <= PROMPT_BYTE_BUDGET
    assert len(messages) <= 6
    assert used and used[0]["id"] == "1"
    assert "[1] Manual.pdf (página 4)" in messages[-1]["content"]
    assert all(source["content"] in messages[-1]["content"] for source in used)
    assert "dados não confiáveis" in messages[0]["content"]


async def test_ollama_cpu_options_and_stream_contract():
    observed = {}

    def handle(request):
        observed.update(json.loads(request.content))
        return httpx.Response(
            200,
            text=(
                '{"message":{"content":"Olá"},"done":false}\n'
                '{"done":true,"eval_count":3,"total_duration":1000000}\n'
            ),
        )

    llm = Ollama(Settings(cpu_threads=2))
    await llm.client.aclose()
    llm.client = httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="http://ollama")
    events = [item async for item in llm.stream([{"role": "user", "content": "Oi"}])]
    await llm.close()
    assert observed["think"] is False
    assert observed["options"]["num_gpu"] == 0
    assert observed["options"]["num_thread"] == 2
    assert events[0] == {"type": "token", "content": "Olá"}
    assert events[-1]["type"] == "done" and events[-1]["tokens"] == 3


async def test_truncated_ollama_stream_is_error():
    llm = Ollama(Settings())
    await llm.client.aclose()
    llm.client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text="")),
        base_url="http://ollama",
    )
    with pytest.raises(RuntimeError, match="antes de concluir"):
        _ = [event async for event in llm.stream([])]
    await llm.close()
