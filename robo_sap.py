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


# =========================================================
# TABELA HTML COM QUEBRA DE TEXTO (substitui st.dataframe)
# =========================================================
COLS_TEXTO_LONGO = ("obs", "observa", "motivo", "justificativa")


def _cor_celula(col_lower, valor):
  val_str = str(valor).upper().strip()
  if val_str in VALORES_NOK or val_str == "NOK":
    return "background-color:#FED7D7;color:#742A2A;font-weight:bold;"
  elif val_str in VALORES_NA:
    return "background-color:#EDF2F7;color:#718096;font-weight:bold;"
  elif val_str in VALORES_OK or val_str == "OK":
    return "background-color:#C6F6D5;color:#22543D;font-weight:bold;"
  return ""


def renderizar_tabela_html(df, altura=260):
  if df.empty:
    st.info("Nenhum registro para os filtros selecionados.")
    return

  colunas_html = []
  for c in df.columns:
    c_lower = str(c).lower()
    eh_texto_longo = any(k in c_lower for k in COLS_TEXTO_LONGO)
    # Cabeçalho quebra o texto em até 4 linhas (altura fixa) em vez de
    # cortar com "..." — assim dá pra ler a pergunta inteira sem estourar
    # a altura da tabela.
    largura_cab = (
        "min-width:200px;max-width:260px;white-space:normal;"
        if eh_texto_longo
        else "min-width:160px;max-width:190px;white-space:normal;"
        "word-break:break-word;"
    )
    titulo_col = str(c).upper().replace("'", "&#39;")
    colunas_html.append(
        f"<th style='{largura_cab}'>{titulo_col}</th>"
    )

  linhas_html = []
  for _, row in df.iterrows():
    celulas = []
    for c in df.columns:
      c_lower = str(c).lower()
      eh_texto_longo = any(k in c_lower for k in COLS_TEXTO_LONGO)
      wrap_style = (
          "white-space:normal;word-break:break-word;min-width:200px;"
          "max-width:260px;"
          if eh_texto_longo
          else "white-space:nowrap;min-width:160px;max-width:190px;"
          "overflow:hidden;text-overflow:ellipsis;"
      )
      cor_style = _cor_celula(c_lower, row[c])
      titulo_completo = str(row[c]).replace("'", "&#39;")
      celulas.append(
          f"<td style='{wrap_style}{cor_style}' title='{titulo_completo}'>"
          f"{row[c]}</td>"
      )
    linhas_html.append(f"<tr>{''.join(celulas)}</tr>")

  html = f"""
  <div style="max-height:{altura}px; overflow-y:auto; overflow-x:auto;
              border:1px solid #CBD5E0; border-radius:6px;">
    <table style="border-collapse:collapse; width:max-content; min-width:100%;
                   font-size:12.5px; font-family: 'Source Sans Pro', sans-serif;
                   table-layout:auto;">
      <thead>
        <tr style="position:sticky; top:0; background:#2D3748; color:white;
                   z-index:1;">
          {''.join(colunas_html)}
        </tr>
      </thead>
      <tbody>
        {''.join(linhas_html)}
      </tbody>
    </table>
  </div>
  <style>
    td, th {{ padding: 5px 8px; border: 1px solid #E2E8F0; text-align: left; vertical-align: top; line-height: 1.3; }}
    thead th {{ max-height: 90px; }}
  </style>
  """
  st.markdown(html, unsafe_allow_html=True)


