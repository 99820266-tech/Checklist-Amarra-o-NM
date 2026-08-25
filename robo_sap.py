import io
import re
from datetime import datetime
import altair as alt
import pandas as pd
import requests
import streamlit as st
import urllib3

# Tenta importar o autorun para TV (caso instalado)
try:
  from streamlit_autorun import autorun

  HAS_AUTORUN = True
except ImportError:
  HAS_AUTORUN = False

# Desativa os avisos de certificado SSL para a rede da empresa
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configura a página para o modo estendido ideal para TVs operacionais
st.set_page_config(
    page_title="Painel Amarração NM", layout="wide", page_icon="✅"
)

# Atualização automática para TVs (30 segundos)
if HAS_AUTORUN:
  autorun(interval=30000, key="auto_refresh_tv")

st.markdown(
    "<h1 style='text-align: center; color: #1A365D;'>AMARRAÇÃO NM - CONTROLE DE"
    " CHECKLISTS</h1>",
    unsafe_allow_html=True,
)

# =========================================================
# CONFIGURAÇÃO DOS 3 CHECKLISTS
# =========================================================
CHECKLISTS = {
    "ferramentas": {
        "titulo": "1. CHECKLIST FERRAMENTAS",
        "url_dados": (
            "https://sheet.zohopublic.com/sheet/publishedsheet/819a86b9667e21ca4cdd5454628503e800e1c6920c83c592df3314e7f5033605?type=grid&download=csv"
        ),
        "url_form": (
            "https://forms.zohopublic.com/teclogforms/form/ChecklistCintoTipoParaquedistaTalabarteY/formperma/pf1lCZ1zZrihaToyRI1TVjQpgmPe48jJ2e--Ort7gRU"
        ),
        "cor": "#3182ce",
    },
    "epis": {
        "titulo": "2. CHECKLIST EPIs",
        "url_dados": (
            "https://sheet.zohopublic.com/sheet/publishedsheet/8806b346c7ce4e2cac7dda07de0eb585096d36753d757f473e54777612103528?type=grid&download=csv"
        ),
        "url_form": (
            "https://forms.zohopublic.com/teclogforms/form/CheckListdeEscadadeMo/formperma/ugeL1bWQGcY5yVwqAPMg1eYS6l9MSII3riUT2bG4dcU"
        ),
        "cor": "#319795",
    },
    "veiculos": {
        "titulo": "3. CHECKLIST VEÍCULOS",
        "url_dados": (
            "https://sheet.zohopublic.com/sheet/publishedsheet/5a8d5ba1474f2a8fb755a8a42e32c9588a14e71e71137613fd09fb00b899d813?type=grid&download=csv"
        ),
        "url_form": (
            "https://forms.zohopublic.com/teclogforms/form/checklist/formperma/7ymOCgVcvOXyXFaeaYYkJKNvVUpv6frRMRlx8pKrDic"
        ),
        "cor": "#dd6b20",
    },
}

VALORES_OK = {
    "SIM",
    "OK",
    "LIBERADO",
    "NA",
    "N/A",
    "N.A.",
    "N/A.",
    "NÃO APLICÁVEL",
    "NAO APLICAVEL",
    "NÃO SE APLICA",
    "NAO SE APLICA",
    "NONE",
    "NAN",
}
VALORES_NOK = {"NÃO", "NAO", "NOK", "BLOQUEADO"}
VALORES_NA = {
    "NA",
    "N/A",
    "N.A.",
    "N/A.",
    "NÃO APLICÁVEL",
    "NAO APLICAVEL",
    "NÃO SE APLICA",
    "NAO SE APLICA",
    "NONE",
    "NAN",
    "",
}

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
COLUNAS_UNICA_OCORRENCIA = {"turno"}


def _nome_base(col):
  if col.strip().endswith("?"):
    return col
  return re.sub(r"\.?\d+$", "", col).strip()


def parse_data_flexivel(serie):
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
  colunas_remover = []
  vistas = set()
  for col in df.columns:
    base = _nome_base(col)
    if base in COLUNAS_SEMPRE_REMOVER or base.startswith("unnamed"):
      colunas_remover.append(col)
      continue
    if base in COLUNAS_UNICA_OCORRENCIA:
      if base in vistas:
        colunas_remover.append(col)
        continue
      vistas.add(base)
  return df.drop(columns=colunas_remover, errors="ignore")


def identificar_colunas_perguntas(df):
  colunas_perguntas = []
  todas_respostas_validas = (VALORES_OK | VALORES_NOK) - {"NONE", "NAN"}

  for c in df.columns:
    c_clean = c.strip().lower()

    if any(
        k in c_clean
        for k in [
            "data",
            "turno",
            "nome",
            "responsável",
            "responsavel",
            "placa",
            "obs",
            "observa",
            "motivo",
            "justificativa",
        ]
    ):
      continue

    if c_clean.endswith("?"):
      colunas_perguntas.append(c)
      continue

    valores_unicos = df[c].dropna().astype(str).str.upper().str.strip().unique()
    if len(valores_unicos) > 0 and any(
        v in todas_respostas_validas for v in valores_unicos
    ):
      colunas_perguntas.append(c)

  return colunas_perguntas


