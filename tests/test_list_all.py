"""workflows.list_all() reads every page.

``GET /portal`` is paged: 20 rows unless asked, never more than 100 (base-common SearchRequest), and
``workflows.list()`` returns one page. The examples presented that page as "all workflows". The
server here (pytest-httpx) has more rows than one page; two of them share a name across the page
boundary, and one comes back on two pages, as if a workflow was created while the pages were read.
"""

import pytest

from workstudio import AsyncClient, Client
from workstudio.exceptions import WorkStudioError

BASE = "http://ws.test"
PORTAL = f"{BASE}/api/v1/workflow/portal"


def _uuid(i: int) -> str:
    return f"00000000-0000-7000-8000-{i:012d}"


def rows(count: int) -> list[dict]:
    out = [
        {
            "id": _uuid(i),
            "globalUniqueId": _uuid(10_000 + i),
            "name": "Invoice sync" if i in (99, 100) else f"Automation {i:03d}",
            "endpoint": f"automation-{i}",
            "latestVersion": 1,
        }
        for i in range(count)
    ]
    out.insert(100, dict(out[99]))
    return out


def serve(httpx_mock, all_rows: list[dict], size: int = 100, search: str = None) -> int:
    pages = (len(all_rows) + size - 1) // size
    for p in range(pages):
        query = f"page={p}&size={size}" + (f"&search={search}" if search else "")
        httpx_mock.add_response(
            method="GET",
            url=f"{PORTAL}?{query}",
            json={
                "data": all_rows[p * size : (p + 1) * size],
                "pagination": {
                    "page": p,
                    "size": size,
                    "totalElements": len(all_rows),
                    "totalPages": pages,
                    "hasNext": p + 1 < pages,
                    "hasPrevious": p > 0,
                },
            },
        )
    return pages


@pytest.fixture
def client():
    c = Client(api_key="svx_tk_test", base_url=BASE)
    yield c
    c.close()


def _page_requests(httpx_mock) -> list[str]:
    return [str(r.url) for r in httpx_mock.get_requests() if r.url.path.endswith("/portal")]


class TestListAll:
    def test_every_page_once_ties_kept_repeat_dropped(self, client, httpx_mock):
        pages = serve(httpx_mock, rows(230))
        workflows = client.workflows.list_all()
        assert len(workflows) == 230
        assert len({str(w.id) for w in workflows}) == 230
        assert [str(w.id) for w in workflows if w.name == "Invoice sync"] == [_uuid(99), _uuid(100)]
        assert pages == 3
        assert _page_requests(httpx_mock) == [f"{PORTAL}?page={p}&size=100" for p in range(3)]

    def test_search_goes_on_every_page(self, client, httpx_mock):
        serve(httpx_mock, rows(150), search="invoice")
        assert len(client.workflows.list_all(search="invoice")) == 150
        assert all("search=invoice" in u for u in _page_requests(httpx_mock))

    def test_one_page_list_is_still_one_page(self, client, httpx_mock):
        httpx_mock.add_response(
            method="GET",
            url=f"{PORTAL}?page=0&size=20",
            json={
                "data": rows(230)[:20],
                "pagination": {"totalElements": 231, "totalPages": 12, "hasNext": True},
            },
        )
        workflows, info = client.workflows.list()
        assert len(workflows) == 20 and info.has_next

    def test_a_failed_page_raises(self, client, httpx_mock):
        all_rows = rows(230)
        httpx_mock.add_response(
            method="GET",
            url=f"{PORTAL}?page=0&size=100",
            json={"data": all_rows[:100], "pagination": {"totalPages": 3, "hasNext": True}},
        )
        httpx_mock.add_response(
            method="GET", url=f"{PORTAL}?page=1&size=100", status_code=500, json={}
        )
        with pytest.raises(WorkStudioError):
            client.workflows.list_all()


class TestAsyncListAll:
    async def test_every_page_once(self, httpx_mock):
        serve(httpx_mock, rows(230))
        async with AsyncClient(api_key="svx_tk_test", base_url=BASE) as client:
            workflows = await client.workflows.list_all()
        assert len(workflows) == 230
        assert len(_page_requests(httpx_mock)) == 3
