"""End-to-end tests through HTTP. Need the server extras:

uv sync --all-extras && uv run pytest
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient

from tech_amharic.domain import Role
from tech_amharic.records import read_dir
from tech_amharic.server.config import Settings
from tech_amharic.server.db import create_tables
from tech_amharic.server.main import create_app
from tech_amharic.server.security import create_user
from tech_amharic.server.services import import_records

pytestmark = pytest.mark.server
DATA = Path(__file__).resolve().parents[1] / "data" / "concepts"


class Ctx:
    client: TestClient
    tokens: dict[str, str]

    def auth(self, who: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens[who]}"}


@pytest.fixture
def ctx(tmp_path: Path) -> Iterator[Ctx]:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        secure_cookies=False,
        write_rate_per_minute=1000,
    )
    app = create_app(settings)
    db = app.state.db
    create_tables(db.engine)
    c = Ctx()
    c.tokens = {}
    with db.sessions() as session:
        import_records(session, read_dir(DATA))
        for handle, role in [
            ("ana", Role.CONTRIBUTOR),
            ("rev", Role.REVIEWER),
            ("rev2", Role.REVIEWER),
        ]:
            _, token = create_user(session, handle, role)
            c.tokens[handle] = token
        session.commit()
    with TestClient(app) as client:
        c.client = client
        yield c


# ---------------------------------------------------------------- reads


def test_health_and_stats(ctx: Ctx) -> None:
    assert ctx.client.get("/healthz").json() == {"status": "ok"}
    stats = ctx.client.get("/api/v1/stats").json()
    assert stats["concepts"] >= 100 and stats["published"] == 0 and stats["proposed"] > 100


def test_search_both_languages_and_homophones(ctx: Ctx) -> None:
    by_en = ctx.client.get("/api/v1/concepts", params={"q": "encryption"}).json()
    assert by_en[0]["slug"] == "encryption"  # exact match ranks first
    by_am = ctx.client.get("/api/v1/concepts", params={"q": "ምሥጠራ"}).json()  # ሠ for ሰ
    assert any(r["slug"] == "encryption" for r in by_am)
    by_domain = ctx.client.get("/api/v1/concepts", params={"domain": "security"}).json()
    assert by_domain and all(r["domain"] == "security" for r in by_domain)


def test_concept_detail_and_404(ctx: Ctx) -> None:
    body = ctx.client.get("/api/v1/concepts/kernel-os").json()
    assert {t["lang"] for t in body["terms"]} == {"en", "am"}
    assert ctx.client.get("/api/v1/concepts/nope").status_code == 404


# ---------------------------------------------------------------- writes


def test_writes_need_a_token(ctx: Ctx) -> None:
    r = ctx.client.post("/api/v1/concepts/encryption/terms", json={"lang": "am", "text": "መመስጠር"})
    assert r.status_code == 401


def test_full_review_flow(ctx: Ctx) -> None:
    c = ctx.client
    # Contributor proposes.
    r = c.post(
        "/api/v1/concepts/encryption/terms",
        json={"lang": "am", "text": "መመስጠር", "formation": "native"},
        headers=ctx.auth("ana"),
    )
    assert r.status_code == 201, r.text
    term_id = r.json()["id"]
    assert r.json()["status"] == "proposed"

    # Votes sort the queue but do not change status.
    assert c.put(
        f"/api/v1/terms/{term_id}/vote", json={"value": 1}, headers=ctx.auth("rev2")
    ).json() == {"score": 1}
    queue = c.get("/api/v1/review-queue").json()
    assert queue[0]["term_id"] == term_id

    # Contributor cannot approve; reviewer can.
    r = c.post(
        f"/api/v1/terms/{term_id}/reviews",
        json={"decision": "approve_preferred"},
        headers=ctx.auth("ana"),
    )
    assert r.status_code == 403 and r.json()["code"] == "not_reviewer"
    r = c.post(
        f"/api/v1/terms/{term_id}/reviews",
        json={"decision": "approve_preferred"},
        headers=ctx.auth("rev"),
    )
    assert r.status_code == 201 and r.json()["to_status"] == "preferred"

    # A second preferred term demotes the first to admitted.
    seed_term = next(
        t for t in c.get("/api/v1/concepts/encryption").json()["terms"] if t["text"] == "ምስጠራ"
    )
    r = c.post(
        f"/api/v1/terms/{seed_term['id']}/reviews",
        json={"decision": "approve_preferred"},
        headers=ctx.auth("rev"),
    )
    assert r.status_code == 201
    statuses = {
        t["text"]: t["status"] for t in c.get("/api/v1/concepts/encryption").json()["terms"]
    }
    assert statuses["ምስጠራ"] == "preferred" and statuses["መመስጠር"] == "admitted"

    # It is now published: export and bundle include the concept.
    bundle = c.get("/api/v1/bundle.json").json()
    assert [x["id"] for x in bundle["concepts"]] == ["encryption"]
    assert "preferredTerm-admn-sts" in c.get("/api/v1/export.tbx").text


def test_self_review_blocked(ctx: Ctx) -> None:
    r = ctx.client.post(
        "/api/v1/concepts/firewall/terms",
        json={"lang": "am", "text": "የኔትወርክ ኬላ"},
        headers=ctx.auth("rev"),
    )
    term_id = r.json()["id"]
    r = ctx.client.post(
        f"/api/v1/terms/{term_id}/reviews",
        json={"decision": "approve_admitted"},
        headers=ctx.auth("rev"),
    )
    assert r.status_code == 403 and r.json()["code"] == "self_review"


def test_request_changes_then_resubmit(ctx: Ctx) -> None:
    c = ctx.client
    term_id = c.post(
        "/api/v1/concepts/latency/terms",
        json={"lang": "am", "text": "ዝግታ"},
        headers=ctx.auth("ana"),
    ).json()["id"]
    r = c.post(
        f"/api/v1/terms/{term_id}/reviews",
        json={"decision": "request_changes"},
        headers=ctx.auth("rev"),
    )
    assert r.status_code == 422 and r.json()["code"] == "comment_required"
    r = c.post(
        f"/api/v1/terms/{term_id}/reviews",
        json={
            "decision": "request_changes",
            "comment": "Too close to 'slowness'; latency is a delay.",
        },
        headers=ctx.auth("rev"),
    )
    assert r.json()["to_status"] == "changes_requested"
    r = c.post(
        f"/api/v1/terms/{term_id}/resubmit", json={"text": "የምላሽ መዘግየት"}, headers=ctx.auth("ana")
    )
    assert (
        r.status_code == 200
        and r.json()["status"] == "proposed"
        and r.json()["text"] == "የምላሽ መዘግየት"
    )


def test_duplicate_and_wrong_script_rejected(ctx: Ctx) -> None:
    dup = ctx.client.post(
        "/api/v1/concepts/encryption/terms",
        json={"lang": "am", "text": "ምሥጠራ"},
        headers=ctx.auth("ana"),
    )
    assert dup.status_code == 409 and dup.json()["code"] == "duplicate_term"
    wrong = ctx.client.post(
        "/api/v1/concepts/encryption/terms",
        json={"lang": "am", "text": "encryption"},
        headers=ctx.auth("ana"),
    )
    assert wrong.status_code == 422 and wrong.json()["code"] == "script_mismatch"


def test_create_concept(ctx: Ctx) -> None:
    body = {
        "slug": "retrieval-augmented-generation",
        "domain": "ai-ml",
        "definition_en": "Answering with a language model grounded in retrieved documents.",
        "terms": [
            {"lang": "en", "text": "retrieval-augmented generation"},
            {"lang": "en", "text": "RAG", "formation": "abbreviation"},
            {"lang": "am", "text": "ሰነድ-ተኮር ምላሽ ማመንጨት", "formation": "phrase"},
        ],
    }
    r = ctx.client.post("/api/v1/concepts", json=body, headers=ctx.auth("ana"))
    assert r.status_code == 201, r.text
    statuses = [(t["text"], t["status"]) for t in r.json()["terms"]]
    assert statuses[0] == ("retrieval-augmented generation", "preferred")
    assert all(s == "proposed" for _, s in statuses[1:])
    again = ctx.client.post("/api/v1/concepts", json=body, headers=ctx.auth("ana"))
    assert again.status_code == 409


def test_bad_domain_and_bad_slug(ctx: Ctx) -> None:
    base = {"terms": [{"lang": "en", "text": "x"}]}
    r = ctx.client.post(
        "/api/v1/concepts",
        json={**base, "slug": "x", "domain": "blockchain"},
        headers=ctx.auth("ana"),
    )
    assert r.status_code == 422
    r = ctx.client.post(
        "/api/v1/concepts",
        json={**base, "slug": "Bad Slug", "domain": "general"},
        headers=ctx.auth("ana"),
    )
    assert r.status_code == 422


def test_audit_log_records_writes(ctx: Ctx) -> None:
    from sqlalchemy import func, select

    from tech_amharic.server.models import AuditEvent

    ctx.client.post(
        "/api/v1/concepts/latency/terms",
        json={"lang": "am", "text": "መቆየት"},
        headers=ctx.auth("ana"),
    )
    with ctx.client.app.state.db.sessions() as session:  # type: ignore[attr-defined]
        n = session.scalar(select(func.count()).where(AuditEvent.action == "term.propose"))
    assert n == 1


# ---------------------------------------------------------------- web


def test_web_pages_render(ctx: Ctx) -> None:
    home = ctx.client.get("/", params={"q": "ምስጠራ"})
    assert home.status_code == 200 and "encryption" in home.text
    page = ctx.client.get("/c/encryption")
    assert page.status_code == 200 and "ምስጠራ" in page.text
    assert ctx.client.get("/review").status_code == 200
    partial = ctx.client.get(
        "/", params={"q": "data"}, headers={"HX-Request": "true", "HX-Target": "results"}
    )
    assert "<html" not in partial.text


def test_web_login_and_cross_site_post_blocked(ctx: Ctx) -> None:
    r = ctx.client.post("/login", data={"token": ctx.tokens["rev"]}, follow_redirects=False)
    assert r.status_code == 303 and "tam_session" in r.headers["set-cookie"]
    evil = ctx.client.post(
        "/c/encryption/propose", data={"text": "ሀ"}, headers={"Origin": "https://evil.example"}
    )
    assert evil.status_code == 403


# ---------------------------------------------------------------- chat


def test_chat_grounds_answer_in_termbase(ctx: Ctx) -> None:
    calls: list[dict[str, object]] = []

    async def fake_ask(question, records, **kw):  # type: ignore[no-untyped-def]
        from tech_amharic import chat

        found = chat.retrieve(records, question)
        calls.append({"question": question, "found": [c["id"] for c in found], **kw})
        answer = "ምስጠራ (encryption) መረጃን ይጠብቃል።"
        return {
            "answer": answer,
            "concepts": [chat.concept_summary(c) for c in found],
            "checks": chat.check_answer(answer, found).__dict__,
            "model": kw["model"],
        }

    ctx.client.app.state.ask = fake_ask  # type: ignore[attr-defined]
    r = ctx.client.post("/api/v1/chat", json={"question": "ምስጠራ ምንድን ነው?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["concepts"][0]["id"] == "encryption"
    assert body["checks"]["terms_used"] == ["encryption"]
    assert calls[0]["found"] == ["encryption"]


def test_chat_validates_and_rate_limits(ctx: Ctx) -> None:
    async def fake_ask(question, records, **kw):  # type: ignore[no-untyped-def]
        return {
            "answer": "ሀ",
            "concepts": [],
            "checks": {"ethiopic_ratio": 1.0, "terms_used": [], "terms_missing": []},
            "model": "m",
        }

    app = ctx.client.app  # type: ignore[attr-defined]
    app.state.ask = fake_ask
    assert ctx.client.post("/api/v1/chat", json={"question": ""}).status_code == 422
    too_long = "ሀ" * 501
    assert ctx.client.post("/api/v1/chat", json={"question": too_long}).status_code == 422
    from tech_amharic.server.security import RateLimiter

    app.state.chat_limiter = RateLimiter(2)
    codes = [
        ctx.client.post("/api/v1/chat", json={"question": "ምንድን ነው?"}).status_code for _ in range(3)
    ]
    assert codes == [200, 200, 429]


def test_chat_reports_model_outage(ctx: Ctx) -> None:
    import httpx

    async def broken(question, records, **kw):  # type: ignore[no-untyped-def]
        raise httpx.ConnectError("down")

    ctx.client.app.state.ask = broken  # type: ignore[attr-defined]
    r = ctx.client.post("/api/v1/chat", json={"question": "What is a firewall?"})
    assert r.status_code == 502
