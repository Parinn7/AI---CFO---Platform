"""Unit tests for CSV/XLSX parsing + column mapping (task 3.2) — no DB needed."""

import datetime as dt
import io
from decimal import Decimal

import pytest

from app.transactions.parsing import UploadParseError, parse_upload


def _csv(text: str) -> bytes:
    return text.encode("utf-8")


def test_parses_basic_csv_with_aliased_headers():
    content = _csv(
        "Transaction Date,Narration,Amount (INR),Category,Type\n"
        "2026-01-05,Client invoice,\"1,20,000\",Revenue,income\n"
        "05/01/2026,Office rent,-25000,Rent,expense\n"
    )
    parsed = parse_upload("jan.csv", content)
    assert parsed.errors == []
    assert len(parsed.rows) == 2

    r0 = parsed.rows[0]
    assert r0.date == dt.date(2026, 1, 5)
    assert r0.amount == Decimal("120000")
    assert r0.description == "Client invoice"
    assert r0.category_name == "Revenue"
    assert r0.explicit_type == "income"

    r1 = parsed.rows[1]
    assert r1.date == dt.date(2026, 1, 5)
    assert r1.amount == Decimal("-25000")
    assert r1.explicit_type == "expense"


def test_skips_bad_rows_but_keeps_good_ones():
    content = _csv(
        "date,amount,description\n"
        "2026-02-01,1000,ok\n"
        ",500,missing date\n"
        "2026-02-03,notanumber,bad amount\n"
        "2026-02-04,750,also ok\n"
    )
    parsed = parse_upload("f.csv", content)
    assert len(parsed.rows) == 2
    assert len(parsed.errors) == 2
    assert any("date" in e for e in parsed.errors)
    assert any("amount" in e for e in parsed.errors)


def test_direction_words_normalise_to_type():
    content = _csv(
        "date,amount,type\n"
        "2026-01-01,100,Credit\n"
        "2026-01-02,200,DR\n"
        "2026-01-03,300,weird\n"
    )
    parsed = parse_upload("f.csv", content)
    assert [r.explicit_type for r in parsed.rows] == ["income", "expense", None]


def test_unsupported_extension_raises():
    with pytest.raises(UploadParseError):
        parse_upload("data.txt", b"whatever")


def test_missing_required_columns_raises():
    with pytest.raises(UploadParseError):
        parse_upload("f.csv", _csv("name,notes\nfoo,bar\n"))


def test_empty_file_raises():
    with pytest.raises(UploadParseError):
        parse_upload("f.csv", _csv("\n\n"))


def test_parses_xlsx():
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Date", "Amount", "Description"])
    ws.append([dt.date(2026, 3, 1), 4200, "Consulting"])
    ws.append(["2026-03-02", "-900", "Domain renewal"])
    buf = io.BytesIO()
    wb.save(buf)

    parsed = parse_upload("book.xlsx", buf.getvalue())
    assert len(parsed.rows) == 2
    assert parsed.rows[0].date == dt.date(2026, 3, 1)
    assert parsed.rows[0].amount == Decimal("4200")
    assert parsed.rows[1].amount == Decimal("-900")


def test_parenthesised_amount_is_negative():
    parsed = parse_upload("f.csv", _csv("date,amount\n2026-01-01,(1500)\n"))
    assert parsed.rows[0].amount == Decimal("-1500")
