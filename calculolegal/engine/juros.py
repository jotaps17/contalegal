"""
juros.py — Cálculo de juros de mora judicial.

Regras gerais:
  - Juros simples a 1% a.m. é o padrão mais frequente em sentenças cíveis.
  - Termo inicial dos juros ≠ termo inicial da correção monetária.
    O advogado deve informar a data correta conforme a sentença/acórdão.
  - Juros incidem sobre o valor já corrigido monetariamente (base = CM).

Tipos suportados:
  - SIMPLES: taxa fixa mensal (% a.m.), linear.
  - SELIC: busca a série BCB 4390 acumulada no período (para futuras fases).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from enum import Enum
from typing import Optional


_PRECISAO_VALOR = Decimal("0.01")


# ─── Tipos de juros ───────────────────────────────────────────────────────────

class TipoJuros(str, Enum):
    SIMPLES  = "simples"    # Taxa fixa % a.m. (padrão cível)
    SELIC    = "selic"      # Selic acumulada — implementar na fase 2
    POUPANCA = "poupanca"   # Limitador em execuções contra Fazenda Pública


# ─── Resultado ────────────────────────────────────────────────────────────────

@dataclass
class ResultadoJuros:
    """Resultado do cálculo de juros de mora."""
    tipo:          TipoJuros
    data_ini:      date         # termo inicial dos juros (conforme sentença)
    data_fim:      date         # data de referência final
    base_calculo:  Decimal      # valor corrigido sobre o qual incidem os juros
    taxa_am:       Decimal      # taxa mensal em % (ex: Decimal("1") = 1% a.m.)
    n_meses:       int          # número de meses de incidência
    valor_juros:   Decimal      # valor monetário dos juros

    @property
    def percentual_total(self) -> Decimal:
        """Percentual total de juros acumulado no período."""
        return (self.taxa_am * self.n_meses).quantize(Decimal("0.01"))

    def resumo(self) -> dict:
        return {
            "tipo":           self.tipo.value,
            "periodo":        f"{self.data_ini:%d/%m/%Y} → {self.data_fim:%d/%m/%Y}",
            "n_meses":        self.n_meses,
            "taxa_am":        str(self.taxa_am),
            "percentual_total": str(self.percentual_total),
            "base_calculo":   str(self.base_calculo),
            "valor_juros":    str(self.valor_juros),
        }


# ─── Helpers ─────────────────────────────────────────────────────────────────

def meses_entre(data_ini: date, data_fim: date) -> int:
    """
    Número de meses completos entre data_ini e data_fim.

    Conta de mês a mês (sem considerar dias):
      Jan/2020 → Mar/2020 = 2 meses
      Jan/2020 → Jan/2020 = 0 meses
    """
    return (data_fim.year - data_ini.year) * 12 + (data_fim.month - data_ini.month)


# ─── Funções de cálculo ───────────────────────────────────────────────────────

def calcular_juros_simples(
    base: Decimal,
    taxa_am: Decimal,
    data_ini: date,
    data_fim: date,
) -> ResultadoJuros:
    """
    Juros de mora simples a taxa fixa mensal.

    Fórmula: juros = base × (taxa_am / 100) × n_meses

    Padrão mais comum em condenações cíveis (1% a.m. conforme art. 406 CC
    c/c art. 161 §1º CTN até vigência da Lei 14.905/2024).

    Args:
        base: Valor corrigido monetariamente sobre o qual incidem os juros.
        taxa_am: Taxa de juros ao mês em % (ex: Decimal("1") para 1% a.m.).
        data_ini: Termo inicial dos juros (conforme sentença/acórdão).
        data_fim: Data final (normalmente a data do cálculo).

    Returns:
        ResultadoJuros com o valor calculado.

    Raises:
        ValueError: Se data_fim < data_ini.
    """
    if data_fim < data_ini:
        raise ValueError(
            f"data_fim ({data_fim}) deve ser >= data_ini ({data_ini}) "
            "para cálculo de juros."
        )

    n = meses_entre(data_ini, data_fim)
    valor_juros = (base * taxa_am / Decimal("100") * n).quantize(
        _PRECISAO_VALOR, rounding=ROUND_HALF_UP
    )

    return ResultadoJuros(
        tipo=TipoJuros.SIMPLES,
        data_ini=data_ini,
        data_fim=data_fim,
        base_calculo=base,
        taxa_am=taxa_am,
        n_meses=n,
        valor_juros=valor_juros,
    )


def calcular_juros_taxa_legal(
    base: Decimal,
    data_ini: date,
    data_fim: date,
) -> ResultadoJuros:
    """
    Juros pela Taxa Legal (Lei 14.905/2024 — vigente a partir de 01/09/2024).

    A Taxa Legal é composta por IPCA + spread fixado pelo CMN.
    Requer busca de série específica — implementação completa na fase 2.

    Por ora, usa 1% a.m. como placeholder e emite aviso.
    """
    import warnings
    warnings.warn(
        "Taxa Legal (Lei 14.905/2024): cálculo completo via série BCB "
        "será implementado na fase 2. Usando 1% a.m. como estimativa.",
        UserWarning,
        stacklevel=2,
    )
    return calcular_juros_simples(base, Decimal("1"), data_ini, data_fim)