def reordenar_colunas(df, colunas_perguntas):
  colunas_status = (
      ["status checklist"] if "status checklist" in df.columns else []
  )
  colunas_obs = [
      c
      for c in df.columns
      if any(k in c for k in ["obs", "observa", "motivo", "justificativa"])
  ]

  colunas_id = [
      c
      for c in df.columns
      if c not in colunas_perguntas
      and c not in colunas_status
      and c not in colunas_obs
  ]

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

  ordem_final = ordenadas_id + colunas_perguntas + colunas_status + colunas_obs
  return df[ordem_final]


# =========================================================
# BARRA DE PREENCHIMENTO
# =========================================================
st.markdown(
    "<p style='text-align:center; color:#4A5568; font-weight:bold;"
    " margin-top:-10px;'>📝 Preencher um checklist agora:</p>",
    unsafe_allow_html=True,
)
col_b1, col_b2, col_b3 = st.columns(3)
with col_b1:
  st.link_button(
      "🧰 Ferramentas",
      CHECKLISTS["ferramentas"]["url_form"],
      use_container_width=True,
  )
with col_b2:
  st.link_button(
      "🦺 EPIs", CHECKLISTS["epis"]["url_form"], use_container_width=True
  )
with col_b3:
  st.link_button(
      "🚛 Veículos",
      CHECKLISTS["veiculos"]["url_form"],
      use_container_width=True,
  )
st.markdown("<hr style='margin-top:10px;'>", unsafe_allow_html=True)


# =========================================================
# FUNÇÕES DE APOIO
# =========================================================
@st.cache_data(ttl=30)
def puxar_dados(url):
  try:
    res = requests.get(url, verify=False, timeout=15)
    df = pd.read_csv(io.StringIO(res.text), keep_default_na=False)

    df.columns = [str(c).strip().lower() for c in df.columns]

    df = df.replace(
        {
            "": "NA",
            None: "NA",
            "None": "NA",
            "none": "NA",
            "nan": "NA",
            "NaN": "NA",
        }
    )

    for col in df.columns:
      if "turno" in col:
        df[col] = (
            df[col]
            .astype(str)
            .str.upper()
            .str.replace("TURNO", "")
            .str.strip()
        )
      if "data" in col:
        datas_parseadas = parse_data_flexivel(df[col])
        data_formatada = datas_parseadas.dt.strftime("%d/%m/%Y")
        df[col] = data_formatada.where(
            datas_parseadas.notna(), df[col].astype(str).str.strip()
        )

    df = limpar_colunas_indesejadas(df)
    return df
  except Exception as e:
    st.session_state.setdefault("erros_carregamento", []).append(str(e))
    return pd.DataFrame()


def calcular_status(df):
  colunas_perguntas = identificar_colunas_perguntas(df)
  if not colunas_perguntas:
    return df, []

  def linha_ok(row):
    respostas = [str(v).upper().strip() for v in row]
    return not any(r in VALORES_NOK for r in respostas)

  df = df.copy()
  df["status checklist"] = df[colunas_perguntas].apply(
      lambda row: "OK" if linha_ok(row) else "NOK", axis=1
  )
  df = reordenar_colunas(df, colunas_perguntas)
  return df, colunas_perguntas


def estilizar_tabela(val):
  val_str = str(val).upper().strip()
  if val_str in VALORES_NOK or val_str == "NOK":
    return "background-color: #FED7D7; color: #742A2A; font-weight: bold;"
  elif val_str in VALORES_NA:
    return "background-color: #EDF2F7; color: #718096; font-weight: bold;"
  elif val_str in VALORES_OK or val_str == "OK":
    return "background-color: #C6F6D5; color: #22543D; font-weight: bold;"
  return ""


def criar_grafico_linha_limpo(df, cor_linha):
  if df.empty:
    return
  col_d = next((c for c in df.columns if "data" in c), None)
  if not col_d:
    return

  df_g = df.groupby(col_d).size().reset_index(name="Total")
  df_g = df_g.sort_values(by=col_d, ascending=True)

  linha = (
      alt.Chart(df_g)
      .mark_line(color=cor_linha, strokeWidth=3)
      .encode(
          x=alt.X(f"{col_d}:N", title="Dias Anteriores"),
          y=alt.Y("Total:Q", title="Qtd Total"),
          tooltip=[col_d, "Total"],
      )
  )
  pontos = (
      alt.Chart(df_g)
      .mark_point(color=cor_linha, size=60, filled=True)
      .encode(
          x=alt.X(f"{col_d}:N"),
          y=alt.Y("Total:Q"),
          tooltip=[col_d, "Total"],
      )
  )
  texto = (
      alt.Chart(df_g)
      .mark_text(
          align="center",
          baseline="bottom",
          dy=-10,
          fontSize=12,
          fontWeight="bold",
          color="#2D3748",
      )
      .encode(
          x=alt.X(f"{col_d}:N"),
          y=alt.Y("Total:Q"),
          text="Total:Q",
      )
  )

  st.altair_chart(
      (linha + pontos + texto).properties(height=180),
      use_container_width=True,
  )


