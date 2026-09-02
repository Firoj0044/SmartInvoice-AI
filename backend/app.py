"""
SmartInvoice AI - Backend
==========================
A production-ready Flask app for AI-powered invoicing.

Features:
  - Client management (CRUD)
  - Invoice management with line items, tax, multi-currency
  - AI natural language -> structured invoice
  - AI receipt scanning (image -> items, vendor, amount, category)
  - AI auto-categorization of expenses
  - Payment tracking (draft, sent, paid, overdue)
  - Analytics dashboard
  - Receipt storage
  - Full bilingual support (Bangla + English)

Run:  python app.py
"""

import base64
import json
import os
import re
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

# ---- Paths ----
ROOT = Path(__file__).resolve().parent.parent  # backend/ -> project root
load_dotenv(ROOT / "backend" / ".env")
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "smartinvoice.db"
UPLOADS_DIR = DATA_DIR / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)
FRONTEND_DIR = ROOT / "frontend"
LANDING_DIR = ROOT / "landing"

OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODEL = os.getenv(
    "OPENROUTER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free"
).strip()

# Fallback chain for AI (free models)
AI_MODELS = [
    OPENROUTER_MODEL,
    "qwen/qwen-2.5-72b-instruct:free",
    "google/gemma-3-27b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "mistralai/mistral-small-3.2-24b-instruct:free",
]

app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")
CORS(app)

CATEGORIES = [
    "Food & Dining", "Travel", "Office Supplies", "Software & Subscriptions",
    "Marketing", "Professional Services", "Equipment", "Utilities",
    "Rent & Lease", "Other"
]


