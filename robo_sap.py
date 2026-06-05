import streamlit as st
import pandas as pd
import requests
import io
import urllib3
import altair as alt

# Desativa os avisos de certificado SSL para a rede da empresa
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configura a página para o modo estendido ideal para TVs operacionais
st.set_page_config(page_title="Painel Amarração NM", layout="wide")

st.markdown("<h1 style='text-align: center; color: #1A365D;'>AMARRAÇÃO NM - CONTROLE DE CHECKLISTS</h1>", unsafe_allow_html=True)

# --- LINKS DOS 3 CHECKLISTS (ZOHO) ---
URL_FERRAMENTAS = "https://sheet.zohopublic.com/sheet/publishedsheet/85de8ed310d210a609d3206d8c3eff7ee871bc9bf5eb4c81c7225ff5edef496c?type=grid&download=csv"
URL_EPIS = "https://sheet.zohopublic.com/sheet/publishedsheet/28ea5dda3561dc00f67462cc85a3637c2940a1ce9dc222f5aa1d8732ce6ddd4c?type=grid&download=csv"
URL_VEICULOS = "https://sheet.zohopublic.com/sheet/publishedsheet/67964af9a3a2ae4e416c5aaf6b3507dce12e146ea12621af862de7f390b19ac0?type=grid&download=csv"

@st.cache_data(ttl=30)
def puxar_dados(url):
    try:
        res = requests.get(url, verify=False)
        df = pd.read_csv(io.StringIO(res.text))
        
        # Padroniza o nome das colunas eliminando espaços e deixando minúsculo
        df.columns = [str(c).strip().lower() for c in df.columns]
        
        # Padroniza dados de Turno e Data sem deixar o Python traduzir a letra 'A'
        for col in df.columns:
            if 'turno' in col:
                # Extrai apenas a letra final (A, B ou C) e força como string limpa
                df[col] = df[col].astype(str).str.upper().str.replace('TURNO', '').str.strip()
            if 'data' in col:
                df[col] = df[col].astype(str).str.strip()
                
        return df
    except Exception as e:
        return pd.DataFrame()

# Carrega e trata os dados
df_ferramentas = puxar_dados(URL_FERRAMENTAS)
df_epis = puxar_dados(URL_EPIS)
df_veiculos = puxar_dados(URL_VEICULOS)

# Função padrão para aplicar as cores do farol (Verde para OK, Vermelho para NOK)
def estilizar_tabela(val):
    val_str = str(val).upper().strip()
    if val_str in ['SIM', 'OK', 'LIBERADO']:
        return 'background-color: #C6F6D5; color: #22543D; font-weight: bold;'
    elif val_str in ['NÃO', 'NAO', 'NOK', 'BLOQUEADO']:
        return 'background-color: #FED7D7; color: #742A2A; font-weight: bold;'
    return ''

# Função de gráfico: Linha de tendência limpa e ultra-objetiva
def criar_grafico_linha_limpo(df, cor_linha):
    if df.empty:
        return
    col_d = [c for c in df.columns if 'data' in c][0]
    
    # Agrupa apenas por dia para saber o total geral realizado
    df_g = df.groupby(col_d).size().reset_index(name='Total')
    df_g = df_g.sort_values(by=col_d, ascending=True)
    
    # Desenha a linha de evolução
    linha = alt.Chart(df_g).mark_line(color=cor_linha, strokeWidth=3).encode(
        x=alt.X(f'{col_d}:N', title='Dias Anteriores'),
        y=alt.Y('Total:Q', title='Qtd Total'),
        tooltip=[col_d, 'Total']
    )
    
    # Adiciona os pontos com os números em cima para leitura direta
    pontos = alt.Chart(df_g).mark_point(color=cor_linha, size=60, filled=True).encode(
        x=alt.X(f'{col_d}:N'),
        y=alt.Y('Total:Q'),
        tooltip=[col_d, 'Total']
    )
    
    texto = alt.Chart(df_g).mark_text(align='center', baseline='bottom', dy=-10, fontSize=12, fontWeight='bold', color='#2D3748').encode(
        x=alt.X(f'{col_d}:N'),
        y=alt.Y('Total:Q'),
        text='Total:Q'
    )
    
    grafico_final = (linha + pontos + texto).properties(height=180)
    st.altair_chart(grafico_final, use_container_width=True)

