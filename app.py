"""
app.py — ContaLegal: Interface Streamlit para Cálculo de Atualização de Débito Judicial.

Execução local:  streamlit run app.py
Via Docker:      make run-d  (acessa http://localhost:8501)
"""

import sys
import json
from pathlib import Path
from decimal import Decimal, InvalidOperation
from datetime import date

import streamlit as st
import pandas as pd

# ── Adiciona calculolegal/ ao path para que engine.* seja importável ──────────
_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT / "calculolegal"))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from engine.indices import Indice, listar_indices
from engine.calculo import (
    ParametrosCalculo,
    ParametrosHonorarios,
    ParametrosMulta,
    calcular,
)
from engine.calculo_cda_mt import ParametrosCdaMt, calcular_cda_mt

# ── Configuração da página ────────────────────────────────────────────────────
st.set_page_config(
    page_title="ContaLegal — Cálculo Judicial",
    page_icon="⚖️",
    layout="wide",
)

# ── Helpers de formatação ─────────────────────────────────────────────────────

def fmt_brl(v) -> str:
    """Formata Decimal/float como moeda brasileira: R$ 1.234,56"""
    d = Decimal(str(v)).quantize(Decimal("0.01"))
    s = f"{float(d):,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def parse_brl(s: str) -> Decimal:
    """Converte string monetária (1.234,56 ou 1,234.56) para Decimal."""
    s = s.strip().replace("R$", "").replace("\xa0", "").replace(" ", "")
    if not s:
        raise ValueError("Valor não informado.")
    if "," in s and "." in s:
        if s.rindex(",") > s.rindex("."):   # padrão BR: 1.234,56
            s = s.replace(".", "").replace(",", ".")
        else:                               # padrão US: 1,234.56
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    return Decimal(s)


def _safe_date(raw, fallback: date) -> date:
    try:
        return date.fromisoformat(raw) if raw else fallback
    except (ValueError, TypeError):
        return fallback


# ── Exibe resultado consolidado ───────────────────────────────────────────────

def _mostrar_resultado(r) -> None:
    p = r.parametros

    # Métricas principais
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Principal", fmt_brl(r.valor_principal))
    c2.metric(
        "Valor Corrigido",
        fmt_brl(r.valor_corrigido),
        delta=f"+{float(r.correcao.variacao_pct):.2f}%",
    )
    c3.metric(
        "Juros de Mora",
        fmt_brl(r.valor_juros),
        delta=f"{r.juros.n_meses} meses × {r.juros.taxa_am}% a.m.",
    )
    c4.metric("TOTAL", fmt_brl(r.valor_total))

    st.divider()

    # Composição do débito
    st.subheader("Composição do Débito")
    rows = [
        {"Componente": "Principal original",        "Valor": fmt_brl(r.valor_principal),                                "Obs.": ""},
        {"Componente": "+ Correção monetária",       "Valor": fmt_brl(r.valor_corrigido - r.valor_principal),
         "Obs.": f"Fator {r.correcao.fator_acumulado}  ({float(r.correcao.variacao_pct):.4f}%)"},
        {"Componente": "= Valor corrigido",          "Valor": fmt_brl(r.valor_corrigido),                               "Obs.": ""},
        {"Componente": "+ Juros de mora",            "Valor": fmt_brl(r.valor_juros),
         "Obs.": f"{r.juros.n_meses} meses × {r.juros.taxa_am}% a.m. = {float(r.juros.percentual_total):.2f}%"},
        {"Componente": "= Subtotal",                 "Valor": fmt_brl(r.valor_subtotal),                                "Obs.": ""},
    ]

    if r.valor_multa:
        obs = f"{float(p.multa.percentual):.1f}% s/ {p.multa.base}" if p.multa else ""
        rows.append({"Componente": "+ Multa processual",        "Valor": fmt_brl(r.valor_multa),      "Obs.": obs})

    if r.valor_honorarios:
        obs = f"{float(p.honorarios.percentual):.1f}% s/ {p.honorarios.base}" if p.honorarios else ""
        rows.append({"Componente": "+ Honorários sucumbência",  "Valor": fmt_brl(r.valor_honorarios), "Obs.": obs})

    if r.valor_despesas:
        rows.append({"Componente": "+ Despesas adicionais",     "Valor": fmt_brl(r.valor_despesas),   "Obs.": ""})

    rows.append({"Componente": "TOTAL ATUALIZADO", "Valor": fmt_brl(r.valor_total), "Obs.": ""})

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.divider()

    # Memória de cálculo mês a mês
    with st.expander("📋 Memória de Cálculo — Correção Monetária (mês a mês)"):
        parcelas_data = [
            {
                "Mês/Ano":        parc.periodo_label,
                "Variação (%)":   float(parc.taxa_pct),
                "Fator":          float(parc.fator),
                "Saldo Início":   fmt_brl(parc.valor_inicio),
                "Saldo Fim":      fmt_brl(parc.valor_fim),
            }
            for parc in r.correcao.parcelas
        ]
        df_parc = pd.DataFrame(parcelas_data)
        if not df_parc.empty:
            st.dataframe(df_parc, use_container_width=True, hide_index=True)
        else:
            st.info("Período sem meses completos — nenhuma parcela de correção.")

    st.divider()

    # Exportar
    st.subheader("Exportar")
    col_j, col_c = st.columns(2)

    with col_j:
        st.download_button(
            "⬇️ Resumo (JSON)",
            data=json.dumps(r.resumo(), ensure_ascii=False, indent=2),
            file_name="contalegal_resultado.json",
            mime="application/json",
        )

    with col_c:
        if parcelas_data:
            csv_bytes = df_parc.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")
            st.download_button(
                "⬇️ Memória de Cálculo (CSV)",
                data=csv_bytes,
                file_name="contalegal_memoria.csv",
                mime="text/csv",
            )