# ========== Database ==========
def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS clients (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT,
            phone TEXT,
            company TEXT,
            address TEXT,
            currency TEXT DEFAULT 'USD',
            language TEXT DEFAULT 'en',
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS invoices (
            id TEXT PRIMARY KEY,
            client_id TEXT,
            invoice_number TEXT UNIQUE,
            issue_date TEXT,
            due_date TEXT,
            line_items TEXT,
            subtotal REAL,
            tax_rate REAL,
            tax_amount REAL,
            total REAL,
            currency TEXT DEFAULT 'USD',
            notes TEXT,
            status TEXT DEFAULT 'draft',
            language TEXT DEFAULT 'en',
            created_at REAL NOT NULL,
            FOREIGN KEY (client_id) REFERENCES clients(id)
        );
        CREATE TABLE IF NOT EXISTS receipts (
            id TEXT PRIMARY KEY,
            image_path TEXT,
            vendor TEXT,
            amount REAL,
            currency TEXT,
            date TEXT,
            category TEXT,
            items TEXT,
            raw_text TEXT,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS expenses (
            id TEXT PRIMARY KEY,
            receipt_id TEXT,
            category TEXT,
            amount REAL,
            currency TEXT,
            description TEXT,
            date TEXT,
            client_id TEXT,
            created_at REAL NOT NULL
        );
    """)
    conn.commit()
    conn.close()


init_db()


# ========== AI: Core ==========
def ai_call(system_prompt: str, user_prompt: str, max_tokens: int = 800, temperature: float = 0.1) -> str:
    """Call OpenRouter with retry through fallback models. Returns raw text or None."""
    if not OPENROUTER_KEY:
        return None

    for model in AI_MODELS:
        try:
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
                timeout=30,
            )
            if r.status_code != 200:
                print(f"[ai] {model} -> {r.status_code}, trying next")
                continue
            content = r.json()["choices"][0]["message"]["content"].strip()
            if content:
                return content
        except Exception as exc:
            print(f"[ai] {model} error: {exc}")
            continue
    return None


def ai_parse_json(text: str) -> dict:
    """Parse AI response, stripping markdown code fences if present."""
    if not text:
        return {}
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```", 2)
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
    text = text.strip()
    # Find first { and last } to handle surrounding text
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end+1]
    try:
        return json.loads(text)
    except Exception as exc:
        print(f"[ai] JSON parse error: {exc}, text was: {text[:200]}")
        return {}


# ========== AI: Generate Invoice from text ==========
def ai_generate_invoice(prompt: str, language: str = "en") -> dict:
    """Convert a natural language description into a structured invoice."""
    if language == "bn":
        note_hint = "Write the notes in Bangla (বাংলা)."
    else:
        note_hint = "Write the notes in English."

    system_prompt = f"""You are SmartInvoice AI. Convert a natural-language description into a structured invoice.

EXAMPLE INPUT: "logo design $500, 2 hours consulting at $80/hr, 5% tax, due in 14 days"
EXAMPLE OUTPUT:
{{"line_items":[{{"description":"Logo design","quantity":1,"unit_price":500}},{{"description":"Consulting (2 hrs)","quantity":2,"unit_price":80}}],"tax_rate":0.05,"currency":"USD","due_days":14,"notes":"Thank you for your business!"}}

RULES:
- Extract EACH item as a separate line item. Don't merge them.
- quantity is how many units (hours, pieces, etc).
- unit_price is price per unit in the currency given.
- tax_rate is a decimal: 0.05 = 5%, 0.15 = 15%. Default 0 if not mentioned.
- currency: USD, EUR, GBP, BDT, INR, JPY, AUD, CAD. Default USD if not specified.
- due_days: how many days until payment. Default 30.
- {note_hint}

Return ONLY the JSON object. No markdown, no explanation."""

    raw = ai_call(system_prompt, prompt, max_tokens=600)
    result = ai_parse_json(raw) if raw else {}

    # Validate we got real line items (not just one with default values)
    items = result.get("line_items") or []
    if not items:
        # Build a fallback single-line invoice
        return {
            "line_items": [{
                "description": prompt[:80] if language == "en" else "সেবা",
                "quantity": 1,
                "unit_price": 100.0,
            }],
            "tax_rate": 0.0,
            "currency": "USD",
            "due_days": 30,
            "notes": "ধন্যবাদ!" if language == "bn" else "Thank you!",
            "ai_generated": False,
        }
    return {
        "line_items": items,
        "tax_rate": float(result.get("tax_rate", 0)),
        "currency": result.get("currency", "USD").upper(),
        "due_days": int(result.get("due_days", 30)),
        "notes": result.get("notes", "ধন্যবাদ!" if language == "bn" else "Thank you!"),
        "ai_generated": True,
    }


# ========== AI: Scan receipt image ==========
def ai_scan_receipt(image_b64: str, mime_type: str = "image/jpeg", language: str = "en") -> dict:
    """Analyze a receipt image and extract structured data."""
    system_prompt = f"""You are SmartInvoice AI's receipt scanner. Analyze this receipt image and extract structured data.

Return ONLY this JSON:
{{
  "vendor": "Store/Company name",
  "amount": 0.00,
  "currency": "USD",
  "date": "YYYY-MM-DD",
  "category": "one of: {', '.join(CATEGORIES)}",
  "items": [{{"description": "item name", "quantity": 1, "unit_price": 0.00}}],
  "raw_text": "brief description of the receipt"
}}

RULES:
- vendor: business name from the receipt
- amount: TOTAL amount (number only, no currency symbol)
- currency: USD, EUR, GBP, BDT, INR, JPY, etc. from the receipt
- date: purchase date in YYYY-MM-DD format
- category: pick the most fitting from the list
- items: individual line items with quantity and price
- raw_text: 1-sentence description of what the receipt is for

If you can't read certain values, make reasonable guesses based on context. If amount is unclear, estimate from items."""

    models_with_vision = [m for m in AI_MODELS if "vision" in m or "gpt-4o" in m or "claude" in m]
    # Try vision models first, fall back to text-only
    for model in (models_with_vision + AI_MODELS):
        try:
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": [
                            {"type": "text", "text": "Extract data from this receipt:"},
                            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_b64}"}}
                        ]},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 800,
                },
                timeout=45,
            )
            if r.status_code != 200:
                print(f"[scan] {model} -> {r.status_code}")
                continue
            content = r.json()["choices"][0]["message"]["content"].strip()
            result = ai_parse_json(content)
            if result.get("vendor") or result.get("amount"):
                result["ai_generated"] = True
                # Validate category
                if result.get("category") not in CATEGORIES:
                    result["category"] = "Other"
                return result
        except Exception as exc:
            print(f"[scan] {model} error: {exc}")
            continue

    return {
        "vendor": "Unknown",
        "amount": 0.0,
        "currency": "USD",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "category": "Other",
        "items": [],
        "raw_text": "Could not extract receipt data",
        "ai_generated": False,
    }


