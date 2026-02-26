import streamlit as st
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import apimoex
from datetime import datetime, timedelta

st.set_page_config(page_title="QUANTUM TRADER PRO", layout="wide", page_icon="🇷🇺")

# --- СТИЛИ ---
st.markdown("""
    <style>
    .stApp { background-color: #0E1117; color: #FAFAFA; }
    .metric-card { background-color: #1E1E1E; padding: 15px; border-radius: 10px; border: 1px solid #333; text-align: center; }
    </style>
    """, unsafe_allow_html=True)

class QuantEngine:
    def __init__(self, ticker):
        self.ticker = ticker.upper().strip()

    def fetch_data(self, days):
        try:
            with requests.Session() as session:
                start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
                data = apimoex.get_board_history(session, self.ticker, start=start_date, board='TQBR')
                
                if not data:
                    return None
                
                df = pd.DataFrame(data)
                df.columns = [col.upper() for col in df.columns]
                
                rename_map = {
                    'TRADEDATE': 'Date', 'OPEN': 'Open', 'HIGH': 'High', 
                    'LOW': 'Low', 'CLOSE': 'Close', 'VOLUME': 'Volume'
                }
                df.rename(columns=rename_map, inplace=True)
                
                required = ['Open', 'High', 'Low', 'Close', 'Volume']
                if not all(col in df.columns for col in required):
                    return None

                df['Date'] = pd.to_datetime(df['Date'])
                df.set_index('Date', inplace=True)
                df.sort_index(inplace=True)
                
                # --- АНАЛИЗ ОБЪЕМОВ ---
                # Считаем средний объем за 20 дней
                df['Vol_Avg'] = df['Volume'].rolling(window=20).mean()
                # Аномалия - если текущий объем > среднего в 2.5 раза
                df['Anomaly'] = df['Volume'] > (df['Vol_Avg'] * 2.5)
                
                # Индикаторы
                df.ta.ema(length=50, append=True)
                df.ta.rsi(length=14, append=True)
                df.fillna(method='ffill', inplace=True)
                return df
        except Exception as e:
            st.error(f"Ошибка: {e}")
            return None

# --- ИНТЕРФЕЙС ---
with st.sidebar:
    st.title("⚙️ Настройки")
    ticker_input = st.text_input("Тикер (напр. SBER)", value="SBER")
    period = st.selectbox("Период", ["1 Год", "3 Года", "5 Лет"])
    days_count = {"1 Год": 365, "3 Года": 1095, "5 Лет": 1825}[period]

engine = QuantEngine(ticker_input)

with st.spinner('Анализ аномалий и загрузка MOEX...'):
    data = engine.fetch_data(days_count)

if data is not None and not data.empty:
    # Создаем график: 1. Цена, 2. Объем
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                        vertical_spacing=0.05, row_heights=[0.7, 0.3],
                        subplot_titles=(f'Цена {ticker_input}', 'Объем торгов'))
    
    # 1. Свечной график
    fig.add_trace(go.Candlestick(
        x=data.index, open=data['Open'], high=data['High'], 
        low=data['Low'], close=data['Close'], name='Цена'
    ), row=1, col=1)

    # 2. Подсветка аномалий на графике цены (синие точки над свечами)
    anomalies = data[data['Anomaly'] == True]
    fig.add_trace(go.Scatter(
        x=anomalies.index, y=anomalies['High'] * 1.02,
        mode='markers', marker=dict(color='#00BFFF', size=10, symbol='diamond'),
        name='Аномальный Объем'
    ), row=1, col=1)

    # 3. Гистограмма объемов
    colors = ['#ef5350' if row['Open'] > row['Close'] else '#26a69a' for _, row in data.iterrows()]
    fig.add_trace(go.Bar(
        x=data.index, y=data['Volume'], name='Объем',
        marker_color=colors, opacity=0.5
    ), row=2, col=1)

    # Средняя линия объема
    fig.add_trace(go.Scatter(
        x=data.index, y=data['Vol_Avg'], 
        line=dict(color='white', width=1, dash='dot'), name='Средний объем (20)'
    ), row=2, col=1)

    fig.update_layout(height=800, template="plotly_dark", xaxis_rangeslider_visible=False, showlegend=False)
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
    
    st.plotly_chart(fig, use_container_width=True)

    # --- ИНФОРМАЦИОННЫЙ БЛОК ---
    st.markdown("### 📊 Анализ китов")
    last_anomaly = data[data['Anomaly'] == True].tail(3)
    
    if not last_anomaly.empty:
        st.info(f"💡 Последние аномальные всплески объема зафиксированы: {', '.join(last_anomaly.index.strftime('%d.%m.%Y'))}. "
                "Это может указывать на активный сбор или раздачу позиции крупным игроком.")
    else:
        st.write("Крупных аномалий в объемах за последнее время не обнаружено.")
        
else:
    st.error("Ошибка данных. Проверьте тикер.")
