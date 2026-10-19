"""
indices.py — Busca e cache de séries históricas de índices judiciais.

Fontes:
  - BCB/SGS (Banco Central): IPCA, IPCA-E, IPCA-15, INPC, IGP-M, IGP-DI, SELIC, TR
  - CSV local (data/tjsp.csv): Tabela Prática TJSP

API BCB/SGS: https://api.bcb.gov.br/dados/serie/bcdata.sgs.{serie}/dados
Não requer autenticação.
"""

from __future__ import annotations

import json
import requests
import pandas as pd

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Optional


# ─── Caminhos ─────────────────────────────────────────────────────────────────

_BASE_DIR = Path(__file__).parent.parent
CACHE_DIR = _BASE_DIR / "data" / "cache"
DATA_DIR  = _BASE_DIR / "data"

BCB_API = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{serie}/dados"


# ─── Enum de índices ───────────────────────────────────────────────────────────

class Indice(str, Enum):
    IPCA    = "IPCA"
    IPCA_E  = "IPCA-E"
    IPCA_15 = "IPCA-15"
    INPC    = "INPC"
    IGP_M   = "IGP-M"
    IGP_DI  = "IGP-DI"
    SELIC   = "SELIC"
    TR      = "TR"
    TJSP    = "TJSP"

    @property
    def descricao(self) -> str:
        return _DESCRICOES[self]

    @property
    def uso_tipico(self) -> str:
        return _USOS[self]


_DESCRICOES: dict[Indice, str] = {
    Indice.IPCA:    "IPCA – Índice de Preços ao Consumidor Amplo (IBGE)",
    Indice.IPCA_E:  "IPCA-E – Referência padrão JF e Previdenciário (IBGE)",
    Indice.IPCA_15: "IPCA-15 – Variação dos primeiros 15 dias (IBGE)",
    Indice.INPC:    "INPC – Índice Nacional de Preços ao Consumidor (IBGE)",
    Indice.IGP_M:   "IGP-M – Índice Geral de Preços do Mercado (FGV)",
    Indice.IGP_DI:  "IGP-DI – Índice Geral de Preços - Disp. Interna (FGV)",
    Indice.SELIC:   "SELIC – Taxa Selic acumulada no mês (BCB)",
    Indice.TR:      "TR – Taxa Referencial (BCB)",
    Indice.TJSP:    "TJSP – Tabela Prática do Tribunal de Justiça de SP",
}

_USOS: dict[Indice, str] = {
    Indice.IPCA:    "Ações cíveis em geral; padrão pós-Tema 905 STJ",
    Indice.IPCA_E:  "Débitos previdenciários (JF/TNU); condenações federais",
    Indice.IPCA_15: "Contratos com previsão expressa; alguns TJs",
    Indice.INPC:    "Reajuste de benefícios INSS; contratos trabalhistas",
    Indice.IGP_M:   "Contratos de aluguel; sentenças com previsão contratual",
    Indice.IGP_DI:  "Contratos antigos; algumas sentenças cíveis",
    Indice.SELIC:   "Débitos tributários federais; restituições da Fazenda",
    Indice.TR:      "FGTS; financiamentos habitacionais (CEF/SFH)",
    Indice.TJSP:    "Ações cíveis no Estado de SP (quando determinado na sentença)",
}


# ─── Séries BCB/SGS ───────────────────────────────────────────────────────────
# Referência: https://www3.bcb.gov.br/sgspub/

BCB_SERIES: dict[Indice, int] = {
    Indice.IPCA:    433,
    Indice.IPCA_E:  10764,
    Indice.IPCA_15: 10773,
    Indice.INPC:    188,
    Indice.IGP_M:   189,
    Indice.IGP_DI:  190,
    Indice.SELIC:   4390,   # Selic acumulada no mês, anualizada base 252
    Indice.TR:      226,
}


# ─── Helpers internos ─────────────────────────────────────────────────────────

def _cache_path(indice: Indice) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{indice.value.lower().replace('-', '_')}.json"


def _load_cache(indice: Indice) -> dict[str, str]:
    p = _cache_path(indice)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _save_cache(indice: Indice, data: dict[str, str]) -> None:
    _cache_path(indice).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _mes_key(ano: int, mes: int) -> str:
    """Chave de cache padronizada: 'AAAA-MM'."""
    return f"{ano:04d}-{mes:02d}"


def _next_month(ano: int, mes: int) -> tuple[int, int]:
    return (ano + 1, 1) if mes == 12 else (ano, mes + 1)


def _months_in_range(data_ini: date, data_fim: date) -> list[tuple[int, int]]:
    """Lista de (ano, mes) entre data_ini e data_fim, inclusive."""
    months: list[tuple[int, int]] = []
    ano, mes = data_ini.year, data_ini.month
    while (ano, mes) <= (data_fim.year, data_fim.month):
        months.append((ano, mes))
        ano, mes = _next_month(ano, mes)
    return months


# ─── Busca BCB ────────────────────────────────────────────────────────────────