def processar_bloco_operacional(df_bruto, chave, data_sel, turno_sel, busca):
  cfg = CHECKLISTS[chave]
  titulo, cor_grafico = cfg["titulo"], cfg["cor"]

  st.markdown(
      f"<h3 style='color: #1A365D; margin-top: 25px; border-bottom: 2px solid"
      f" #E2E8F0; padding-bottom: 5px;'>{titulo}</h3>",
      unsafe_allow_html=True,
  )

  if df_bruto.empty:
    st.warning(f"Sem dados cadastrados para {titulo}.")
    return pd.DataFrame()

  df, colunas_perguntas = calcular_status(df_bruto)

  col_d = next((c for c in df.columns if "data" in c), None)
  col_t = next((c for c in df.columns if "turno" in c), None)

  df_filtrado = df.copy()
  if col_d:
    df_filtrado = df_filtrado[df_filtrado[col_d] == data_sel]
  if col_t and turno_sel != "TODOS":
    df_filtrado = df_filtrado[df_filtrado[col_t] == turno_sel]

  if busca:
    colunas_texto = [
        c for c in df_filtrado.columns if c not in colunas_perguntas
    ]
    mask = pd.Series(False, index=df_filtrado.index)
    for c in colunas_texto:
      mask = mask | df_filtrado[c].astype(str).str.contains(
          busca, case=False, na=False
      )
    df_filtrado = df_filtrado[mask]

  total_realizados = len(df_filtrado)
  total_ok = (
      (df_filtrado["status checklist"] == "OK").sum() if total_realizados else 0
  )
  total_nok = (
      (df_filtrado["status checklist"] == "NOK").sum()
      if total_realizados
      else 0
  )
  pct_conformidade = (
      (total_ok / total_realizados * 100) if total_realizados else 0
  )

  m1, m2, m3, m4 = st.columns(4)
  m1.metric("📋 Total Realizado", total_realizados)
  m2.metric("✅ OK", int(total_ok))
  m3.metric("❌ NOK", int(total_nok))
  m4.metric("📈 Conformidade", f"{pct_conformidade:.0f}%")

  col_tab, col_graf = st.columns([2, 1])
  with col_tab:
    st.dataframe(
        df_filtrado.style.map(estilizar_tabela),
        use_container_width=True,
        height=230,
    )
  with col_graf:
    st.markdown(
        "<p style='text-align: center; font-weight: bold; color: #4A5568;"
        " margin-bottom: 2px;'>📈 Tendência de Preenchimento Diário</p>",
        unsafe_allow_html=True,
    )
    criar_grafico_linha_limpo(df, cor_grafico)

  return df_filtrado


# =========================================================
# CARREGAMENTO DOS DADOS
# =========================================================
dados = {
    chave: puxar_dados(cfg["url_dados"]) for chave, cfg in CHECKLISTS.items()
}

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
    todos_turnos.update(
        [str(t) for t in df[col_t].dropna().unique() if str(t).strip() != ""]
    )

if todas_datas:

  def _chave_ordenacao_data(valor):
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

  busca = st.text_input(
      "🔎 Buscar por responsável / nome / placa / observação (opcional):"
  )

  st.caption(
      f"Última atualização: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')} —"
      " dados renovam automaticamente a cada 30s"
  )

  # PROCESSAMENTO E EXIBIÇÃO DAS 3 ÁREAS
  df_f = processar_bloco_operacional(
      dados["ferramentas"], "ferramentas", data_sel, turno_sel, busca
  )
  df_e = processar_bloco_operacional(
      dados["epis"], "epis", data_sel, turno_sel, busca
  )
  df_v = processar_bloco_operacional(
      dados["veiculos"], "veiculos", data_sel, turno_sel, busca
  )

  # =========================================================
  # EXPORTAÇÃO DE DADOS
  # =========================================================
  st.markdown("---")
  st.markdown("### 📥 Exportar Relatórios")

  buffer_geral = io.BytesIO()
  with pd.ExcelWriter(buffer_geral, engine="openpyxl") as writer:
    if not df_f.empty:
      df_f.to_excel(writer, sheet_name="Ferramentas", index=False)
    if not df_e.empty:
      df_e.to_excel(writer, sheet_name="EPIs", index=False)
    if not df_v.empty:
      df_v.to_excel(writer, sheet_name="Veiculos", index=False)

  st.download_button(
      label="📊 Baixar Todos os Dados do Dia (.xlsx)",
      data=buffer_geral.getvalue(),
      file_name=f"Checklists_Completos_{data_sel.replace('/','-')}.xlsx",
      mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      use_container_width=True,
  )

else:
  st.info("Aguardando sincronização com os bancos de dados do Zoho Forms...")
  if st.button("🔄 Tentar novamente"):
    st.cache_data.clear()
    st.rerun()