def criar_grafico_semanal(df, cor_linha):
  """Gráfico limpo mostrando apenas os últimos 7 dias com registro."""
  if df.empty:
    return
  col_d = next((c for c in df.columns if "data" in c), None)
  if not col_d:
    return

  df_g = df.groupby(col_d).size().reset_index(name="Total")
  df_g["_ord"] = pd.to_datetime(df_g[col_d], format="%d/%m/%Y", errors="coerce")
  df_g = df_g.sort_values("_ord")
  df_g = df_g.tail(7)  # só a última semana com dados

  if df_g.empty:
    return

  ordem_datas = df_g[col_d].tolist()

  barras = (
      alt.Chart(df_g)
      .mark_bar(color=cor_linha, cornerRadiusTopLeft=4, cornerRadiusTopRight=4, size=26)
      .encode(
          x=alt.X(
              f"{col_d}:N",
              title=None,
              sort=ordem_datas,
              axis=alt.Axis(labelAngle=0, labelFontSize=11, domain=False, tickSize=0),
          ),
          y=alt.Y(
              "Total:Q",
              title=None,
              axis=alt.Axis(grid=False, labels=False, ticks=False),
          ),
          tooltip=[alt.Tooltip(f"{col_d}:N", title="Data"), alt.Tooltip("Total:Q", title="Qtd")],
      )
  )
  rotulos = (
      alt.Chart(df_g)
      .mark_text(dy=-8, fontSize=12, fontWeight="bold", color="#2D3748")
      .encode(
          x=alt.X(f"{col_d}:N", sort=ordem_datas),
          y="Total:Q",
          text="Total:Q",
      )
  )

  st.altair_chart(
      (barras + rotulos)
      .properties(height=170)
      .configure_view(strokeWidth=0)
      .configure_axis(domainColor="#E2E8F0"),
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
    return pd.DataFrame(), []

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
    renderizar_tabela_html(df_filtrado, altura=230)
  with col_graf:
    st.markdown(
        "<p style='text-align: center; font-weight: bold; color: #4A5568;"
        " margin-bottom: 2px;'>📈 Histórico (última semana)</p>",
        unsafe_allow_html=True,
    )
    criar_grafico_semanal(df, cor_grafico)

  return df_filtrado, colunas_perguntas


def montar_resumo_nok(resultados, data_sel, turno_sel):
  """Monta um resumo consolidado das ocorrências NOK de todos os checklists."""
  linhas_resumo = []

  for chave, (df_filtrado, colunas_perguntas) in resultados.items():
    if df_filtrado.empty or not colunas_perguntas:
      continue
    titulo_curto = CHECKLISTS[chave]["titulo"].split(". ", 1)[-1]
    col_resp = next(
        (
            c
            for c in df_filtrado.columns
            if any(k in c for k in ["responsável", "responsavel", "nome", "placa"])
        ),
        None,
    )
    col_obs = next(
        (
            c
            for c in df_filtrado.columns
            if any(k in c for k in ["obs", "observa", "motivo", "justificativa"])
        ),
        None,
    )

    nok_df = df_filtrado[df_filtrado["status checklist"] == "NOK"]
    for _, row in nok_df.iterrows():
      itens_falhos = [
          c for c in colunas_perguntas
          if str(row[c]).upper().strip() in VALORES_NOK
      ]
      linhas_resumo.append({
          "checklist": titulo_curto,
          "responsável / identificação": row[col_resp] if col_resp else "-",
          "item(ns) reprovado(s)": "; ".join(itens_falhos) if itens_falhos else "-",
          "observação": row[col_obs] if col_obs else "-",
      })

  st.markdown("### 🚨 Resumo de Ocorrências NOK")
  st.caption(f"Filtro atual: {data_sel} — Turno: {turno_sel}")

  if not linhas_resumo:
    st.success("Nenhuma ocorrência NOK encontrada para os filtros selecionados. ✅")
    return

  df_resumo = pd.DataFrame(linhas_resumo)
  st.error(f"{len(df_resumo)} ocorrência(s) NOK encontrada(s).")
  renderizar_tabela_html(df_resumo, altura=220)


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

  # PROCESSAMENTO DAS 3 ÁREAS (guarda resultado para montar o resumo)
  resultados = {}
  resultados["ferramentas"] = processar_bloco_operacional(
      dados["ferramentas"], "ferramentas", data_sel, turno_sel, busca
  )
  resultados["epis"] = processar_bloco_operacional(
      dados["epis"], "epis", data_sel, turno_sel, busca
  )
  resultados["veiculos"] = processar_bloco_operacional(
      dados["veiculos"], "veiculos", data_sel, turno_sel, busca
  )

  st.markdown("---")
  montar_resumo_nok(resultados, data_sel, turno_sel)

else:
  st.info("Aguardando sincronização com os bancos de dados do Zoho Forms...")
  if st.button("🔄 Tentar novamente"):
    st.cache_data.clear()
    st.rerun()