# ========== AI: Auto-categorize expense ==========
def ai_categorize(description: str) -> str:
    """Suggest a category for an expense description."""
    if not description:
        return "Other"
    system_prompt = f"""Categorize this expense into ONE of these categories: {', '.join(CATEGORIES)}
Return ONLY the category name, nothing else."""
    raw = ai_call(system_prompt, description, max_tokens=20, temperature=0)
    if raw:
        cat = raw.strip().strip('"').strip("'")
        if cat in CATEGORIES:
            return cat
    return "Other"


# ========== Helpers ==========
def gen_id() -> str:
    return uuid.uuid4().hex[:12]


def gen_invoice_number() -> str:
    return f"INV-{int(time.time())}"


def calc_totals(line_items, tax_rate):
    subtotal = 0.0
    for item in line_items or []:
        qty = float(item.get("quantity", 1))
        price = float(item.get("unit_price", 0))
        subtotal += qty * price
    tax_amount = round(subtotal * float(tax_rate or 0), 2)
    total = round(subtotal + tax_amount, 2)
    return subtotal, tax_amount, total


# ========== Routes: Static Pages ==========
@app.route("/")
def index():
    """Serve the marketing landing page."""
    return send_from_directory(LANDING_DIR, "index.html")


@app.route("/app")
@app.route("/app/")
def app_page():
    """Serve the actual application."""
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/landing/<path:filename>")
def landing_assets(filename):
    return send_from_directory(LANDING_DIR, filename)


@app.route("/static/<path:filename>")
def frontend_assets(filename):
    return send_from_directory(FRONTEND_DIR, filename)


# ========== Routes: Health ==========
@app.route("/api/health")
def health():
    return jsonify({
        "ok": True,
        "ai": bool(OPENROUTER_KEY),
        "model": OPENROUTER_MODEL,
        "version": "1.0",
    })


# ========== Routes: Clients ==========
@app.route("/api/clients", methods=["GET"])
def list_clients():
    conn = get_db()
    rows = conn.execute("SELECT * FROM clients ORDER BY created_at DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/clients", methods=["POST"])
