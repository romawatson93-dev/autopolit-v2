import pytest
import httpx

# Тест проверяет, что /healthz отвечает 200 и возвращает JSON с ключом 'status'
@pytest.mark.asyncio
async def test_healthz():
    async with httpx.AsyncClient(base_url="http://api:8000") as client:
        r = await client.get("/healthz", timeout=5.0)
        assert r.status_code == 200
        data = r.json()
        assert data.get("status") == "ok"
        # 'db' ключ может быть ok или fail, главное что эндпоинт жив
