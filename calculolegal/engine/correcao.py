"""
correcao.py — Cálculo da correção monetária judicial.

Convenção de período adotada (padrão CJ / tribunais brasileiros):
  - O fator de cada mês é: (1 + taxa_mensal / 100)
  - São incluídos todos os meses entre data_ini e data_fim (inclusive).
  - Aplicação acumulativa: fator_total = Π fator_i

Precisão:
  - Fatores calculados com 8 casas decimais (Decimal, ROUND_HALF_UP).
  - Valores monetários arredondados para 2 casas decimais.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from typing import Optional

from .indices import Indice, get_taxas


# ─── Constantes de precisão ───────────────────────────────────────────────────

_PRECISAO_FATOR = Decimal("0.00000001")   # 8 casas no fator
_PRECISAO_VALOR = Decimal("0.01")         # 2 casas no valor monetário


# ─── Dataclasses de resultado ─────────────────────────────────────────────────

@dataclass
class ParcelaCorrecao:
    """
    Representa a aplicação do índice em um único mês.
    Compõe a memória de cálculo para juntada aos autos.
    """
    ano:          int
    mes:          int
    taxa_pct:     Decimal   # variação mensal em % (ex: 0.35)
    fator:        Decimal   # (1 + taxa_pct / 100), ex: 1.0035
    valor_inicio: Decimal   # valor ao início do mês
    valor_fim:    Decimal   # valor ao fim do mês (após correção)

    @property
    def periodo_label(self) -> str:
        return f"{self.mes:02d}/{self.ano}"

    @property
    def variacao_valor(self) -> Decimal:
        return self.valor_fim - self.valor_inicio


@dataclass
class ResultadoCorrecao:
    """
    Resultado completo da correção monetária com memória de cálculo.
    """
    indice:          Indice
    data_ini:        date
    data_fim:        date
    valor_original:  Decimal
    valor_corrigido: Decimal
    fator_acumulado: Decimal
    parcelas:        list[ParcelaCorrecao] = field(default_factory=list)

    @property
    def variacao_pct(self) -> Decimal:
        """Variação percentual total do período."""
        return ((self.fator_acumulado - Decimal("1")) * Decimal("100")).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )

    @property
    def valor_acrescido(self) -> Decimal:
        """Valor nominal da correção (diferença)."""
        return (self.valor_corrigido - self.valor_original).quantize(_PRECISAO_VALOR)

    @property
    def n_meses(self) -> int:
        return len(self.parcelas)

    def resumo(self) -> dict:
        return {
            "indice":          self.indice.value,
            "periodo":         f"{self.data_ini:%d/%m/%Y} → {self.data_fim:%d/%m/%Y}",
            "n_meses":         self.n_meses,
            "fator_acumulado": str(self.fator_acumulado),
            "variacao_pct":    str(self.variacao_pct),
            "valor_original":  str(self.valor_original),
            "valor_corrigido": str(self.valor_corrigido),
            "valor_acrescido": str(self.valor_acrescido),
        }


# ─── Função principal ─────────────────────────────────────────────────────────

def calcular_correcao(
    valor: Decimal,
    data_ini: date,
    data_fim: date,
    indice: Indice,
    forcar_atualizacao: bool = False,
) -> ResultadoCorrecao:
    """
    Calcula a correção monetária de `valor` entre `data_ini` e `data_fim`
    pelo índice informado.

    A correção é aplicada mês a mês de forma acumulativa:
        valor_corrigido = valor × Π (1 + taxa_i / 100)

    Args:
        valor: Valor principal a corrigir.
        data_ini: Data-base (termo a quo). Usa o mês/ano; o dia é ignorado.
        data_fim: Data final (termo ad quem). Usa o mês/ano; o dia é ignorado.
        indice: Índice de correção monetária a aplicar.
        forcar_atualizacao: Se True, ignora cache e busca da API.

    Returns:
        ResultadoCorrecao com parcelas e fator acumulado.

    Raises:
        ValueError: Se data_fim < data_ini ou índice indisponível no período.
    """
    if data_fim < data_ini:
        raise ValueError(
            f"data_fim ({data_fim}) deve ser maior ou igual a data_ini ({data_ini})."
        )

    df_taxas = get_taxas(indice, data_ini, data_fim, forcar_atualizacao)

    fator_acumulado = Decimal("1")
    valor_corrente  = valor
    parcelas: list[ParcelaCorrecao] = []

    for _, row in df_taxas.iterrows():
        taxa_pct = Decimal(str(row["taxa"]))
        fator    = (Decimal("1") + taxa_pct / Decimal("100")).quantize(
            _PRECISAO_FATOR, rounding=ROUND_HALF_UP
        )

        valor_antes   = valor_corrente
        valor_corrente = (valor_corrente * fator).quantize(
            _PRECISAO_VALOR, rounding=ROUND_HALF_UP
        )
        fator_acumulado = (fator_acumulado * fator).quantize(
            _PRECISAO_FATOR, rounding=ROUND_HALF_UP
        )

        parcelas.append(ParcelaCorrecao(
            ano=int(row["ano"]),
            mes=int(row["mes"]),
            taxa_pct=taxa_pct,
            fator=fator,
            valor_inicio=valor_antes,
            valor_fim=valor_corrente,
        ))

    return ResultadoCorrecao(
        indice=indice,
        data_ini=data_ini,
        data_fim=data_fim,
        valor_original=valor,
        valor_corrigido=valor_corrente,
        fator_acumulado=fator_acumulado,
        parcelas=parcelas,
    )


def calcular_correcao_encadeada(
    valor: Decimal,
    data_ini: date,
    data_fim: date,
    trechos: list[tuple[date, date, Indice]],
    forcar_atualizacao: bool = False,
) -> list[ResultadoCorrecao]:
    """
    Correção com troca de índice ao longo do período (encadeamento).

    Útil quando a sentença determina índices diferentes em sub-períodos.
    Exemplo: TR de 2000 a 2012, IPCA-E de 2012 em diante.

    Args:
        valor: Valor principal inicial.
        data_ini: Data inicial total (informativa; use os trechos para controle).
        data_fim: Data final total (informativa).
        trechos: Lista de (data_inicio, data_fim, indice) sem lacunas.
                 O valor de saída de cada trecho é a entrada do próximo.
        forcar_atualizacao: Propaga para get_taxas.

    Returns:
        Lista de ResultadoCorrecao, um por trecho. O valor corrigido total
        é o valor_corrigido do último elemento.
    """
    resultados: list[ResultadoCorrecao] = []
    valor_atual = valor

    for ini, fim, idx in trechos:
        res = calcular_correcao(valor_atual, ini, fim, idx, forcar_atualizacao)
        resultados.append(res)
        valor_atual = res.valor_corrigido

    return resultados