def create_client():
    data = request.get_json() or {}
    if not data.get("name"):
        return jsonify({"error": "name required"}), 400
    cid = gen_id()
    conn = get_db()
    conn.execute(
        """INSERT INTO clients
           (id, name, email, phone, company, address, currency, language, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            cid,
            data.get("name", "").strip(),
            data.get("email", "").strip(),
            data.get("phone", "").strip(),
            data.get("company", "").strip(),
            data.get("address", "").strip(),
            data.get("currency", "USD").strip(),
            data.get("language", "en").strip(),
            time.time(),
        ),
    )
    conn.commit()
    conn.close()
    return jsonify({"id": cid, "ok": True})


@app.route("/api/clients/<cid>", methods=["DELETE"])
def delete_client(cid):
    conn = get_db()
    conn.execute("DELETE FROM clients WHERE id = ?", (cid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ========== Routes: AI ==========
@app.route("/api/ai/generate-invoice", methods=["POST"])
def ai_gen():
    data = request.get_json() or {}
    prompt = data.get("prompt", "").strip()
    language = data.get("language", "en").strip()
    if not prompt:
        return jsonify({"error": "prompt required"}), 400
    return jsonify(ai_generate_invoice(prompt, language))


@app.route("/api/ai/scan-receipt", methods=["POST"])
def ai_scan():
    """Scan a receipt image. Expects JSON: {image: base64, mime_type, language}."""
    data = request.get_json() or {}
    image_b64 = data.get("image", "")
    mime_type = data.get("mime_type", "image/jpeg")
    language = data.get("language", "en")
    if not image_b64:
        return jsonify({"error": "image required"}), 400
    # Strip data URI prefix if present
    if "," in image_b64:
        image_b64 = image_b64.split(",", 1)[1]
    result = ai_scan_receipt(image_b64, mime_type, language)
    # Save image to disk
    try:
        ext = mime_type.split("/")[-1] or "jpg"
        img_path = UPLOADS_DIR / f"receipt-{int(time.time())}.{ext}"
        img_path.write_bytes(base64.b64decode(image_b64))
        result["image_path"] = str(img_path.relative_to(ROOT))
    except Exception as exc:
        print(f"[scan] image save failed: {exc}")
    return jsonify(result)


@app.route("/api/ai/categorize", methods=["POST"])
def ai_cat():
    data = request.get_json() or {}
    desc = data.get("description", "").strip()
    return jsonify({"category": ai_categorize(desc)})


# ========== Routes: Invoices ==========
@app.route("/api/invoices", methods=["GET"])
def list_invoices():
    conn = get_db()
    rows = conn.execute("""
        SELECT i.*, c.name as client_name, c.email as client_email, c.company as client_company
        FROM invoices i
        LEFT JOIN clients c ON c.id = i.client_id
        ORDER BY i.created_at DESC
    """).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["line_items"] = json.loads(d.get("line_items") or "[]")
        except Exception:
            d["line_items"] = []
        out.append(d)
    return jsonify(out)


@app.route("/api/invoices", methods=["POST"])
def create_invoice():
    data = request.get_json() or {}
    iid = gen_id()
    line_items = data.get("line_items") or []
    tax_rate = float(data.get("tax_rate", 0))
    subtotal, tax_amount, total = calc_totals(line_items, tax_rate)

    issue_date = data.get("issue_date") or datetime.now().strftime("%Y-%m-%d")
    due_days = int(data.get("due_days", 30))
    if not data.get("due_date"):
        due_date = (datetime.now() + timedelta(days=due_days)).strftime("%Y-%m-%d")
    else:
        due_date = data.get("due_date")

    conn = get_db()
    conn.execute(
        """INSERT INTO invoices
           (id, client_id, invoice_number, issue_date, due_date,
            line_items, subtotal, tax_rate, tax_amount, total,
            currency, notes, status, language, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            iid,
            data.get("client_id") or None,
            data.get("invoice_number") or gen_invoice_number(),
            issue_date,
            due_date,
            json.dumps(line_items),
            subtotal,
            tax_rate,
            tax_amount,
            total,
            data.get("currency", "USD").strip(),
            data.get("notes", "").strip(),
            data.get("status", "draft").strip(),
            data.get("language", "en").strip(),
            time.time(),
        ),
    )
    conn.commit()
    conn.close()
    return jsonify({"id": iid, "ok": True, "total": total})


@app.route("/api/invoices/<iid>/status", methods=["PATCH"])
def update_invoice_status(iid):
    data = request.get_json() or {}
    new_status = data.get("status", "draft")
    if new_status not in ("draft", "sent", "paid", "overdue"):
        return jsonify({"error": "invalid status"}), 400
    conn = get_db()
    conn.execute("UPDATE invoices SET status = ? WHERE id = ?", (new_status, iid))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/invoices/<iid>", methods=["DELETE"])
