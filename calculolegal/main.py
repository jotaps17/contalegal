"""
main.py — CLI de teste do motor de cálculo ContaLegal.

Uso:
    python main.py

Demonstra três cenários comuns:
  1. Correção simples (IPCA-E, sem honorários)
  2. Cálculo completo (INPC + juros + honorários + multa)
  3. Correção com encadeamento de índices (TR → IPCA-E)
"""

import sys
from decimal import Decimal
from datetime import date

if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from engine.indices import Indice, listar_indices
from engine.calculo import (
    ParametrosCalculo,
    ParametrosHonorarios,
    ParametrosMulta,
    calcular,
)
from engine.correcao import calcular_correcao_encadeada


# ─── Helpers de formatação ────────────────────────────────────────────────────

def brl(valor: Decimal) -> str:
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def cabecalho(titulo: str) -> None:
    print(f"\n{'#' * 66}")
    print(f"#  {titulo}")
    print(f"{'#' * 66}")


# ─── Cenários ─────────────────────────────────────────────────────────────────

def cenario_1():
    """Correção monetária simples — IPCA-E, sem outros componentes."""
    cabecalho("CENÁRIO 1 — Correção simples (IPCA-E)")

    params = ParametrosCalculo(
        valor_principal=Decimal("10000.00"),
        data_ini_correcao=date(2022, 1, 1),
        data_fim_correcao=date(2024, 12, 31),
        indice=Indice.IPCA_E,
        taxa_juros_am=Decimal("1"),
    )

    resultado = calcular(params)
    resultado.imprimir()


def cenario_2():
    """Cálculo completo — INPC + juros + honorários 10% + multa 523 CPC."""
    cabecalho("CENÁRIO 2 — Completo (INPC + juros + honorários + multa)")

    params = ParametrosCalculo(
        valor_principal=Decimal("25000.00"),
        data_ini_correcao=date(2021, 6, 1),
        data_fim_correcao=date(2024, 12, 31),
        indice=Indice.INPC,
        taxa_juros_am=Decimal("1"),
        data_ini_juros=date(2021, 6, 1),
        honorarios=ParametrosHonorarios(
            percentual=Decimal("10"),
            base="condenacao",
        ),
        multa=ParametrosMulta(
            percentual=Decimal("10"),
            tipo="523",
            base="atualizado",
        ),
    )

    resultado = calcular(params)
    resultado.imprimir()


def cenario_3():
    """Encadeamento de índices — TR de 2005 a 2012, IPCA-E de 2012 em diante."""
    cabecalho("CENÁRIO 3 — Encadeamento TR → IPCA-E")

    valor = Decimal("50000.00")
    trechos = [
        (date(2005, 1, 1), date(2011, 12, 31), Indice.TR),
        (date(2012, 1, 1), date(2024, 12, 31), Indice.IPCA_E),
    ]

    resultados = calcular_correcao_encadeada(
        valor=valor,
        data_ini=trechos[0][0],
        data_fim=trechos[-1][1],
        trechos=trechos,
    )

    print(f"\n  Valor original:  {brl(valor)}")
    for i, res in enumerate(resultados, 1):
        print(f"\n  Trecho {i}: {res.indice.value} "
              f"({res.data_ini:%m/%Y} → {res.data_fim:%m/%Y})")
        print(f"    Fator:          {res.fator_acumulado}")
        print(f"    Variação:       {res.variacao_pct}%")
        print(f"    Valor corrigido: {brl(res.valor_corrigido)}")

    valor_final = resultados[-1].valor_corrigido
    print(f"\n  {'─' * 40}")
    print(f"  VALOR FINAL CORRIGIDO: {brl(valor_final)}")
    print(f"  Variação total:        "
          f"{((valor_final / valor - 1) * 100).quantize(Decimal('0.01'))}%\n")


def listar():
    """Lista todos os índices disponíveis."""
    cabecalho("ÍNDICES DISPONÍVEIS")
    print(f"\n  {'Índice':<12} {'Descrição':<50} {'Série BCB'}")
    print(f"  {'─' * 75}")
    for idx in listar_indices():
        serie = str(idx["serie_bcb"]) if idx["serie_bcb"] else "CSV local"
        print(f"  {idx['indice']:<12} {idx['descricao']:<50} {serie}")
    print()


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    listar()
    cenario_1()
    # cenario_2()   # descomente para testar
    # cenario_3()   # descomente para testar (período longo = mais lento)
