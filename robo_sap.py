import streamlit as st
import pandas as pd
import requests
import io
import re
import urllib3
import altair as alt
from datetime import datetime

# Desativa os avisos de certificado SSL para a rede da empresa
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configura a página para o modo estendido ideal para TVs operacionais
st.set_page_config(page_title="Painel Amarração NM", layout="wide", page_icon="✅")

st.markdown(
    "<h1 style='text-align: center; color: #1A365D;'>AMARRAÇÃO NM - CONTROLE DE CHECKLISTS</h1>",
    unsafe_allow_html=True,
)

# =========================================================
# CONFIGURAÇÃO DOS 3 CHECKLISTS (dados + formulário)
# =========================================================
CHECKLISTS = {
    "ferramentas": {
        "titulo": "1. CHECKLIST FERRAMENTAS",
        "url_dados": "https://sheet.zohopublic.com/sheet/publishedsheet/7e5091470d1d7556840e64864aec864eac62c1a9e45c3a7023d1f0f0022c5862?type=grid&download=csv",
        "url_form": "https://forms.zohopublic.com/teclogforms/form/ChecklistCintoTipoParaquedistaTalabarteY/formperma/pf1lCZ1zZrihaToyRI1TVjQpgmPe48jJ2e--Ort7gRU",
        "cor": "#3182ce",  # Azul
    },
    "epis": {
        "titulo": "2. CHECKLIST EPIs",
        "url_dados": "https://sheet.zohopublic.com/sheet/publishedsheet/28ea5dda3561dc00f67462cc85a3637c2940a1ce9dc222f5aa1d8732ce6ddd4c?type=grid&download=csv",
        "url_form": "https://forms.zohopublic.com/teclogforms/form/CheckListdeEscadadeMo/formperma/ugeL1bWQGcY5yVwqAPMg1eYS6l9MSII3riUT2bG4dcU",
        "cor": "#319795",  # Verde água
    },
    "veiculos": {
        "titulo": "3. CHECKLIST VEÍCULOS",
        "url_dados": "https://sheet.zohopublic.com/sheet/publishedsheet/67964af9a3a2ae4e416c5aaf6b3507dce12e146ea12621af862de7f390b19ac0?type=grid&download=csv",
        "url_form": "https://forms.zohopublic.com/teclogforms/form/checklist/formperma/7ymOCgVcvOXyXFaeaYYkJKNvVUpv6frRMRlx8pKrDic",
        "cor": "#dd6b20",  # Laranja
    },
}

VALORES_OK = {"SIM", "OK", "LIBERADO"}
VALORES_NOK = {"NÃO", "NAO", "NOK", "BLOQUEADO"}

# Nomes-base de colunas que nunca devem aparecer no painel (metadados do Zoho,
# assinatura em branco, ou qualquer versão crua de "status checklist" vinda do
# sheet — o status exibido é sempre recalculado por nós, então a versão bruta
# deve ser descartada mesmo que apareça uma única vez, tipo "status checklist1")
COLUNAS_SEMPRE_REMOVER = {
    "endereço ip",
    "endereco ip",
    "assinatura",
    "assinatura do responsável",
    "assinatura do responsavel",
    "status checklist",
    "adicionado às",
    "adicionado as",
}
# Colunas que devem existir só uma vez: se vier duplicada (ex: "turno.1"),
# mantém a primeira e descarta as demais
COLUNAS_UNICA_OCORRENCIA = {"turno"}


def _nome_base(col):
    """Remove sufixos de duplicata que o pandas adiciona (.1, .2, ou um número
    colado no final), mas preserva perguntas legítimas que terminam em '?'."""
    if col.strip().endswith("?"):
        return col
    return re.sub(r"\.?\d+$", "", col).strip()


