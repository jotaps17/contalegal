# ContaLegal

Streamlit app that calculates the monetary correction (inflation adjustment),
interest, penalties, and attorney's fees owed on Brazilian judicial debts and
tax-related CDAs (Certidão de Dívida Ativa), following the official BCB
(Central Bank) index series and the specific legal rules that apply to each
calculation.

## Features

- **Manual input**: computes a judicial debt update using BCB index series
  (IPCA-E, IPCA, IGP-DI, SELIC, TR, INPC, etc.) plus default interest,
  Art. 523 CPC penalty, and attorney's fees.
- **PDF upload**: extracts calculation parameters from a judicial ruling PDF
  via local regex (optionally assisted by the Anthropic API) and pre-fills
  the form.
- **CDA — MT**: updates Certidões de Dívida Ativa for the state of Mato
  Grosso, automatically applying the three legally mandated phases (IGP-DI,
  then IPCA, then SELIC) based on the relevant dates.
- Chained index calculation across periods with different applicable
  indices (e.g. TR until 2012, then IPCA-E).
- All monetary arithmetic uses `Decimal` (never `float`); factors are kept
  at 8 decimal places, monetary values rounded to 2 with `ROUND_HALF_UP`.
- Index values are cached to disk (`calculolegal/data/cache/`) so only
  missing months trigger a BCB API call.

## Stack

Python, Streamlit, pandas, pdfplumber (PDF text extraction), Decimal-based
calculation engine, Docker/Docker Compose for deployment.

## Running it

Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/).

```bash
docker compose build
docker compose up -d
# → http://localhost:8501
docker compose down
```

Or with `make` (see `Makefile`):

```bash
make build
make run-d
make stop
make logs
```

### Without Docker

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r calculolegal/requirements.txt
streamlit run app.py
```

### Optional environment variable

PDF extraction works out of the box via local regex. To additionally enable
AI-assisted extraction, copy `.env.example` to `.env` and set
`ANTHROPIC_API_KEY`.

## Tests

There is no automated test suite. The calculation engine can be smoke-tested
directly from the CLI, which runs through three built-in scenarios:

```bash
pip install -r calculolegal/requirements.txt
python calculolegal/main.py
```

## Screenshots

> _placeholder — add screenshots of the manual-entry, PDF-upload, and
> CDA-MT tabs here_

## License

© 2026 João Pedro Gomes Spengler. All rights reserved.
