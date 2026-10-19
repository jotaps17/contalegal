"""
pdf_extractor.py — Extração de parâmetros de documentos judiciais via regex.

Utiliza pdfplumber para extrair o texto e expressões regulares calibradas para
o padrão de sentenças, acórdãos e planilhas de cálculo judiciais brasileiras.
Não há chamada externa: todo o processamento é local.
"""

import io
import re
from datetime import datetime
from typing import Optional

import pdfplumber


# ── Leitura de PDF ────────────────────────────────────────────────────────────

def extrair_texto_pdf(pdf_bytes: bytes) -> str:
    """Extrai texto de todas as páginas do PDF via pdfplumber."""
    paginas = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for pagina in pdf.pages:
            t = pagina.extract_text()
            if t:
                paginas.append(t)
    return "\n\n".join(paginas)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _brl_to_float(s: str) -> Optional[float]:
    """'1.234,56' → 1234.56"""
    try:
        return float(s.strip().replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _parse_date_br(s: str) -> Optional[str]:
    """'DD/MM/AAAA' → 'YYYY-MM-DD', ou None se inválida."""
    try:
        return datetime.strptime(s.strip(), "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


# ── Extratores individuais ────────────────────────────────────────────────────

_RE_BRL = r'([\d]{1,3}(?:\.[\d]{3})*,\d{2})'


def _find_valor_principal(texto: str) -> Optional[float]:
    """
    Extrai o valor principal buscando valores em contexto de condenação/pagamento.
    Retorna o primeiro valor válido encontrado nos padrões em ordem de prioridade.
    """
    patterns = [
        rf'condenad[ao]\b[^R\n]{{0,100}}R\$\s*{_RE_BRL}',
        rf'pagar\b[^R\n]{{0,100}}R\$\s*{_RE_BRL}',
        rf'valor\s+principal[^R\n]{{0,100}}R\$\s*{_RE_BRL}',
        rf'valor\s+da?\s+(?:d[íi]vida|condenação|débito)[^R\n]{{0,100}}R\$\s*{_RE_BRL}',
        rf'quantia\s+de\s+R\$\s*{_RE_BRL}',
        rf'import[âa]ncia\s+de\s+R\$\s*{_RE_BRL}',
        rf'soma\s+de\s+R\$\s*{_RE_BRL}',
        rf'R\$\s*{_RE_BRL}',          # fallback: primeira ocorrência
    ]
    for pattern in patterns:
        m = re.search(pattern, texto, re.IGNORECASE)
        if m:
            v = _brl_to_float(m.group(1))
            if v and v > 0:
                return v
    return None


def _find_indice(texto: str) -> Optional[str]:
    """
    Detecta o índice de correção monetária.
    Ordem: variantes específicas antes das genéricas (ex: IPCA-E antes de IPCA).
    """
    regras = [
        (r'\bIPCA[- ]?E\b',                                                       "IPCA-E"),
        (r'\bIPCA[- ]?15\b',                                                       "IPCA-15"),
        (r'\bIGP[- ]?DI\b',                                                        "IGP-DI"),
        (r'\bIGP[- ]?M\b',                                                         "IGP-M"),
        (r'\bINPC\b',                                                               "INPC"),
        (r'\bSELIC\b',                                                              "SELIC"),
        (r'\bTaxa Referencial\b|\bTR\b(?=[\s,.()\-])',                             "TR"),
        (r'Tabela Pr[áa]tica\b[^.]{0,60}?\bTJSP\b|\bTJSP\b[^.]{0,60}?Tabela Pr[áa]tica\b', "TJSP"),
        (r'\bIPCA\b',                                                               "IPCA"),
    ]
    for pattern, indice in regras:
        if re.search(pattern, texto, re.IGNORECASE):
            return indice
    return None


def _find_taxa_juros(texto: str) -> float:
    """
    Extrai a taxa de juros moratórios mensal (%).
    Padrão cível: 1% a.m. (Art. 406 CC / Art. 161 §1º CTN).
    """
    patterns = [
        r'juros[^.\n]{0,80}?(\d+(?:[.,]\d+)?)\s*%\s*(?:a\.?\s*m\.?|ao\s+m[eê]s)',
        r'mora[^.\n]{0,80}?(\d+(?:[.,]\d+)?)\s*%\s*(?:a\.?\s*m\.?|ao\s+m[eê]s)',
        r'(\d+(?:[.,]\d+)?)\s*%\s*(?:a\.?\s*m\.?|ao\s+m[eê]s)[^.\n]{0,60}?juro',
    ]
    for p in patterns:
        m = re.search(p, texto, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1).replace(",", "."))
            except ValueError:
                pass
    return 1.0


def _find_datas(texto: str) -> tuple[Optional[str], Optional[str]]:
    """
    Extrai data_ini (evento/citação) e data_fim (referência do cálculo).
    Ambas em formato YYYY-MM-DD ou None se não encontradas.
    """
    _re_d = r'(\d{1,2}/\d{2}/\d{4})'

    ini_patterns = [
        rf'evento\s+danoso[^.\n]{{0,80}}?{_re_d}',
        rf'data\s+do\s+evento[^.\n]{{0,80}}?{_re_d}',
        rf'{_re_d}[^.\n]{{0,60}}?cita[çc][ãa]o',
        rf'cita[çc][ãa]o[^.\n]{{0,80}}?{_re_d}',
        rf'ajuizamento[^.\n]{{0,80}}?{_re_d}',
        rf'publica[çc][ãa]o\b[^.\n]{{0,80}}?{_re_d}',
        rf'senten[çc]a\b[^.\n]{{0,80}}?{_re_d}',
        rf'vencimento[^.\n]{{0,80}}?{_re_d}',
        rf'termo\s+inicial[^.\n]{{0,80}}?{_re_d}',
        rf'a\s+partir\s+de[^.\n]{{0,80}}?{_re_d}',
    ]

    ini = None
    for pat in ini_patterns:
        m = re.search(pat, texto, re.IGNORECASE)
        if m:
            ini = _parse_date_br(m.group(1))
            if ini:
                break

    fim_patterns = [
        rf'data\s+do\s+c[áa]lculo[^.\n]{{0,80}}?{_re_d}',
        rf'até\s+(?:a\s+)?(?:data\s+de|o\s+dia)[^.\n]{{0,80}}?{_re_d}',
        rf'efetivo\s+pagamento[^.\n]{{0,80}}?{_re_d}',
        rf'presente\s+data[^.\n]{{0,80}}?{_re_d}',
    ]

    fim = None
    for pat in fim_patterns:
        m = re.search(pat, texto, re.IGNORECASE)
        if m:
            fim = _parse_date_br(m.group(1))
            if fim:
                break

    return ini, fim


def _find_honorarios(texto: str) -> tuple[Optional[float], str]:
    """Extrai percentual e base dos honorários advocatícios."""
    m = re.search(
        r'honor[áa]rios\b[^.\n]{0,100}?(\d+(?:[.,]\d+)?)\s*%',
        texto, re.IGNORECASE,
    )
    pct = None
    if m:
        try:
            pct = float(m.group(1).replace(",", "."))
        except ValueError:
            pass

    base = "causa" if re.search(r'valor\s+da\s+causa', texto, re.IGNORECASE) else "condenacao"
    return pct, base


def _find_multa(texto: str) -> tuple[Optional[float], str]:
    """Extrai percentual e tipo da multa processual (Art. 523 CPC ou genérica)."""
    # Art. 523 CPC tem prioridade — padrão 10%
    if re.search(r'art(?:igo)?\.?\s*523\b', texto, re.IGNORECASE):
        m = re.search(r'multa[^.\n]{0,80}?(\d+(?:[.,]\d+)?)\s*%', texto, re.IGNORECASE)
        pct = 10.0
        if m:
            try:
                pct = float(m.group(1).replace(",", "."))
            except ValueError:
                pass
        return pct, "523"

    m = re.search(
        r'multa\s+(?:processual\s+)?(?:de\s+)?(\d+(?:[.,]\d+)?)\s*%',
        texto, re.IGNORECASE,
    )
    if m:
        try:
            return float(m.group(1).replace(",", ".")), "generica"
        except ValueError:
            pass

    return None, "generica"


# ── API pública ───────────────────────────────────────────────────────────────

def extrair_parametros_pdf(pdf_bytes: bytes) -> dict:
    """
    Extrai parâmetros de cálculo de um PDF judicial via regex.
    Processamento inteiramente local — sem chamadas externas.

    Args:
        pdf_bytes: Conteúdo do arquivo PDF em bytes.

    Returns:
        dict com os campos extraídos. Campos não detectados ficam None.

    Raises:
        ValueError: Se o PDF não contiver texto extraível (ex: documento escaneado).
    """
    texto = extrair_texto_pdf(pdf_bytes)

    if not texto.strip():
        raise ValueError(
            "Não foi possível extrair texto do PDF. "
            "O arquivo pode ser uma imagem escaneada (sem OCR)."
        )

    valor               = _find_valor_principal(texto)
    data_ini, data_fim  = _find_datas(texto)
    indice              = _find_indice(texto)
    taxa_j              = _find_taxa_juros(texto)
    hon_pct, hon_base   = _find_honorarios(texto)
    multa_pct, multa_tp = _find_multa(texto)

    pendentes = []
    if not valor:
        pendentes.append("valor principal")
    if not data_ini:
        pendentes.append("data inicial")
    if not indice:
        pendentes.append("índice de correção")

    obs = (
        f"Verifique manualmente: {', '.join(pendentes)}."
        if pendentes
        else "Extração automática concluída — revise os campos antes de calcular."
    )

    return {
        "valor_principal":       valor,
        "data_ini_correcao":     data_ini,
        "data_fim_correcao":     data_fim,
        "indice":                indice,
        "taxa_juros_am":         taxa_j,
        "honorarios_percentual": hon_pct,
        "honorarios_base":       hon_base if hon_pct else None,
        "multa_percentual":      multa_pct,
        "multa_tipo":            multa_tp if multa_pct else None,
        "observacoes":           obs,
    }