# ── Estado de sessão ──────────────────────────────────────────────────────────
if "resultado" not in st.session_state:
    st.session_state.resultado = None
if "pdf_params" not in st.session_state:
    st.session_state.pdf_params = None
if "cda_resultado" not in st.session_state:
    st.session_state["cda_resultado"] = None

# ── Barra lateral ─────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚖️ ContaLegal")
    st.caption("Atualização de Débito Judicial — v1.0")
    st.divider()

    with st.expander("📋 Índices disponíveis"):
        for idx in listar_indices():
            st.markdown(f"**{idx['indice']}**")
            st.caption(idx["uso_tipico"])

    st.divider()
    st.caption("Fonte BCB/SGS: dados obtidos via API pública do Banco Central do Brasil.")

# ── Abas principais ───────────────────────────────────────────────────────────
tab_manual, tab_pdf, tab_resultado, tab_cda = st.tabs([
    "📝 Entrada Manual",
    "📄 Upload PDF",
    "📊 Resultado",
    "🏦 CDA — MT",
])

# ═══════════════════════════════════════════════════════════════════════════════
# ABA 1 — ENTRADA MANUAL
# ═══════════════════════════════════════════════════════════════════════════════

with tab_manual:
    st.header("Entrada Manual de Parâmetros")

    _indice_opcoes = [idx.value for idx in Indice]
    _indice_map    = {idx.value: idx for idx in Indice}
    _idx_default   = _indice_opcoes.index("IPCA-E")

    with st.form("form_manual"):

        # Dados principais
        st.subheader("Dados Principais")
        col1, col2 = st.columns(2)

        with col1:
            f_valor = st.text_input(
                "Valor do Principal (R$) *",
                value="10.000,00",
                help="Valor original da condenação. Ex: 10.000,00 ou 10000.00",
            )
            f_indice = st.selectbox(
                "Índice de Correção Monetária *",
                options=_indice_opcoes,
                index=_idx_default,
                help="IPCA-E: débitos federais/previdenciários | TJSP: ações cíveis em SP",
            )
            f_despesas = st.number_input(
                "Despesas adicionais (R$)",
                value=0.0,
                min_value=0.0,
                step=100.0,
                format="%.2f",
                help="Custas processuais, honorários periciais, etc.",
            )

        with col2:
            f_data_ini = st.date_input(
                "Início da Correção Monetária *",
                value=date(2022, 1, 1),
                format="DD/MM/YYYY",
                help="Data do evento danoso ou publicação da sentença",
            )
            f_data_fim = st.date_input(
                "Fim da Correção Monetária *",
                value=date.today(),
                format="DD/MM/YYYY",
                help="Normalmente a data de elaboração do cálculo",
            )
            f_taxa_juros = st.number_input(
                "Taxa de Juros (% a.m.) *",
                value=1.0,
                min_value=0.0,
                step=0.1,
                format="%.2f",
                help="1% a.m. = padrão cível (Art. 406 CC). Use 0 para não incluir juros.",
            )

        # Juros com data diferente
        f_juros_data_dif = st.checkbox(
            "Data de início dos juros diferente da correção monetária",
        )
        f_data_ini_juros = st.date_input(
            "Início dos Juros de Mora",
            value=date(2022, 1, 1),
            format="DD/MM/YYYY",
            help="Preencha somente se marcou a opção acima",
        )

        st.divider()

        # Honorários
        st.subheader("Honorários de Sucumbência (Art. 85 CPC)")
        col3, col4 = st.columns(2)

        with col3:
            f_tem_hon = st.checkbox("Incluir honorários de sucumbência")
            f_hon_pct = st.number_input(
                "Percentual (%)",
                value=10.0,
                min_value=0.0,
                max_value=100.0,
                step=0.5,
                format="%.1f",
                key="hon_pct",
            )

        with col4:
            f_hon_base = st.selectbox(
                "Base de cálculo",
                options=["condenacao", "causa"],
                format_func=lambda x: "Valor da condenação atualizada" if x == "condenacao" else "Valor da causa",
                key="hon_base",
            )
            f_hon_causa = st.text_input(
                "Valor da causa (R$)",
                value="",
                help="Preencha apenas se a base for 'Valor da causa'",
                key="hon_causa",
                placeholder="10.000,00",
            )

        st.divider()

        # Multa processual
        st.subheader("Multa Processual (CPC/2015)")
        col5, col6 = st.columns(2)

        with col5:
            f_tem_multa = st.checkbox("Incluir multa processual")
            f_multa_pct = st.number_input(
                "Percentual (%)",
                value=10.0,
                min_value=0.0,
                max_value=100.0,
                step=0.5,
                format="%.1f",
                key="multa_pct",
            )

        with col6:
            f_multa_tipo = st.selectbox(
                "Tipo da multa",
                options=["generica", "523"],
                format_func=lambda x: "Genérica (Arts. 77/81 CPC)" if x == "generica" else "Art. 523 CPC (10% s/ o débito)",
                key="multa_tipo",
            )
            f_multa_base = st.radio(
                "Base de cálculo",
                options=["atualizado", "causa"],
                format_func=lambda x: "Valor atualizado (corrigido + juros)" if x == "atualizado" else "Valor da causa",
                key="multa_base",
            )

        submitted = st.form_submit_button(
            "🔢 Calcular", type="primary", use_container_width=True
        )

    # Processa o formulário
    if submitted:
        try:
            valor_principal = parse_brl(f_valor)

            honorarios = None
            if f_tem_hon:
                hon_vc = parse_brl(f_hon_causa) if f_hon_base == "causa" and f_hon_causa.strip() else None
                honorarios = ParametrosHonorarios(
                    percentual=Decimal(str(f_hon_pct)),
                    base=f_hon_base,
                    valor_causa=hon_vc,
                )

            multa = None
            if f_tem_multa:
                multa = ParametrosMulta(
                    percentual=Decimal(str(f_multa_pct)),
                    tipo=f_multa_tipo,
                    base=f_multa_base,
                )

            params = ParametrosCalculo(
                valor_principal=valor_principal,
                data_ini_correcao=f_data_ini,
                data_fim_correcao=f_data_fim,
                indice=_indice_map[f_indice],
                taxa_juros_am=Decimal(str(f_taxa_juros)),
                data_ini_juros=f_data_ini_juros if f_juros_data_dif else None,
                honorarios=honorarios,
                multa=multa,
                despesas_adicionais=Decimal(str(f_despesas)),
            )

            with st.spinner("Buscando índices e calculando..."):
                resultado = calcular(params)

            st.session_state.resultado = resultado
            st.success("✅ Cálculo concluído! Veja a aba **Resultado** acima.")

        except InvalidOperation as e:
            st.error(f"Valor inválido — verifique os campos monetários: {e}")
        except ValueError as e:
            st.error(f"Parâmetro inválido: {e}")
        except Exception as e:
            st.error(f"Erro no cálculo: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# ABA 2 — UPLOAD PDF
# ═══════════════════════════════════════════════════════════════════════════════

with tab_pdf:
    st.header("Upload de Documento Judicial (PDF)")

    _pdf_ok = True
    try:
        from engine.pdf_extractor import extrair_parametros_pdf
    except ImportError as _ie:
        _pdf_ok = False
        st.warning(
            f"Biblioteca necessária não instalada: `{_ie}`. "
            "Execute `pip install pdfplumber` ou use o contêiner Docker."
        )

    if _pdf_ok:
        st.info(
            "Envie uma sentença, acórdão ou planilha de cálculo em PDF. "
            "Os parâmetros são extraídos localmente via regex — "
            "nenhum dado é enviado a serviços externos. "
            "O PDF deve conter texto selecionável (documentos escaneados sem OCR não são suportados)."
        )

        uploaded = st.file_uploader(
            "Selecione um arquivo PDF",
            type=["pdf"],
            help="Processamento 100% local via pdfplumber.",
        )

        if uploaded:
            st.caption(f"📄 **{uploaded.name}** — {uploaded.size / 1024:.1f} KB")

            if st.button("🔍 Extrair Parâmetros", type="primary"):
                with st.spinner("Lendo e analisando o PDF..."):
                    try:
                        params_raw = extrair_parametros_pdf(uploaded.read())
                        st.session_state.pdf_params = params_raw
                        st.success("✅ Parâmetros extraídos! Revise os campos abaixo.")
                    except Exception as e:
                        st.error(f"Erro na extração: {e}")

    # Formulário de revisão dos parâmetros extraídos
    if st.session_state.pdf_params:
        p = st.session_state.pdf_params
        st.subheader("Parâmetros Extraídos — Revise antes de calcular")

        _indice_vals = [idx.value for idx in Indice]
        _idx_raw     = str(p.get("indice") or "IPCA-E")
        _idx_raw     = _idx_raw if _idx_raw in _indice_vals else "IPCA-E"

        _vp_raw    = p.get("valor_principal")
        _vp_str    = f"{float(_vp_raw):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if _vp_raw else ""

        _hon_pct   = p.get("honorarios_percentual")
        _hon_base  = str(p.get("honorarios_base") or "condenacao")
        _multa_pct = p.get("multa_percentual")
        _multa_tp  = str(p.get("multa_tipo") or "generica")

        with st.form("form_pdf"):
            col1, col2 = st.columns(2)

            with col1:
                p_valor  = st.text_input("Valor do Principal (R$)", value=_vp_str)
                p_indice = st.selectbox(
                    "Índice de Correção",
                    options=_indice_vals,
                    index=_indice_vals.index(_idx_raw),
                )
                p_taxa   = st.number_input(
                    "Taxa de Juros (% a.m.)",
                    value=float(p.get("taxa_juros_am") or 1.0),
                    min_value=0.0,
                    step=0.1,
                    format="%.2f",
                )

            with col2:
                p_ini = st.date_input(
                    "Início da Correção",
                    value=_safe_date(p.get("data_ini_correcao"), date(2022, 1, 1)),
                    format="DD/MM/YYYY",
                )
                p_fim = st.date_input(
                    "Fim da Correção",
                    value=_safe_date(p.get("data_fim_correcao"), date.today()),
                    format="DD/MM/YYYY",
                )

                if _hon_pct:
                    st.info(f"Honorários detectados: **{_hon_pct}%** (base: {_hon_base})")
                if _multa_pct:
                    st.info(f"Multa detectada: **{_multa_pct}%** (tipo: {_multa_tp})")
                if p.get("observacoes"):
                    st.caption(f"📝 {str(p['observacoes'])[:250]}")

            p_submit = st.form_submit_button(
                "🔢 Calcular com estes parâmetros", type="primary", use_container_width=True
            )

        if p_submit:
            try:
                valor_principal = parse_brl(p_valor)

                honorarios = None
                if _hon_pct:
                    honorarios = ParametrosHonorarios(
                        percentual=Decimal(str(_hon_pct)),
                        base=_hon_base if _hon_base in ("condenacao", "causa") else "condenacao",
                    )

                multa = None
                if _multa_pct:
                    multa = ParametrosMulta(
                        percentual=Decimal(str(_multa_pct)),
                        tipo=_multa_tp if _multa_tp in ("generica", "523") else "generica",
                        base="atualizado",
                    )

                params = ParametrosCalculo(
                    valor_principal=valor_principal,
                    data_ini_correcao=p_ini,
                    data_fim_correcao=p_fim,
                    indice=Indice(p_indice),
                    taxa_juros_am=Decimal(str(p_taxa)),
                    honorarios=honorarios,
                    multa=multa,
                )

                with st.spinner("Calculando..."):
                    resultado = calcular(params)

                st.session_state.resultado = resultado
                st.success("✅ Cálculo concluído! Veja a aba **Resultado** acima.")

            except InvalidOperation as e:
                st.error(f"Valor inválido: {e}")
            except ValueError as e:
                st.error(f"Parâmetro inválido: {e}")
            except Exception as e:
                st.error(f"Erro no cálculo: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# ABA 3 — RESULTADO
# ═══════════════════════════════════════════════════════════════════════════════

with tab_resultado:
    if st.session_state.resultado is None:
        st.info(
            "Nenhum cálculo realizado ainda. "
            "Use a aba **Entrada Manual** ou **Upload PDF** para gerar um resultado."
        )
    else:
        r = st.session_state.resultado
        p = r.parametros

        st.header("Resultado do Cálculo")
        st.caption(
            f"Índice: **{p.indice.descricao}** &nbsp;|&nbsp; "
            f"Período CM: {p.data_ini_correcao:%d/%m/%Y} → {p.data_fim_correcao:%d/%m/%Y}"
        )

        _mostrar_resultado(r)


# ═══════════════════════════════════════════════════════════════════════════════
# ABA 4 — CDA — MATO GROSSO
# ═══════════════════════════════════════════════════════════════════════════════

with tab_cda:
    st.header("Atualização de CDA — Estado de Mato Grosso")
    st.caption(
        "Certidões de Dívida Ativa do Estado de MT conforme "
        "Lei 11.329/2021 e Lei 12.358/2023."
    )

    st.info(
        "O simulador aplica automaticamente as 3 fases legais: "
        "**IGP-DI + 1%** (até Abr/2021) → **IPCA + 1%** (Mai/2021–Fev/2024) "
        "→ **SELIC** (Mar/2024 em diante). Informe apenas o valor e as datas.",
        icon="⚖️",
    )

    with st.form("form_cda_mt"):
        col1, col2 = st.columns(2)

        with col1:
            cda_valor = st.text_input(
                "Valor da CDA (R$) *",
                value="10.000,00",
                help="Valor original da certidão ou da última atualização.",
            )

        with col2:
            cda_data_ini = st.date_input(
                "Data de Início da Atualização *",
                value=date(2010, 1, 1),
                format="DD/MM/YYYY",
                help="Data de vencimento ou de constituição do crédito tributário.",
            )

        cda_data_fim = st.date_input(
            "Data Final (referência do cálculo) *",
            value=date.today(),
            format="DD/MM/YYYY",
            help="Normalmente a data de hoje ou de elaboração do cálculo.",
        )

        cda_submit = st.form_submit_button(
            "🔢 Calcular Atualização", type="primary", use_container_width=True
        )

    if cda_submit:
        try:
            valor_cda = parse_brl(cda_valor)
            params_cda = ParametrosCdaMt(
                valor_cda=valor_cda,
                data_inicio=cda_data_ini,
                data_fim=cda_data_fim,
            )

            with st.spinner("Buscando índices e calculando as 3 fases..."):
                res_cda = calcular_cda_mt(params_cda)

            st.session_state["cda_resultado"] = res_cda

        except InvalidOperation as e:
            st.error(f"Valor inválido — verifique o campo monetário: {e}")
        except ValueError as e:
            st.error(f"Parâmetro inválido: {e}")
        except Exception as e:
            st.error(f"Erro no cálculo: {e}")

    # ── Exibe resultado CDA ────────────────────────────────────────────────────
    if st.session_state.get("cda_resultado"):
        r = st.session_state["cda_resultado"]

        st.divider()
        st.subheader("Resultado")

        # Métricas principais
        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("Valor Original", fmt_brl(r.valor_original))
        mc2.metric(
            "Valor Atualizado",
            fmt_brl(r.valor_atualizado),
            delta=f"+{float(r.variacao_pct):.2f}%",
        )
        mc3.metric("Acréscimo", fmt_brl(r.diferenca))
        mc4.metric("Fator Total", f"{float(r.fator_total):.4f}×")

        st.divider()

        # Tabela de fases
        st.subheader("Composição por Fase Legal")
        fase_rows = []
        for f in r.fases:
            juros_str = (
                f"{float(f.juros.percentual_total):.2f}% ({f.juros.n_meses} meses × 1%)"
                if f.juros else "— (SELIC all-in)"
            )
            fase_rows.append({
                "Fase": f.nome,
                "Período": f"{f.data_ini:%m/%Y} → {f.data_fim:%m/%Y}",
                "Meses": f.n_meses,
                "Fator CM": float(f.correcao.fator_acumulado),
                "Juros": juros_str,
                "Entrada (R$)": fmt_brl(f.valor_entrada),
                "Saída (R$)": fmt_brl(f.valor_saida),
            })
        st.dataframe(pd.DataFrame(fase_rows), use_container_width=True, hide_index=True)

        # Fundamento legal
        with st.expander("📜 Fundamento Legal"):
            for f in r.fases:
                st.markdown(f"**{f.nome}:** {f.fundamento_legal}")

        st.divider()

        # Memória de cálculo por fase
        st.subheader("Memória de Cálculo — Mês a Mês")
        for f in r.fases:
            with st.expander(f"📋 {f.nome} ({f.n_meses} meses)"):
                parcelas_data = [
                    {
                        "Mês/Ano":       parc.periodo_label,
                        "Variação (%)":  float(parc.taxa_pct),
                        "Fator":         float(parc.fator),
                        "Saldo Início":  fmt_brl(parc.valor_inicio),
                        "Saldo Fim CM":  fmt_brl(parc.valor_fim),
                    }
                    for parc in f.correcao.parcelas
                ]
                if parcelas_data:
                    st.dataframe(
                        pd.DataFrame(parcelas_data),
                        use_container_width=True,
                        hide_index=True,
                    )

        st.divider()

        # Exportar
        st.subheader("Exportar")
        col_j2, col_c2 = st.columns(2)

        with col_j2:
            st.download_button(
                "⬇️ Resumo (JSON)",
                data=json.dumps(r.resumo(), ensure_ascii=False, indent=2),
                file_name="cda_mt_resultado.json",
                mime="application/json",
            )

        with col_c2:
            all_parcelas = []
            for f in r.fases:
                for parc in f.correcao.parcelas:
                    all_parcelas.append({
                        "Fase": f.nome,
                        "Mês/Ano": parc.periodo_label,
                        "Variação (%)": float(parc.taxa_pct),
                        "Fator": float(parc.fator),
                        "Saldo Início": float(parc.valor_inicio),
                        "Saldo Fim CM": float(parc.valor_fim),
                    })
            if all_parcelas:
                csv_bytes = (
                    pd.DataFrame(all_parcelas)
                    .to_csv(index=False, sep=";", decimal=",")
                    .encode("utf-8-sig")
                )
                st.download_button(
                    "⬇️ Memória Completa (CSV)",
                    data=csv_bytes,
                    file_name="cda_mt_memoria.csv",
                    mime="text/csv",
                )
