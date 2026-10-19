"""
calculo.py — Orquestrador de cálculo completo de atualização de débito judicial.

Fluxo:
  1. Correção Monetária (CM) sobre o principal
  2. Juros de Mora (JM) sobre o valor corrigido
  3. Multa processual (se aplicável)
  4. Honorários de sucumbência (se aplicável)
  5. Total consolidado

Referência legal (CPC/2015 e CC/2002):
  - Art. 406 CC: juros moratórios à taxa legal (1% a.m. até set/2024)
  - Lei 14.905/2024: nova Taxa Legal a partir de set/2024
  - Arts. 77, 81, 523, 537 CPC: multas processuais
  - Art. 85 CPC: honorários de sucumbência
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from typing import Optional

from .indices import Indice
from .correcao import calcular_correcao, ResultadoCorrecao
from .juros import calcular_juros_simples, ResultadoJuros


_PRECISAO_VALOR = Decimal("0.01")


# ─── Parâmetros de entrada ────────────────────────────────────────────────────

@dataclass
class ParametrosHonorarios:
    """
    Parâmetros para cálculo de honorários de sucumbência (Art. 85 CPC).
    """
    percentual: Decimal                         # % aplicado
    base: str = "condenacao"                    # "condenacao" | "causa"
    valor_causa: Optional[Decimal] = None       # obrigatório se base == "causa"
    incide_juros_mora: bool = False             # Raro; depende da sentença

    def __post_init__(self):
        if self.base == "causa" and self.valor_causa is None:
            raise ValueError(
                "Informe valor_causa quando a base dos honorários for 'causa'."
            )
        if self.base not in ("condenacao", "causa"):
            raise ValueError(f"base inválida: '{self.base}'. Use 'condenacao' ou 'causa'.")


@dataclass
class ParametrosMulta:
    """
    Parâmetros para cálculo de multa processual (CPC/2015).
    """
    percentual: Decimal                   # % da multa
    tipo: str = "generica"                # "generica" | "523" | "astreinte" etc.
    base: str = "atualizado"             # "atualizado" (principal+juros) | "causa"
    valor_causa: Optional[Decimal] = None # se base == "causa"


@dataclass
class ParametrosCalculo:
    """
    Parâmetros de entrada para um cálculo completo de atualização de débito.

    Exemplo mínimo:
        params = ParametrosCalculo(
            valor_principal=Decimal("10000"),
            data_ini_correcao=date(2022, 1, 1),
            data_fim_correcao=date(2024, 12, 31),
            indice=Indice.IPCA_E,
        )
    """
    # ── Dados principais ──────────────────────────────────────────────────────
    valor_principal:    Decimal
    data_ini_correcao:  date
    data_fim_correcao:  date
    indice:             Indice

    # ── Juros de mora ─────────────────────────────────────────────────────────
    taxa_juros_am:      Decimal = Decimal("1")    # 1% a.m. (padrão cível)
    data_ini_juros:     Optional[date] = None     # None = usa data_ini_correcao
    data_fim_juros:     Optional[date] = None     # None = usa data_fim_correcao

    # ── Componentes opcionais ─────────────────────────────────────────────────
    honorarios:         Optional[ParametrosHonorarios] = None
    multa:              Optional[ParametrosMulta]      = None

    # ── Outros débitos processuais (custas, perito etc.) ──────────────────────
    despesas_adicionais: Decimal = Decimal("0")

    def __post_init__(self):
        if self.valor_principal <= 0:
            raise ValueError("valor_principal deve ser positivo.")
        if self.data_fim_correcao < self.data_ini_correcao:
            raise ValueError("data_fim_correcao deve ser >= data_ini_correcao.")


# ─── Resultado ────────────────────────────────────────────────────────────────

@dataclass
class ResultadoCalculo:
    """
    Resultado consolidado de um cálculo de atualização de débito judicial.
    Contém todos os componentes e a memória de cálculo para juntada.
    """
    parametros:         ParametrosCalculo

    # Componentes calculados
    correcao:           ResultadoCorrecao
    juros:              ResultadoJuros

    valor_principal:    Decimal
    valor_corrigido:    Decimal      # principal após CM
    valor_juros:        Decimal      # juros de mora
    valor_subtotal:     Decimal      # corrigido + juros
    valor_multa:        Decimal
    valor_honorarios:   Decimal
    valor_despesas:     Decimal
    valor_total:        Decimal

    def resumo(self) -> dict:
        """Dicionário compacto para serialização ou geração de relatório."""
        return {
            "principal":      str(self.valor_principal),
            "correcao":       self.correcao.resumo(),
            "juros":          self.juros.resumo(),
            "valor_corrigido": str(self.valor_corrigido),
            "valor_juros":    str(self.valor_juros),
            "subtotal":       str(self.valor_subtotal),
            "multa":          str(self.valor_multa),
            "honorarios":     str(self.valor_honorarios),
            "despesas":       str(self.valor_despesas),
            "total":          str(self.valor_total),
        }

    def imprimir(self) -> None:
        """Imprime resumo formatado no terminal."""
        sep = "─" * 62

        def brl(v: Decimal) -> str:
            return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

        print(f"\n{'=' * 62}")
        print(f"  CÁLCULO DE ATUALIZAÇÃO DE DÉBITO JUDICIAL")
        print(f"{'=' * 62}")
        print(f"  Índice:          {self.parametros.indice.descricao}")
        print(f"  Período CM:      {self.parametros.data_ini_correcao:%d/%m/%Y} "
              f"→ {self.parametros.data_fim_correcao:%d/%m/%Y}")
        print(sep)
        print(f"  Principal:                    {brl(self.valor_principal):>15}")
        print(f"  + Correção Monetária          {brl(self.valor_corrigido - self.valor_principal):>15}")
        print(f"    (fator: {self.correcao.fator_acumulado}, "
              f"variação: {self.correcao.variacao_pct}%)")
        print(f"  = Valor corrigido             {brl(self.valor_corrigido):>15}")
        print(f"  + Juros de mora               {brl(self.valor_juros):>15}")
        print(f"    ({self.juros.n_meses} meses × {self.juros.taxa_am}% a.m.)")
        print(f"  = Subtotal                    {brl(self.valor_subtotal):>15}")
        if self.valor_multa:
            print(f"  + Multa processual            {brl(self.valor_multa):>15}")
        if self.valor_honorarios:
            print(f"  + Honorários sucumbência      {brl(self.valor_honorarios):>15}")
        if self.valor_despesas:
            print(f"  + Despesas adicionais         {brl(self.valor_despesas):>15}")
        print(sep)
        print(f"  TOTAL ATUALIZADO              {brl(self.valor_total):>15}")
        print(f"{'=' * 62}\n")

        print("  MEMÓRIA DE CÁLCULO — Correção Monetária")
        print(f"  {'Mês/Ano':<10} {'Variação%':>10} {'Fator':>12} {'Saldo (R$)':>16}")
        print(f"  {sep}")
        for p in self.correcao.parcelas:
            print(f"  {p.periodo_label:<10} {p.taxa_pct:>10.4f} "
                  f"{p.fator:>12.8f} {brl(p.valor_fim):>16}")
        print(f"\n  Fator acumulado: {self.correcao.fator_acumulado}")
        print(f"{'=' * 62}\n")


# ─── Função principal ─────────────────────────────────────────────────────────

def calcular(params: ParametrosCalculo) -> ResultadoCalculo:
    """
    Executa o cálculo completo de atualização de débito judicial.

    Args:
        params: ParametrosCalculo com todos os dados da condenação.

    Returns:
        ResultadoCalculo com breakdown completo e memória de cálculo.
    """
    # ── 1. Correção monetária ─────────────────────────────────────────────────
    res_cm = calcular_correcao(
        valor=params.valor_principal,
        data_ini=params.data_ini_correcao,
        data_fim=params.data_fim_correcao,
        indice=params.indice,
    )
    valor_corrigido = res_cm.valor_corrigido

    # ── 2. Juros de mora ──────────────────────────────────────────────────────
    data_ini_j = params.data_ini_juros or params.data_ini_correcao
    data_fim_j = params.data_fim_juros or params.data_fim_correcao

    res_juros = calcular_juros_simples(
        base=valor_corrigido,
        taxa_am=params.taxa_juros_am,
        data_ini=data_ini_j,
        data_fim=data_fim_j,
    )
    valor_juros   = res_juros.valor_juros
    valor_subtotal = (valor_corrigido + valor_juros).quantize(_PRECISAO_VALOR)

    # ── 3. Multa processual ───────────────────────────────────────────────────
    valor_multa = Decimal("0")
    if params.multa:
        m = params.multa
        if m.base == "atualizado":
            base_multa = valor_subtotal
        elif m.base == "causa" and m.valor_causa is not None:
            # Atualiza valor da causa para a data fim
            res_causa = calcular_correcao(
                valor=m.valor_causa,
                data_ini=params.data_ini_correcao,
                data_fim=params.data_fim_correcao,
                indice=params.indice,
            )
            base_multa = res_causa.valor_corrigido
        else:
            base_multa = valor_subtotal

        valor_multa = (base_multa * m.percentual / Decimal("100")).quantize(
            _PRECISAO_VALOR, rounding=ROUND_HALF_UP
        )

    # ── 4. Honorários de sucumbência ──────────────────────────────────────────
    valor_honorarios = Decimal("0")
    if params.honorarios:
        h = params.honorarios
        if h.base == "condenacao":
            base_hon = valor_subtotal
        else:  # "causa" — já validado no __post_init__
            res_causa_h = calcular_correcao(
                valor=h.valor_causa,
                data_ini=params.data_ini_correcao,
                data_fim=params.data_fim_correcao,
                indice=params.indice,
            )
            base_hon = res_causa_h.valor_corrigido

        valor_honorarios = (base_hon * h.percentual / Decimal("100")).quantize(
            _PRECISAO_VALOR, rounding=ROUND_HALF_UP
        )

    # ── 5. Total ──────────────────────────────────────────────────────────────
    valor_despesas = params.despesas_adicionais.quantize(_PRECISAO_VALOR)
    valor_total = (
        valor_subtotal + valor_multa + valor_honorarios + valor_despesas
    ).quantize(_PRECISAO_VALOR)

    return ResultadoCalculo(
        parametros=params,
        correcao=res_cm,
        juros=res_juros,
        valor_principal=params.valor_principal,
        valor_corrigido=valor_corrigido,
        valor_juros=valor_juros,
        valor_subtotal=valor_subtotal,
        valor_multa=valor_multa,
        valor_honorarios=valor_honorarios,
        valor_despesas=valor_despesas,
        valor_total=valor_total,
    )