def parse_data_flexivel(serie):
    """Interpreta a data corretamente não importa o formato que o Zoho exportou
    (01/07/2026, 2026-07-01, 1/7/2026, com ou sem hora junto).
    Trata separadamente o formato ISO (yyyy-mm-dd), que é ano-mês-dia sempre,
    do formato brasileiro (dd/mm/aaaa), pois em algumas versões do pandas o
    parâmetro dayfirst confunde as duas coisas e troca dia com mês."""
    s = serie.astype(str).str.strip()
    resultado = pd.Series(pd.NaT, index=serie.index, dtype="datetime64[ns]")

    mask_iso = s.str.match(r"^\d{4}-\d{1,2}-\d{1,2}")
    if mask_iso.any():
        resultado.loc[mask_iso] = pd.to_datetime(
            s[mask_iso], format="mixed", dayfirst=False, errors="coerce"
        )

    mask_resto = ~mask_iso
    if mask_resto.any():
        resultado.loc[mask_resto] = pd.to_datetime(
            s[mask_resto], format="mixed", dayfirst=True, errors="coerce"
        )

    return resultado


def limpar_colunas_indesejadas(df):
    """Remove colunas de metadado/lixo e duplicatas indevidas do sheet."""
    colunas_remover = []
    vistas = set()
    for col in df.columns:
        base = _nome_base(col)
        if base in COLUNAS_SEMPRE_REMOVER:
            colunas_remover.append(col)
            continue
        if base in COLUNAS_UNICA_OCORRENCIA:
            if base in vistas:
                colunas_remover.append(col)
                continue
            vistas.add(base)
    return df.drop(columns=colunas_remover, errors="ignore")


def reordenar_colunas(df, colunas_perguntas):
    """Coloca identificação (Data, Turno, Responsável/Nome, Placa) primeiro,
    depois as perguntas, e a coluna de status por último."""
    colunas_status = ["status checklist"] if "status checklist" in df.columns else []
    colunas_id = [c for c in df.columns if c not in colunas_perguntas and c not in colunas_status]

    prioridade = ["data", "turno", "responsável", "responsavel", "nome", "placa"]
    ordenadas_id, usados = [], set()
    for chave in prioridade:
        for c in colunas_id:
            if c in usados:
                continue
            if chave in c:
                ordenadas_id.append(c)
                usados.add(c)
    for c in colunas_id:
        if c not in usados:
            ordenadas_id.append(c)

    ordem_final = ordenadas_id + colunas_perguntas + colunas_status
    return df[ordem_final]

# =========================================================
# BARRA DE PREENCHIMENTO — um botão por checklist, lado a lado
# =========================================================
st.markdown(
    "<p style='text-align:center; color:#4A5568; font-weight:bold; margin-top:-10px;'>📝 Preencher um checklist agora:</p>",
    unsafe_allow_html=True,
)
col_b1, col_b2, col_b3 = st.columns(3)
with col_b1:
    st.link_button(
        "🧰 Ferramentas", CHECKLISTS["ferramentas"]["url_form"], use_container_width=True
    )
with col_b2:
    st.link_button("🦺 EPIs", CHECKLISTS["epis"]["url_form"], use_container_width=True)
with col_b3:
    st.link_button(
        "🚛 Veículos", CHECKLISTS["veiculos"]["url_form"], use_container_width=True
    )
st.markdown("<hr style='margin-top:10px;'>", unsafe_allow_html=True)


# =========================================================
# FUNÇÕES DE APOIO
# =========================================================
@st.cache_data(ttl=30)
def puxar_dados(url):
    """Busca o CSV publicado no Zoho Sheet e padroniza colunas/valores."""
    try:
        res = requests.get(url, verify=False, timeout=15)
        df = pd.read_csv(io.StringIO(res.text))

        # Padroniza o nome das colunas eliminando espaços e deixando minúsculo
        df.columns = [str(c).strip().lower() for c in df.columns]

        # Padroniza Turno e Data sem deixar o Python "traduzir" letras
        for col in df.columns:
            if "turno" in col:
                df[col] = (
                    df[col].astype(str).str.upper().str.replace("TURNO", "").str.strip()
                )
            if "data" in col:
                # Faz o parse real da data (aceita 01/07/2026, 2026-07-01, 1/7/2026,
                # com ou sem hora junto) e normaliza tudo para o mesmo formato
                # dd/mm/aaaa. Isso evita que o mesmo dia apareça como valores
                # diferentes no filtro só porque cada sheet grava num formato.
                datas_parseadas = parse_data_flexivel(df[col])
                data_formatada = datas_parseadas.dt.strftime("%d/%m/%Y")
                # Se não conseguir interpretar a data, mantém o texto original
                # em vez de descartar a linha
                df[col] = data_formatada.where(datas_parseadas.notna(), df[col].astype(str).str.strip())

        df = limpar_colunas_indesejadas(df)
        return df
    except Exception as e:
        st.session_state.setdefault("erros_carregamento", []).append(str(e))
        return pd.DataFrame()