def delete_invoice(iid):
    conn = get_db()
    conn.execute("DELETE FROM invoices WHERE id = ?", (iid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/invoices/<iid>/send", methods=["POST"])
def send_invoice(iid):
    """Mark invoice as 'sent' and (mock) email to client."""
    data = request.get_json() or {}
    conn = get_db()
    row = conn.execute("""
        SELECT i.*, c.name as client_name, c.email as client_email
        FROM invoices i LEFT JOIN clients c ON c.id = i.client_id
        WHERE i.id = ?
    """, (iid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "not found"}), 404
    conn.execute("UPDATE invoices SET status = 'sent' WHERE id = ?", (iid,))
    conn.commit()
    conn.close()
    return jsonify({
        "ok": True,
        "sent_to": dict(row).get("client_email"),
        "message": f"Invoice sent to {dict(row).get('client_name')}",
        "method": data.get("method", "email"),
    })


# ========== Routes: Receipts & Expenses ==========
@app.route("/api/receipts", methods=["GET"])
def list_receipts():
    conn = get_db()
    rows = conn.execute("SELECT * FROM receipts ORDER BY created_at DESC").fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["items"] = json.loads(d.get("items") or "[]")
        except Exception:
            d["items"] = []
        out.append(d)
    return jsonify(out)


@app.route("/api/receipts", methods=["POST"])
def create_receipt():
    data = request.get_json() or {}
    rid = gen_id()
    conn = get_db()
    conn.execute(
        """INSERT INTO receipts
           (id, image_path, vendor, amount, currency, date, category, items, raw_text, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            rid,
            data.get("image_path", ""),
            data.get("vendor", "").strip(),
            float(data.get("amount", 0)),
            data.get("currency", "USD").strip(),
            data.get("date", datetime.now().strftime("%Y-%m-%d")),
            data.get("category", "Other").strip(),
            json.dumps(data.get("items", [])),
            data.get("raw_text", "").strip(),
            time.time(),
        ),
    )
    conn.commit()
    conn.close()
    return jsonify({"id": rid, "ok": True})


@app.route("/api/receipts/<rid>", methods=["DELETE"])
def delete_receipt(rid):
    conn = get_db()
    conn.execute("DELETE FROM receipts WHERE id = ?", (rid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ========== Routes: Analytics ==========
@app.route("/api/analytics")
def analytics():
    conn = get_db()

    # Invoice analytics
    inv_rows = conn.execute("SELECT * FROM invoices").fetchall()
    total_revenue = paid = pending = overdue = 0.0
    by_status = {"draft": 0, "sent": 0, "paid": 0, "overdue": 0}
    by_currency = {}
    by_month = {}
    today = datetime.now().strftime("%Y-%m-%d")
    for r in inv_rows:
        d = dict(r)
        total = float(d.get("total") or 0)
        cur = d.get("currency", "USD")
        status = d.get("status", "draft")
        total_revenue += total
        if status == "paid":
            paid += total
        elif status == "overdue" or (status == "sent" and d.get("due_date", "") < today):
            overdue += total
            if status != "overdue":
                # Auto-flag overdue
                conn.execute("UPDATE invoices SET status = 'overdue' WHERE id = ?", (d["id"],))
        else:
            pending += total
        by_status[status] = by_status.get(status, 0) + 1
        by_currency[cur] = by_currency.get(cur, 0) + total
        issue = d.get("issue_date", "")[:7]
        by_month[issue] = by_month.get(issue, 0) + total

    # Expense analytics (from receipts)
    exp_rows = conn.execute("SELECT * FROM receipts").fetchall()
    total_expenses = 0.0
    by_category = {}
    for r in exp_rows:
        d = dict(r)
        amt = float(d.get("amount") or 0)
        total_expenses += amt
        cat = d.get("category", "Other")
        by_category[cat] = by_category.get(cat, 0) + amt

    conn.commit()
    conn.close()

    return jsonify({
        "total_revenue": round(total_revenue, 2),
        "paid": round(paid, 2),
        "pending": round(pending, 2),
        "overdue": round(overdue, 2),
        "by_status": by_status,
        "by_currency": {k: round(v, 2) for k, v in by_currency.items()},
        "by_month": {k: round(v, 2) for k, v in sorted(by_month.items())},
        "invoice_count": len(inv_rows),
        "total_expenses": round(total_expenses, 2),
        "by_category": {k: round(v, 2) for k, v in sorted(by_category.items(), key=lambda x: -x[1])},
        "receipt_count": len(exp_rows),
    })


# ========== Main ==========
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8765"))
    print("=" * 60)
    print(f"  SmartInvoice AI")
    print(f"  http://localhost:{port}")
    print(f"  AI: {'ON' if OPENROUTER_KEY else 'OFFLINE (manual mode)'}")
    print("=" * 60)
    app.run(host="127.0.0.1", port=port, debug=False)
