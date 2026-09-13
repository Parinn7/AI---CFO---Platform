"""Endpoint tests for PDF export of all three report types (task 8.4, FR-7.4):
GET /reports/{monthly,board,investor}/pdf.

**The property worth pinning hardest is that an export cannot say anything its
screen doesn't.** A report that leaves the building and disagrees with the
dashboard is the failure mode that gets discovered in a board meeting, so these
tests read the generated PDF's text back with `pypdf` and assert the figures in
it are *literally the strings the JSON sibling returned* — not that some bytes
came back, and not against hand-computed constants.

The second property is the one that breaks silently: the ₹ glyph. ReportLab's
built-in faces have no U+20B9, so a regression that stopped registering the
bundled DejaVu font would still produce a valid PDF — of black boxes. A test
asserts the rupee sign survives a render-and-read round trip.
"""

from collections.abc import AsyncGenerator
from io import BytesIO

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pypdf import PdfReader
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.reports import pdf
from app.transactions.categories import DEFAULT_CATEGORIES
from app.transactions.models import Category

from app.auth import models as _auth_models  # noqa: F401
from app.companies import models as _company_models  # noqa: F401
from app.financial_engine import models as _fin_models  # noqa: F401


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_factory() as session:
        session.add_all(
            [Category(company_id=None, name=n, type=t) for n, t in DEFAULT_CATEGORIES]
        )
        await session.commit()

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.clear()
    await engine.dispose()