# Processamento de cada bloco com a tabela e o novo gráfico
def processar_bloco_operacional(df, titulo, data_sel, turno_sel, cor_grafico):
    st.markdown(f"<h3 style='color: #1A365D; margin-top: 30px; border-bottom: 2px solid #E2E8F0; padding-bottom: 5px;'>{titulo}</h3>", unsafe_allow_html=True)
    
    if not df.empty:
        col_d = [c for c in df.columns if 'data' in c][0]
        col_t = [c for c in df.columns if 'turno' in c][0]
        
        if turno_sel == "TODOS":
            df_filtrado = df[df[col_d] == data_sel].copy()
        else:
            df_filtrado = df[(df[col_d] == data_sel) & (df[col_t] == turno_sel)].copy()
        
        col_status = [c for c in df.columns if 'status' in c]
        total_realizados = len(df_filtrado)
        total_ok = 0
        total_nok = 0
        
        if col_status and total_realizados > 0:
            status_col = col_status[0]
            total_ok = df_filtrado[status_col].astype(str).str.upper().str.strip().isin(['SIM', 'OK', 'LIBERADO']).sum()
            total_nok = df_filtrado[status_col].astype(str).str.upper().str.strip().isin(['NÃO', 'NAO', 'NOK', 'BLOQUEADO']).sum()
        
        st.markdown(
            f"📊 **Filtro atual:** `{turno_sel}` &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"📋 Total Realizado: `{total_realizados}` &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"✅ OK: <span style='color:#2F855A;font-weight:bold;'>{total_ok}</span> &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"❌ NOK: <span style='color:#C53030;font-weight:bold;'>{total_nok}</span>", 
            unsafe_allow_html=True
        )
        
        col_tab, col_graf = st.columns([2, 1])
        
        with col_tab:
            st.dataframe(df_filtrado.style.map(estilizar_tabela), use_container_width=True, height=230)
            
        with col_graf:
            st.markdown("<p style='text-align: center; font-weight: bold; color: #4A5568; margin-bottom: 2px;'>📈 Tendência de Preenchimento Diário</p>", unsafe_allow_html=True)
            criar_grafico_linha_limpo(df, cor_grafico)
    else:
        st.warning(f"Sem dados cadastrados para {titulo}.")

if not df_ferramentas.empty:
    # --- FILTROS GLOBAIS NO TOPO ---
    col1, col2 = st.columns(2)
    with col1:
        lista_datas = sorted(df_ferramentas['data'].unique(), reverse=True)
        data_sel = st.selectbox("📅 Selecione a Data para Monitorar:", lista_datas)
    with col2:
        # Pega as opções reais do banco, remove vazios e ordena como texto puro (A, B, C)
        turnos_reais = sorted([str(t) for t in df_ferramentas['turno'].unique() if str(t).strip() != ''])
        lista_turnos = ["TODOS"] + turnos_reais
        
        turno_sel = st.selectbox("🕒 Selecione o Turno:", lista_turnos)

    # --- PROCESSAMENTO DOS 3 BLOCO OPERACIONAIS ---
    processar_bloco_operacional(df_ferramentas, "1. CHECKLIST FERRAMENTAS", data_sel, turno_sel, "#3182ce") # Azul
    processar_bloco_operacional(df_epis, "2. CHECKLIST EPIs", data_sel, turno_sel, "#319795")         # Verde Água
    processar_bloco_operacional(df_veiculos, "3. CHECKLIST VEÍCULOS", data_sel, turno_sel, "#dd6b20")     # Laranja

else:
    st.info("Aguardando sincronização com os bancos de dados do Zoho Forms...")
