"""
calculo_cda_mt.py — Atualização de Certidões de Dívida Ativa do Estado de Mato Grosso.

Legislação de referência:
  Fase 1 — IGP-DI + 1% a.m.: Art. 47-A Lei 7.098/98 (até Abr/2021)
  Fase 2 — IPCA + 1% a.m.:   Lei 11.329/2021 + Portaria SEFAZ-MT 094/2021 (Mai/2021–Fev/2024)
  Fase 3 — SELIC (all-in):   Lei 12.358/2023 + Decreto 762/2024 (Mar/2024 em diante)

A SELIC da Fase 3 engloba correção monetária e juros de mora num único fator —
não há parcela de juros separada como nas Fases 1 e 2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from typing import Optional

from .indices import Indice
from .correcao import calcular_correcao, ResultadoCorrecao
from .juros import calcular_juros_simples, ResultadoJuros


# ─── Datas de transição legais (fixas) ────────────────────────────────────────

_FIM_IGPDI  = date(2021, 4, 1)   # último mês IGP-DI: Abr/2021
_INI_IPCA   = date(2021, 5, 1)   # primeiro mês IPCA: Mai/2021
_FIM_IPCA   = date(2024, 2, 1)   # último mês IPCA: Fev/2024
_INI_SELIC  = date(2024, 3, 1)   # primeiro mês SELIC: Mar/2024

_PRECISAO = Decimal("0.01")


# ─── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class FaseCdaMt:
    """Resultado de uma fase individual do cálculo CDA-MT."""
    nome:              str
    indice:            Indice
    data_ini:          date
    data_fim:          date
    valor_entrada:     Decimal
    correcao:          ResultadoCorrecao
    juros:             Optional[ResultadoJuros]   # None na Fase 3 (SELIC all-in)
    valor_saida:       Decimal
    fundamento_legal:  str

    @property
    def n_meses(self) -> int:
        return self.correcao.n_meses


@dataclass
class ParametrosCdaMt:
    """Parâmetros de entrada para atualização de CDA do Estado de Mato Grosso."""
    valor_cda:    Decimal   # valor original da CDA (ou da última atualização)
    data_inicio:  date      # data de início da atualização
    data_fim:     date      # data final (referência do cálculo)

    def __post_init__(self):
        if self.valor_cda <= 0:
            raise ValueError("valor_cda deve ser positivo.")
        if self.data_fim < self.data_inicio:
            raise ValueError("data_fim deve ser >= data_inicio.")


@dataclass
class ResultadoCdaMt:
    """Resultado consolidado da atualização de CDA — Estado de Mato Grosso."""
    parametros:       ParametrosCdaMt
    fases:            list[FaseCdaMt] = field(default_factory=list)
    valor_original:   Decimal = Decimal("0")
    valor_atualizado: Decimal = Decimal("0")

    @property
    def fator_total(self) -> Decimal:
        if self.valor_original == 0:
            return Decimal("1")
        return (self.valor_atualizado / self.valor_original).quantize(
            Decimal("0.00000001"), rounding=ROUND_HALF_UP
        )

    @property
    def variacao_pct(self) -> Decimal:
        return ((self.fator_total - Decimal("1")) * Decimal("100")).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )

    @property
    def diferenca(self) -> Decimal:
        return (self.valor_atualizado - self.valor_original).quantize(_PRECISAO)

    def resumo(self) -> dict:
        return {
            "valor_original":   str(self.valor_original),
            "valor_atualizado": str(self.valor_atualizado),
            "diferenca":        str(self.diferenca),
            "fator_total":      str(self.fator_total),
            "variacao_pct":     str(self.variacao_pct),
            "fases": [
                {
                    "fase":           f.nome,
                    "indice":         f.indice.value,
                    "periodo":        f"{f.data_ini:%m/%Y} → {f.data_fim:%m/%Y}",
                    "n_meses":        f.n_meses,
                    "fundamento":     f.fundamento_legal,
                    "valor_entrada":  str(f.valor_entrada),
                    "valor_saida":    str(f.valor_saida),
                    "cm_fator":       str(f.correcao.fator_acumulado),
                    "juros_total_pct": str(f.juros.percentual_total) if f.juros else "—",
                }
                for f in self.fases
            ],
        }


# ─── Função principal ─────────────────────────────────────────────────────────

def calcular_cda_mt(params: ParametrosCdaMt) -> ResultadoCdaMt:
    """
    Atualiza CDA do Estado de MT aplicando as 3 fases conforme legislação.

    As transições de índice são fixas por lei — o usuário informa apenas
    valor, data de início e data final; o módulo determina quais fases se
    aplicam automaticamente.

    Fases:
      1. IGP-DI + 1% a.m. (juros simples) até Abr/2021
      2. IPCA + 1% a.m. (juros simples) de Mai/2021 a Fev/2024
      3. SELIC acumulada (all-in) a partir de Mar/2024

    Args:
        params: ParametrosCdaMt com valor, data_inicio e data_fim.

    Returns:
        ResultadoCdaMt com detalhamento por fase e totais consolidados.
    """
    ini = params.data_inicio
    fim = params.data_fim
    valor_atual = params.valor_cda
    fases: list[FaseCdaMt] = []

    # ── Fase 1: IGP-DI + 1% a.m. ──────────────────────────────────────────────
    if ini <= _FIM_IGPDI:
        fim_f1 = min(fim, _FIM_IGPDI)
        res_cm = calcular_correcao(valor_atual, ini, fim_f1, Indice.IGP_DI)
        res_j  = calcular_juros_simples(
            res_cm.valor_corrigido, Decimal("1"), ini, fim_f1
        )
        saida = (res_cm.valor_corrigido + res_j.valor_juros).quantize(
            _PRECISAO, rounding=ROUND_HALF_UP
        )
        fases.append(FaseCdaMt(
            nome="Fase 1 — IGP-DI + 1% a.m.",
            indice=Indice.IGP_DI,
            data_ini=ini,
            data_fim=fim_f1,
            valor_entrada=valor_atual,
            correcao=res_cm,
            juros=res_j,
            valor_saida=saida,
            fundamento_legal="Art. 47-A Lei 7.098/98 (redação anterior à Lei 11.329/2021)",
        ))
        valor_atual = saida
        if fim <= _FIM_IGPDI:
            return ResultadoCdaMt(
                parametros=params,
                fases=fases,
                valor_original=params.valor_cda,
                valor_atualizado=valor_atual,
            )

    # ── Fase 2: IPCA + 1% a.m. ────────────────────────────────────────────────
    ini_f2 = max(ini, _INI_IPCA)
    if ini_f2 <= _FIM_IPCA and fim >= _INI_IPCA:
        fim_f2 = min(fim, _FIM_IPCA)
        res_cm = calcular_correcao(valor_atual, ini_f2, fim_f2, Indice.IPCA)
        res_j  = calcular_juros_simples(
            res_cm.valor_corrigido, Decimal("1"), ini_f2, fim_f2
        )
        saida = (res_cm.valor_corrigido + res_j.valor_juros).quantize(
            _PRECISAO, rounding=ROUND_HALF_UP
        )
        fases.append(FaseCdaMt(
            nome="Fase 2 — IPCA + 1% a.m.",
            indice=Indice.IPCA,
            data_ini=ini_f2,
            data_fim=fim_f2,
            valor_entrada=valor_atual,
            correcao=res_cm,
            juros=res_j,
            valor_saida=saida,
            fundamento_legal="Lei 11.329/2021 + Portaria SEFAZ-MT 094/2021 + Decreto 916/2021",
        ))
        valor_atual = saida
        if fim <= _FIM_IPCA:
            return ResultadoCdaMt(
                parametros=params,
                fases=fases,
                valor_original=params.valor_cda,
                valor_atualizado=valor_atual,
            )

    # ── Fase 3: SELIC all-in ───────────────────────────────────────────────────
    ini_f3 = max(ini, _INI_SELIC)
    if fim >= _INI_SELIC:
        res_cm = calcular_correcao(valor_atual, ini_f3, fim, Indice.SELIC)
        saida  = res_cm.valor_corrigido
        fases.append(FaseCdaMt(
            nome="Fase 3 — SELIC (correção + juros unificados)",
            indice=Indice.SELIC,
            data_ini=ini_f3,
            data_fim=fim,
            valor_entrada=valor_atual,
            correcao=res_cm,
            juros=None,
            valor_saida=saida,
            fundamento_legal="Lei 12.358/2023 + Decreto 762/2024 (vigência Mar/2024)",
        ))
        valor_atual = saida

    return ResultadoCdaMt(
        parametros=params,
        fases=fases,
        valor_original=params.valor_cda,
        valor_atualizado=valor_atual,
    )