def identificar_colunas_perguntas(df):
    """Toda pergunta do checklist termina com '?'. Isso identifica
    automaticamente as colunas que devem entrar no cálculo do status,
    mesmo que o Zoho renomeie colunas duplicadas (ex: '...?.1')."""
    return [c for c in df.columns if c.strip().endswith("?")]


def calcular_status(df):
    """Cria (ou recalcula) a coluna 'status checklist' com base em todas
    as colunas de pergunta: OK se todas estiverem em VALORES_OK, senão NOK."""
    colunas_perguntas = identificar_colunas_perguntas(df)
    if not colunas_perguntas:
        return df, []

    def linha_ok(row):
        respostas = [str(v).upper().strip() for v in row]
        return all(r in VALORES_OK for r in respostas)

    df = df.copy()
    df["status checklist"] = df[colunas_perguntas].apply(
        lambda row: "OK" if linha_ok(row) else "NOK", axis=1
    )
    df = reordenar_colunas(df, colunas_perguntas)
    return df, colunas_perguntas


def estilizar_tabela(val):
    """Aplica cores de farol: verde para OK, vermelho para NOK."""
    val_str = str(val).upper().strip()
    if val_str in VALORES_OK:
        return "background-color: #C6F6D5; color: #22543D; font-weight: bold;"
    elif val_str in VALORES_NOK:
        return "background-color: #FED7D7; color: #742A2A; font-weight: bold;"
    elif val_str == "OK":
        return "background-color: #C6F6D5; color: #22543D; font-weight: bold;"
    elif val_str == "NOK":
        return "background-color: #FED7D7; color: #742A2A; font-weight: bold;"
    return ""


def criar_grafico_linha_limpo(df, cor_linha):
    if df.empty:
        return
    col_d = next((c for c in df.columns if "data" in c), None)
    if not col_d:
        return

    df_g = df.groupby(col_d).size().reset_index(name="Total")
    df_g = df_g.sort_values(by=col_d, ascending=True)

    linha = alt.Chart(df_g).mark_line(color=cor_linha, strokeWidth=3).encode(
        x=alt.X(f"{col_d}:N", title="Dias Anteriores"),
        y=alt.Y("Total:Q", title="Qtd Total"),
        tooltip=[col_d, "Total"],
    )
    pontos = alt.Chart(df_g).mark_point(color=cor_linha, size=60, filled=True).encode(
        x=alt.X(f"{col_d}:N"),
        y=alt.Y("Total:Q"),
        tooltip=[col_d, "Total"],
    )
    texto = alt.Chart(df_g).mark_text(
        align="center", baseline="bottom", dy=-10, fontSize=12, fontWeight="bold", color="#2D3748"
    ).encode(
        x=alt.X(f"{col_d}:N"),
        y=alt.Y("Total:Q"),
        text="Total:Q",
    )

    st.altair_chart((linha + pontos + texto).properties(height=180), use_container_width=True)


