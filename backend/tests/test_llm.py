import json
from uuid import uuid4

import httpx
import pytest

from rag.config import Settings
from rag.llm import PROMPT_BYTE_BUDGET, TEMPLATE_TOKEN_RESERVE, Ollama, build_prompt


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


@pytest.mark.parametrize("context,output", [(4096, 512), (4600, 2048), (16384, 2048)])
def test_configured_prompt_reserves_output_and_template_with_unicode(context, output):
    documents = [
        {**source, "name": "文档📚" * 100, "content": "🚀 política 漢字 " * 1000}
        for source in sources(12)
    ]
    messages, used = build_prompt(
        "🚀漢字" * 500,
        [{"role": "user", "content": "🌱漢字" * 500}] * 20,
        documents,
        context_tokens=context,
        max_output_tokens=output,
    )
    byte_count = sum(len(item["content"].encode("utf-8")) for item in messages)
    assert byte_count + output + TEMPLATE_TOKEN_RESERVE <= context
    assert used and all(source["content"] in messages[-1]["content"] for source in used)


async def test_models_only_exposes_local_tag_metadata():
    llm = Ollama(Settings())
    await llm.client.aclose()

    def handle(request):
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["completion"]})
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "name": "qwen3:1b",
                        "size": 1234,
                        "digest": "private",
                        "details": {
                            "parameter_size": "1B",
                            "quantization_level": "Q4_K_M",
                        },
                    }
                ]
            },
        )

    llm.client = httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="http://ollama")
    try:
        assert await llm.models() == [
            {
                "name": "qwen3:1b",
                "size_bytes": 1234,
                "parameter_size": "1B",
                "quantization_level": "Q4_K_M",
            }
        ]
    finally:
        await llm.close()


async def test_model_picker_filters_embedding_and_cloud_and_revalidates_changed_digest():
    shows = []
    digest = "v1"

    def handle(request):
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"name": name, "digest": digest} for name in ("local", "embedding", "cloud")
                    ]
                },
            )
        name = json.loads(request.content)["model"]
        shows.append(name)
        return httpx.Response(
            200,
            json={
                "capabilities": ["embedding"] if name == "embedding" else ["completion"],
                "remote_model": "huge:cloud" if name == "cloud" else "",
            },
        )

    llm = Ollama(Settings())
    await llm.client.aclose()
    llm.client = httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="http://ollama")
    try:
        assert [model["name"] for model in await llm.models()] == ["local"]
        assert len(shows) == 3
        await llm.models()
        assert len(shows) == 3  # No repeated metadata work on unchanged local tags.
        assert await llm.selectable_model("local")
        assert len(shows) == 4  # A model change bypasses the read cache.
        assert not await llm.selectable_model("embedding")
        assert not await llm.selectable_model("cloud")
        assert not await llm.selectable_model("not-installed")
        digest = "v2"
        await llm.models()
        assert len(shows) == 9
        # Health only checks the selected local tag, without metadata requests.
        llm.settings = llm.settings.model_copy(update={"ollama_model": "local"})
        assert (await llm.health())["status"] == "ready"
        assert len(shows) == 9
    finally:
        await llm.close()


async def test_changed_generation_options_reach_ollama():
    settings = Settings(
        temperature=0.4,
        top_p=0.7,
        repeat_penalty=1.2,
        max_output_tokens=1024,
        context_tokens=8192,
        generation_batch_size=64,
        keep_alive_minutes=0,
        generation_timeout_seconds=1000,
        cpu_threads=3,
    )
    llm = Ollama(settings)
    await llm.client.aclose()
    observed = {}

    def handle(request):
        observed.update(json.loads(request.content))
        observed["timeout"] = request.extensions["timeout"]
        return httpx.Response(200, text='{"done":true}\n')

    llm.client = httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="http://ollama")
    try:
        _ = [item async for item in llm.stream([])]
        assert observed["options"] == {
            "num_gpu": 0,
            "num_thread": 3,
            "num_ctx": 8192,
            "num_predict": 1024,
            "temperature": 0.4,
            "top_p": 0.7,
            "repeat_penalty": 1.2,
            "num_batch": 64,
        }
        assert observed["keep_alive"] == "0m" and observed["timeout"]["read"] == 1000
    finally:
        await llm.close()