async def _signup(client: AsyncClient, email: str) -> dict:
    token = (
        await client.post(
            "/api/v1/auth/signup",
            json={"email": email, "password": "sup3r-secret"},
        )
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def _company(client: AsyncClient, headers: dict, name: str = "Acme") -> str:
    return (
        await client.post(
            "/api/v1/companies", headers=headers, json={"name": name}
        )
    ).json()["id"]


async def _upload(client: AsyncClient, headers: dict, cid: str, csv: bytes) -> None:
    resp = await client.post(
        "/api/v1/uploads",
        headers=headers,
        data={"company_id": cid},
        files={"file": ("t.csv", csv, "text/csv")},
    )
    assert resp.status_code == 201


# Amounts chosen so Indian grouping is exercised (a lakh-scale figure groups as
# 1,20,000 rather than 120,000) and so July's totals differ from June's.
TWO_MONTHS = (
    b"date,amount,description,type\n"
    b"2026-06-05,200000,Client invoice,income\n"
    b"2026-06-07,90000,Salaries for June,expense\n"
    b"2026-06-10,30000,Office rent,expense\n"
    b"2026-07-05,300000,Client invoice,income\n"
    b"2026-07-07,150000,Salaries for July,expense\n"
    b"2026-07-10,30000,Office rent,expense\n"
    b"2026-07-20,20000,Google Ads campaign,expense\n"
)


def _text(body: bytes) -> str:
    """Every page of a generated PDF as one string.

    Newlines are stripped so an assertion about a figure isn't defeated by
    where the renderer happened to wrap a line.
    """
    reader = PdfReader(BytesIO(body))
    return " ".join(page.extract_text() for page in reader.pages).replace("\n", " ")


# --- The three exports -------------------------------------------------------


async def test_monthly_pdf_is_a_pdf_attachment_named_for_company_and_month(
    client: AsyncClient,
):
    headers = await _signup(client, "monthlypdf@example.com")
    cid = await _company(client, headers, "Northwind Analytics")
    await _upload(client, headers, cid, TWO_MONTHS)

    resp = await client.get(
        f"/api/v1/reports/monthly/pdf?company_id={cid}&month=2026-07", headers=headers
    )

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF")
    disposition = resp.headers["content-disposition"]
    assert disposition.startswith("attachment; ")
    # The filename is the only thing identifying the file once it's downloaded.
    assert "Northwind-Analytics-Monthly-Report-2026-07.pdf" in disposition


async def test_the_filename_header_is_readable_cross_origin(client: AsyncClient):
    """The frontend runs on :3000 and the API on :8000, so the download is a
    cross-origin request — and a browser hides every response header from the
    page unless the server exposes it. Without this the filename arrives and is
    unreadable, and every export saves under an invented name."""
    headers = await _signup(client, "cors@example.com")
    cid = await _company(client, headers, "Northwind Analytics")
    await _upload(client, headers, cid, TWO_MONTHS)

    resp = await client.get(
        f"/api/v1/reports/monthly/pdf?company_id={cid}&month=2026-07",
        headers={**headers, "Origin": "http://localhost:3000"},
    )

    assert resp.status_code == 200
    assert "Content-Disposition" in resp.headers["access-control-expose-headers"]


async def test_board_pdf_names_its_period(client: AsyncClient):
    headers = await _signup(client, "boardpdf@example.com")
    cid = await _company(client, headers, "Northwind Analytics")
    await _upload(client, headers, cid, TWO_MONTHS)

    resp = await client.get(
        f"/api/v1/reports/board/pdf?company_id={cid}&period=quarter&end_month=2026-07",
        headers=headers,
    )

    assert resp.status_code == 200, resp.text
    assert resp.content.startswith(b"%PDF")
    assert (
        "Northwind-Analytics-Board-Report-Quarter-2026-07.pdf"
        in resp.headers["content-disposition"]
    )
    assert "Board Report" in _text(resp.content)


async def test_investor_pdf_states_the_checks_and_their_thresholds(
    client: AsyncClient,
):
    """The checklist is the point of this document — the export has to carry
    the verdicts *and* the fixed rules behind them, not just the figures."""
    headers = await _signup(client, "investorpdf@example.com")
    cid = await _company(client, headers, "Northwind Analytics")
    await _upload(client, headers, cid, TWO_MONTHS)

    resp = await client.get(
        f"/api/v1/reports/investor/pdf?company_id={cid}&end_month=2026-07",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    text = _text(resp.content)

    summary = (
        await client.get(
            f"/api/v1/reports/investor?company_id={cid}&end_month=2026-07",
            headers=headers,
        )
    ).json()

    assert "Investor Readiness Summary" in text
    for check in summary["checks"]:
        assert check["label"] in text, check["label"]
        assert pdf.STATUS_LABELS[check["status"]] in text
    # The thresholds travel with the verdicts, so the PDF states the rule.
    assert "ready" in text and "attention" in text


# --- The export agrees with the screen ---------------------------------------


async def test_monthly_pdf_quotes_the_same_figures_as_the_json_report(
    client: AsyncClient,
):
    """The whole point of 8.4: the exported copy and the screen it came from are
    the same report. Both are asserted as the *same formatted strings*, so a
    renderer that rounded or re-derived anything would fail here."""
    headers = await _signup(client, "agree@example.com")
    cid = await _company(client, headers, "Northwind Analytics")
    await _upload(client, headers, cid, TWO_MONTHS)

    report = (
        await client.get(
            f"/api/v1/reports/monthly?company_id={cid}&month=2026-07", headers=headers
        )
    ).json()
    resp = await client.get(
        f"/api/v1/reports/monthly/pdf?company_id={cid}&month=2026-07", headers=headers
    )
    text = _text(resp.content)

    from app.core.formatting import format_inr

    kpis = report["kpis"]
    # Revenue ₹3,00,000.00 and expenses ₹2,00,000.00, exactly as the API states
    # them — rendered through the same formatter the dashboard mirrors.
    assert format_inr(kpis["total_revenue"]) in text
    assert format_inr(kpis["total_expenses"]) in text
    assert format_inr(report["closing_cash"]) in text
    assert report["company"]["name"] in text
    # Every category line in the breakdown appears with its exact total.
    for line in report["categories"]:
        assert line["name"] in text
        assert format_inr(line["total"]) in text


async def test_board_pdf_quotes_the_same_figures_as_the_json_report(
    client: AsyncClient,
):
    headers = await _signup(client, "boardagree@example.com")
    cid = await _company(client, headers, "Northwind Analytics")
    await _upload(client, headers, cid, TWO_MONTHS)

    query = f"company_id={cid}&period=quarter&end_month=2026-07"
    report = (
        await client.get(f"/api/v1/reports/board?{query}", headers=headers)
    ).json()
    text = _text(
        (await client.get(f"/api/v1/reports/board/pdf?{query}", headers=headers)).content
    )

    from app.core.formatting import format_inr

    assert format_inr(report["current"]["kpis"]["total_revenue"]) in text
    assert format_inr(report["current"]["kpis"]["total_expenses"]) in text
    assert format_inr(report["cash"]["opening_cash"]) in text
    assert format_inr(report["cash"]["closing_cash"]) in text


# --- Undefined metrics are not printed as zero -------------------------------


async def test_undefined_metrics_render_as_a_dash_not_a_zero(client: AsyncClient):
    """The engine returns null for genuinely undefined KPIs — runway when the
    company isn't burning cash. Printing that as "0.0 months" in a document an
    investor reads would be asserting something false."""
    headers = await _signup(client, "undefined@example.com")
    cid = await _company(client, headers, "Northwind Analytics")
    await _upload(client, headers, cid, TWO_MONTHS)

    report = (
        await client.get(
            f"/api/v1/reports/monthly?company_id={cid}&month=2026-07", headers=headers
        )
    ).json()
    assert report["kpis"]["runway_months"] is None  # a surplus month

    text = _text(
        (
            await client.get(
                f"/api/v1/reports/monthly/pdf?company_id={cid}&month=2026-07",
                headers=headers,
            )
        ).content
    )
    assert "Not burning cash" in text
    assert "0.0 months" not in text


async def test_a_negative_burn_rate_is_stated_as_a_surplus(client: AsyncClient):
    """July is a surplus month, so the stored `burn_rate` is negative. Printing
    it raw under the word "outflow" is arithmetically true and reads as a loss —
    and the dashboard's `KpiCards` flips the sign and the label, so an export
    that didn't would contradict the tile beside it."""
    headers = await _signup(client, "surplus@example.com")
    cid = await _company(client, headers, "Northwind Analytics")
    await _upload(client, headers, cid, TWO_MONTHS)

    report = (
        await client.get(
            f"/api/v1/reports/monthly?company_id={cid}&month=2026-07", headers=headers
        )
    ).json()
    assert float(report["kpis"]["burn_rate"]) < 0  # a surplus

    text = _text(
        (
            await client.get(
                f"/api/v1/reports/monthly/pdf?company_id={cid}&month=2026-07",
                headers=headers,
            )
        ).content
    )
    assert "net monthly cash surplus" in text
    assert "net monthly cash burn" not in text
    assert "+₹1,00,000.00/mo" in text  # the magnitude, signed as an inflow


# --- The rupee glyph ---------------------------------------------------------


async def test_the_rupee_sign_survives_a_render(client: AsyncClient):
    """ReportLab's built-in faces have no U+20B9. A regression that stopped
    registering the bundled DejaVu font would still emit a valid PDF — full of
    black boxes where every amount should be — so this is asserted directly
    rather than inferred from the file parsing."""
    headers = await _signup(client, "rupee@example.com")
    cid = await _company(client, headers, "Northwind Analytics")
    await _upload(client, headers, cid, TWO_MONTHS)

    text = _text(
        (
            await client.get(
                f"/api/v1/reports/monthly/pdf?company_id={cid}&month=2026-07",
                headers=headers,
            )
        ).content
    )
    assert "₹" in text
    assert "₹3,00,000.00" in text  # Indian grouping, not 300,000.00


# --- Access, arguments and empty companies -----------------------------------


@pytest.mark.parametrize("path", ["monthly", "board", "investor"])
async def test_export_requires_authentication(client: AsyncClient, path: str):
    headers = await _signup(client, f"auth-{path}@example.com")
    cid = await _company(client, headers)
    resp = await client.get(f"/api/v1/reports/{path}/pdf?company_id={cid}")
    assert resp.status_code == 401


@pytest.mark.parametrize("path", ["monthly", "board", "investor"])
async def test_another_users_company_is_not_exportable(
    client: AsyncClient, path: str
):
    """404 rather than 403 — an export must not confirm a company id exists,
    the same rule the JSON routes follow."""
    owner = await _signup(client, f"owner-{path}@example.com")
    cid = await _company(client, owner, "Northwind Analytics")
    await _upload(client, owner, cid, TWO_MONTHS)

    stranger = await _signup(client, f"stranger-{path}@example.com")
    resp = await client.get(
        f"/api/v1/reports/{path}/pdf?company_id={cid}", headers=stranger
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Company not found."


@pytest.mark.parametrize("path", ["monthly", "board", "investor"])
async def test_a_company_with_no_data_is_a_404_with_the_same_message(
    client: AsyncClient, path: str
):
    """An export and its JSON sibling must describe an empty company
    identically — two different messages for one condition is how a UI ends up
    saying different things on the same screen."""
    headers = await _signup(client, f"empty-{path}@example.com")
    cid = await _company(client, headers)

    exported = await client.get(
        f"/api/v1/reports/{path}/pdf?company_id={cid}", headers=headers
    )
    on_screen = await client.get(
        f"/api/v1/reports/{path}?company_id={cid}", headers=headers
    )

    assert exported.status_code == on_screen.status_code == 404
    assert exported.json()["detail"] == on_screen.json()["detail"]
    assert "No financial data yet" in exported.json()["detail"]


@pytest.mark.parametrize(
    "path,param", [("monthly", "month"), ("board", "end_month"), ("investor", "end_month")]
)
async def test_a_malformed_month_is_a_400(client: AsyncClient, path: str, param: str):
    headers = await _signup(client, f"badmonth-{path}@example.com")
    cid = await _company(client, headers)
    resp = await client.get(
        f"/api/v1/reports/{path}/pdf?company_id={cid}&{param}=July-2026", headers=headers
    )
    assert resp.status_code == 400
    assert "YYYY-MM" in resp.json()["detail"]


async def test_an_unknown_board_period_is_a_422(client: AsyncClient):
    headers = await _signup(client, "badperiod@example.com")
    cid = await _company(client, headers)
    resp = await client.get(
        f"/api/v1/reports/board/pdf?company_id={cid}&period=fortnight", headers=headers
    )
    assert resp.status_code == 422


async def test_exporting_twice_produces_the_same_report(client: AsyncClient):
    """Nothing is stored, so an export is a pure function of the data — and a
    second one has to describe the same month rather than a new record of
    someone having looked at a screen."""
    headers = await _signup(client, "twice@example.com")
    cid = await _company(client, headers, "Northwind Analytics")
    await _upload(client, headers, cid, TWO_MONTHS)

    url = f"/api/v1/reports/monthly/pdf?company_id={cid}&month=2026-07"
    first = await client.get(url, headers=headers)
    second = await client.get(url, headers=headers)

    assert first.status_code == second.status_code == 200
    assert first.headers["content-disposition"] == second.headers["content-disposition"]
    # Byte-identical isn't asserted: a PDF embeds its creation timestamp. The
    # figures are what has to match.
    assert _text(first.content) == _text(second.content)


# --- Unit: filenames and escaping --------------------------------------------


def test_company_names_survive_becoming_filenames():
    """Company names are user-typed. A slash or a quote in a
    `Content-Disposition` filename is a malformed header, not a quirk."""
    assert pdf._slug("Northwind Analytics") == "Northwind-Analytics"
    assert pdf._slug('Acme "Pvt" Ltd./India') == "Acme-Pvt-Ltd-India"
    assert pdf._slug("   ") == "company"  # never an empty or leading-dash name
    assert pdf._slug("नॉर्थविंड") == "company"  # nothing Latin survives
    assert len(pdf._slug("x" * 200)) == 60


def test_ampersands_in_user_text_do_not_break_a_render():
    """ReportLab paragraphs take mini-HTML, so an unescaped '&' raises
    mid-render — meaning a category called "R&D" would make export fail for
    that company and no other."""
    assert pdf._esc("R&D") == "R&amp;D"
    assert pdf._esc("<script>") == "&lt;script&gt;"


async def test_a_company_named_with_markup_still_exports(client: AsyncClient):
    headers = await _signup(client, "markup@example.com")
    cid = await _company(client, headers, "R&D <Holdings> Pvt Ltd")
    await _upload(client, headers, cid, TWO_MONTHS)

    resp = await client.get(
        f"/api/v1/reports/monthly/pdf?company_id={cid}&month=2026-07", headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert "R-D-Holdings-Pvt-Ltd-Monthly-Report" in resp.headers["content-disposition"]
    # The name is drawn as typed, not as escaped markup.
    assert "R&D <Holdings> Pvt Ltd" in _text(resp.content)