def _fetch_bcb(serie: int, data_ini: date, data_fim: date) -> dict[str, str]:
    """
    Chama a API pública BCB/SGS e retorna {AAAA-MM: valor_percentual}.
    O BCB retorna o valor em % (ex: "0.35" = 0,35% ao mês).
    """
    params = {
        "formato": "json",
        "dataInicial": data_ini.strftime("%d/%m/%Y"),
        "dataFinal":   data_fim.strftime("%d/%m/%Y"),
    }
    resp = requests.get(BCB_API.format(serie=serie), params=params, timeout=20)
    resp.raise_for_status()

    result: dict[str, str] = {}
    for item in resp.json():
        d = datetime.strptime(item["data"], "%d/%m/%Y")
        result[_mes_key(d.year, d.month)] = item["valor"]
    return result


# ─── TJSP via CSV ─────────────────────────────────────────────────────────────

def _get_tjsp(data_ini: date, data_fim: date) -> pd.DataFrame:
    """
    Carrega tabela TJSP do arquivo data/tjsp.csv.

    Formato esperado do CSV:
        ano,mes,taxa
        2020,1,0.43
        2020,2,0.32
        ...

    O arquivo deve ser mantido atualizado manualmente conforme o TJSP
    publica sua Tabela Prática em: https://www.tjsp.jus.br/CorrecaoMonetaria
    """
    csv_path = DATA_DIR / "tjsp.csv"
    if not csv_path.exists():
        raise FileNotFoundError(
            f"Tabela TJSP não encontrada em {csv_path}.\n"
            "Baixe os dados em https://www.tjsp.jus.br/CorrecaoMonetaria e "
            "salve como data/tjsp.csv com colunas: ano,mes,taxa"
        )

    df = pd.read_csv(csv_path, dtype={"ano": int, "mes": int, "taxa": str})
    months = set(_months_in_range(data_ini, data_fim))
    mask = df.apply(lambda r: (int(r["ano"]), int(r["mes"])) in months, axis=1)
    resultado = df[mask].copy()

    if resultado.empty:
        raise ValueError(
            f"Nenhum dado TJSP encontrado para o período "
            f"{data_ini:%m/%Y} – {data_fim:%m/%Y}. Verifique o arquivo tjsp.csv."
        )

    resultado["taxa"] = resultado["taxa"].apply(lambda x: Decimal(str(x)))
    return resultado[["ano", "mes", "taxa"]].reset_index(drop=True)


# ─── API pública do módulo ────────────────────────────────────────────────────

def get_taxas(
    indice: Indice,
    data_ini: date,
    data_fim: date,
    forcar_atualizacao: bool = False,
) -> pd.DataFrame:
    """
    Retorna DataFrame com colunas [ano (int), mes (int), taxa (Decimal)]
    para o índice e período solicitado.

    - taxa: variação mensal em % com sinal (ex: Decimal("0.35") = 0,35% a.m.)
    - Inclui os meses de data_ini e data_fim.
    - Usa cache local JSON; busca da API apenas os meses ausentes.

    Args:
        indice: Membro do Enum Indice.
        data_ini: Início do período (usa ano/mês; dia ignorado).
        data_fim: Fim do período (usa ano/mês; dia ignorado).
        forcar_atualizacao: Se True, ignora cache e refaz a busca completa.

    Returns:
        pd.DataFrame ordenado por ano, mes.

    Raises:
        ValueError: Se algum mês do período não estiver disponível.
        requests.HTTPError: Se a API BCB retornar erro.
        FileNotFoundError: Se TJSP e o CSV não existir.
    """
    if data_fim < data_ini:
        raise ValueError("data_fim deve ser >= data_ini.")

    if indice == Indice.TJSP:
        return _get_tjsp(data_ini, data_fim)

    # ── Cache miss detection ──────────────────────────────────────────────────
    cache = {} if forcar_atualizacao else _load_cache(indice)
    months = _months_in_range(data_ini, data_fim)
    missing = [(a, m) for (a, m) in months if _mes_key(a, m) not in cache]

    if missing:
        ini_fetch = date(missing[0][0],  missing[0][1],  1)
        fim_fetch = date(missing[-1][0], missing[-1][1], 1)
        novos = _fetch_bcb(BCB_SERIES[indice], ini_fetch, fim_fetch)
        cache.update(novos)
        _save_cache(indice, cache)

    # ── Monta DataFrame ───────────────────────────────────────────────────────
    rows = []
    for ano, mes in months:
        key = _mes_key(ano, mes)
        if key not in cache:
            raise ValueError(
                f"Taxa {indice} não disponível para {key}. "
                "O índice pode ainda não ter sido divulgado para esse período."
            )
        rows.append({"ano": ano, "mes": mes, "taxa": Decimal(str(cache[key]))})

    return pd.DataFrame(rows)


def listar_indices() -> list[dict]:
    """Retorna lista de dicts com info de todos os índices disponíveis."""
    return [
        {
            "indice":      idx.value,
            "descricao":   idx.descricao,
            "uso_tipico":  idx.uso_tipico,
            "fonte":       "BCB/SGS" if idx != Indice.TJSP else "CSV local",
            "serie_bcb":   BCB_SERIES.get(idx),
        }
        for idx in Indice
    ]
