# SmartInvoice AI

> **Stop writing invoices. Start talking.**
> AI-powered invoicing for freelancers, agencies, and small businesses.

Built for the **Kevin O'Leary × Emergent Builder Fest** — a $100,000 contest.

🌐 **[Live Demo](https://smartinvoice-ai.onrender.com)** · ✨ **[Launch App](https://smartinvoice-ai.onrender.com/app)** · 🐛 **[Issues](https://github.com/YOUR-USERNAME/smartinvoice-ai/issues)**

---

## What it does

SmartInvoice AI turns what you sold — typed or spoken, in English or Bangla — into a tax-ready, multi-currency invoice in 30 seconds. No templates, no spreadsheets, no friction.

### Features

- ✨ **AI Invoice Generation** — natural language → structured invoice with line items, tax, currency, due date
- 📸 **Receipt OCR + Auto-Categorize** — snap a receipt, AI extracts vendor, amount, date, items, category
- 💱 **Multi-Currency** — USD, EUR, GBP, BDT, INR, JPY, AUD, CAD
- 🌐 **Bilingual** — full Bangla + English UI
- 📊 **Live Dashboard** — revenue, paid, pending, overdue, charts
- 📤 **Send & Track** — one click to send, mark paid/sent/overdue
- 📄 **PDF Export** — professional invoice PDFs
- 🆓 **Free Forever** — no sign-up, no credit card

## Tech Stack

- **Backend**: Flask + SQLite + gunicorn
- **Frontend**: Vanilla JS (no build step), Chart.js, Google Fonts
- **AI**: OpenRouter (free LLM models) for generation, vision-capable models for receipt scan
- **Hosting**: Render.com (free tier)

## Quick Start

### Local

```bash
pip install -r requirements.txt
cp backend/.env.example backend/.env
# Add your OPENROUTER_API_KEY to backend/.env
python backend/app.py
```

Open http://localhost:8765

### Deploy to Render.com

1. Push to GitHub
2. Go to https://render.com → New → Blueprint
3. Connect your repo
4. Add `OPENROUTER_API_KEY` env var
5. Click Apply

See `render.yaml` for the full config.

## Project Structure

```
smartinvoice-ai/
├── backend/
│   ├── app.py            # Flask + AI backend
│   └── .env.example      # API key template
├── frontend/
│   └── index.html        # App dashboard
├── landing/
│   └── index.html        # Marketing landing page
├── data/                 # SQLite DB + uploads
├── requirements.txt
├── render.yaml           # Render.com config
└── Procfile              # Process file
```

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/health` | GET | Health check |
| `/api/clients` | GET/POST | List/create clients |
| `/api/invoices` | GET/POST | List/create invoices |
| `/api/invoices/<id>/status` | PATCH | Update status (paid/sent/overdue) |
| `/api/ai/generate-invoice` | POST | AI: text → structured invoice |
| `/api/ai/scan-receipt` | POST | AI: image → receipt data |
| `/api/ai/categorize` | POST | AI: text → category |
| `/api/analytics` | GET | Dashboard stats |

## Why it wins

| Problem | Existing tools | SmartInvoice AI |
|---|---|---|
| Slow to create invoices | Wave, FreshBooks (5-10 min) | 30 seconds |
| Need template/format | All existing tools | Just type what you sold |
| Bilingual support | Almost none | Full Bangla + English |
| Receipt scanning | Expensive add-on | Free tier |
| Learning curve | Hours of setup | Zero — open and go |

## License

MIT

## Credits

Built by **MD Firoj Khon** for the Kevin O'Leary × Emergent Builder Fest 2025.
