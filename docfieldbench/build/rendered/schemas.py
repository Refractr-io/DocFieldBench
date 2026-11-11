"""One hand-written schema per rendered family, with the match kind per field."""
from __future__ import annotations

from ..families import INVOICE_MATCH, INVOICE_SCHEMA, LINE_ITEM_MATCH, _d, _n, _obj, _s


def _i():
    return {"type": ["integer", "null"]}


def _arr(props):
    return {"type": ["array", "null"], "items": _obj(props)}


_ADDR = {"street": _s(), "postcode": _s(), "city": _s()}
_ADDR_M = {"street": "short_text", "postcode": "id", "city": "short_text"}


def _prefixed(prefix, m):
    return {f"/{prefix}/{k}": v for k, v in m.items()}


SCHEMAS = {
    "invoice": (INVOICE_SCHEMA, INVOICE_MATCH, {"/line_items": LINE_ITEM_MATCH}),
    "receipt": (
        _obj({"merchant": _obj({"name": _s(), **_ADDR, "vat_id": _s(), "phone": _s()}), "receipt_number": _s(),
              "date": _d(), "payment_method": _s(), "card_last4": _s(), "subtotal": _n(), "tax_total": _n(),
              "tip": _n(), "total": _n(),
              "line_items": _arr({"description": _s(), "quantity": _n(), "unit_price": _n(), "line_total": _n()})}),
        {"/merchant/name": "name", **_prefixed("merchant", _ADDR_M), "/merchant/vat_id": "id", "/merchant/phone": "id",
         "/receipt_number": "id", "/date": "date", "/payment_method": "short_text", "/card_last4": "id",
         "/subtotal": "amount", "/tax_total": "amount", "/tip": "amount", "/total": "amount"},
        {"/line_items": LINE_ITEM_MATCH}),
    "bank_statement": (
        _obj({"bank_name": _s(), "account_holder": _s(), "iban": _s(), "bic": _s(), "account_number": _s(),
              "statement_number": _s(), "period_start": _d(), "period_end": _d(), "opening_balance": _n(),
              "closing_balance": _n(), "transactions": _arr({"date": _d(), "description": _s(), "amount": _n()})}),
        {"/bank_name": "name", "/account_holder": "name", "/iban": "id", "/bic": "id", "/account_number": "id",
         "/statement_number": "id", "/period_start": "date", "/period_end": "date", "/opening_balance": "amount",
         "/closing_balance": "amount"},
        {"/transactions": {"date": "date", "description": "short_text", "amount": "amount"}}),
    "account_statement": (
        _obj({"supplier": _obj({"name": _s(), **_ADDR}), "customer": _obj({"name": _s(), "customer_number": _s()}),
              "statement_date": _d(), "opening_balance": _n(), "closing_balance": _n(), "due_date": _d(),
              "entries": _arr({"date": _d(), "reference": _s(), "description": _s(), "amount": _n()})}),
        {"/supplier/name": "name", **_prefixed("supplier", _ADDR_M), "/customer/name": "name",
         "/customer/customer_number": "id", "/statement_date": "date", "/opening_balance": "amount",
         "/closing_balance": "amount", "/due_date": "date"},
        {"/entries": {"date": "date", "reference": "id", "description": "short_text", "amount": "amount"}}),
    "delivery_note": (
        _obj({"delivery_note_number": _s(), "delivery_date": _d(), "order_number": _s(), "customer_number": _s(),
              "shipper": _obj({"name": _s(), **_ADDR}), "recipient": _obj({"name": _s(), **_ADDR}),
              "carrier": _s(), "tracking_number": _s(), "package_count": _i(), "gross_weight": _n(),
              "line_items": _arr({"article_number": _s(), "description": _s(), "quantity": _n()})}),
        {"/delivery_note_number": "id", "/delivery_date": "date", "/order_number": "id", "/customer_number": "id",
         "/shipper/name": "name", **_prefixed("shipper", _ADDR_M), "/recipient/name": "name",
         **_prefixed("recipient", _ADDR_M), "/carrier": "name", "/tracking_number": "id", "/package_count": "integer",
         "/gross_weight": "number"},
        {"/line_items": {"article_number": "id", "description": "short_text", "quantity": "number"}}),
    "payslip": (
        _obj({"employer": _obj({"name": _s(), **_ADDR}), "employee": _obj({"name": _s(), "employee_id": _s()}),
              "pay_period_start": _d(), "pay_period_end": _d(), "pay_date": _d(), "gross_pay": _n(),
              "total_deductions": _n(), "net_pay": _n(), "iban": _s(),
              "earnings": _arr({"description": _s(), "amount": _n()}),
              "deductions": _arr({"description": _s(), "amount": _n()})}),
        {"/employer/name": "name", **_prefixed("employer", _ADDR_M), "/employee/name": "name",
         "/employee/employee_id": "id", "/pay_period_start": "date", "/pay_period_end": "date", "/pay_date": "date",
         "/gross_pay": "amount", "/total_deductions": "amount", "/net_pay": "amount", "/iban": "id"},
        {"/earnings": {"description": "short_text", "amount": "amount"},
         "/deductions": {"description": "short_text", "amount": "amount"}}),
}