def processar_bloco_operacional(df_bruto, chave, data_sel, turno_sel, busca):
    cfg = CHECKLISTS[chave]
    titulo, cor_grafico = cfg["titulo"], cfg["cor"]

    st.markdown(
        f"<h3 style='color: #1A365D; margin-top: 25px; border-bottom: 2px solid #E2E8F0; padding-bottom: 5px;'>{titulo}</h3>",
        unsafe_allow_html=True,
    )

    if df_bruto.empty:
        st.warning(f"Sem dados cadastrados para {titulo}.")
        return

    df, colunas_perguntas = calcular_status(df_bruto)

    col_d = next((c for c in df.columns if "data" in c), None)
    col_t = next((c for c in df.columns if "turno" in c), None)

    df_filtrado = df.copy()
    if col_d:
        df_filtrado = df_filtrado[df_filtrado[col_d] == data_sel]
    if col_t and turno_sel != "TODOS":
        df_filtrado = df_filtrado[df_filtrado[col_t] == turno_sel]

    # Filtro de busca livre (responsável / nome / placa) em qualquer coluna de texto
    if busca:
        colunas_texto = [c for c in df_filtrado.columns if c not in colunas_perguntas]
        mask = pd.Series(False, index=df_filtrado.index)
        for c in colunas_texto:
            mask = mask | df_filtrado[c].astype(str).str.contains(busca, case=False, na=False)
        df_filtrado = df_filtrado[mask]

    total_realizados = len(df_filtrado)
    total_ok = (df_filtrado["status checklist"] == "OK").sum() if total_realizados else 0
    total_nok = (df_filtrado["status checklist"] == "NOK").sum() if total_realizados else 0
    pct_conformidade = (total_ok / total_realizados * 100) if total_realizados else 0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("📋 Total Realizado", total_realizados)
    m2.metric("✅ OK", int(total_ok))
    m3.metric("❌ NOK", int(total_nok))
    m4.metric("📈 Conformidade", f"{pct_conformidade:.0f}%")

    col_tab, col_graf = st.columns([2, 1])
    with col_tab:
        # A ordem das colunas já vem definida por reordenar_colunas() dentro de calcular_status
        st.dataframe(
            df_filtrado.style.map(estilizar_tabela),
            use_container_width=True,
            height=230,
        )
    with col_graf:
        st.markdown(
            "<p style='text-align: center; font-weight: bold; color: #4A5568; margin-bottom: 2px;'>📈 Tendência de Preenchimento Diário</p>",
            unsafe_allow_html=True,
        )
        criar_grafico_linha_limpo(df, cor_grafico)


# =========================================================
# CARREGAMENTO DOS DADOS
# =========================================================
dados = {chave: puxar_dados(cfg["url_dados"]) for chave, cfg in CHECKLISTS.items()}

# =========================================================
# BARRA SUPERIOR: FILTROS GLOBAIS + ATUALIZAR
# =========================================================
todas_datas = set()
todos_turnos = set()
for df in dados.values():
    if df.empty:
        continue
    col_d = next((c for c in df.columns if "data" in c), None)
    col_t = next((c for c in df.columns if "turno" in c), None)
    if col_d:
        todas_datas.update(df[col_d].dropna().unique())
    if col_t:
        todos_turnos.update([str(t) for t in df[col_t].dropna().unique() if str(t).strip() != ""])

if todas_datas:
    def _chave_ordenacao_data(valor):
        """Ordena pelo valor real da data (dd/mm/aaaa); joga para o fim
        qualquer texto que não seja uma data válida."""
        try:
            return datetime.strptime(valor, "%d/%m/%Y")
        except (ValueError, TypeError):
            return datetime.min

    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        lista_datas = sorted(todas_datas, key=_chave_ordenacao_data, reverse=True)
        data_sel = st.selectbox("📅 Selecione a Data para Monitorar:", lista_datas)
    with col2:
        lista_turnos = ["TODOS"] + sorted(todos_turnos)
        turno_sel = st.selectbox("🕒 Selecione o Turno:", lista_turnos)
    with col3:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔄 Atualizar Agora", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    busca = st.text_input("🔎 Buscar por responsável / nome / placa (opcional):")

    st.caption(f"Última atualização: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')} — dados renovam automaticamente a cada 30s")

    processar_bloco_operacional(dados["ferramentas"], "ferramentas", data_sel, turno_sel, busca)
    processar_bloco_operacional(dados["epis"], "epis", data_sel, turno_sel, busca)
    processar_bloco_operacional(dados["veiculos"], "veiculos", data_sel, turno_sel, busca)

else:
    st.info("Aguardando sincronização com os bancos de dados do Zoho Forms...")
    if st.button("🔄 Tentar novamente"):
        st.cache_data.clear()
        st.rerun()
