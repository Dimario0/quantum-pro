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
        self.ticker = ticker.upper().replace(".ME", "").strip()

    def fetch_data(self, days):
        try:
            with requests.Session() as session:
                start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
                data = apimoex.get_board_history(session, self.ticker, start=start_date, board='TQBR')
                if not data: return None
                df = pd.DataFrame(data)
                df.columns = df.columns.str.upper()
                df.rename(columns={'TRADEDATE': 'Date', 'OPEN': 'Open', 'HIGH': 'High', 'LOW': 'Low', 'CLOSE': 'Close', 'VOLUME': 'Volume'}, inplace=True)
                df['Date'] = pd.to_datetime(df['Date'])
                df.set_index('Date', inplace=True)
                # Индикаторы
                df.ta.ema(length=20, append=True); df.ta.ema(length=50, append=True); df.ta.ema(length=200, append=True)
                df.ta.rsi(length=14, append=True); df.ta.atr(length=14, append=True); df.ta.vwma(length=20, append=True)
                df.ta.macd(append=True); df.ta.bbands(append=True)
                df.fillna(0, inplace=True)
                return df
        except: return None

    def fetch_market_context(self, days):
        """Загрузка внешних факторов: Brent и USD/RUB через MOEX"""
        try:
            with requests.Session() as session:
                start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
                # USD/RUB (Фьючерс или курс) и IMOEX
                imoex = apimoex.get_board_history(session, 'IMOEX', start=start_date, board='SNDX')
                usd = apimoex.get_board_history(session, 'USD000UTSTOM', start=start_date, board='CETS') # Курс доллар/рубль
                
                df_imoex = pd.DataFrame(imoex).set_index(pd.to_datetime(pd.DataFrame(imoex)['TRADEDATE'])) if imoex else None
                df_usd = pd.DataFrame(usd).set_index(pd.to_datetime(pd.DataFrame(usd)['TRADEDATE'])) if usd else None
                
                return df_imoex, df_usd
        except: return None, None

    def analyze_context(self, data, imoex_data, usd_data):
        last = data.iloc[-1]
        
        # Анализ IMOEX
        imoex_status = "Нейтрально"
        if imoex_data is not None:
            imoex_last = imoex_data.iloc[-1]['CLOSE']
            imoex_prev = imoex_data.iloc[-5]['CLOSE'] # Сравнение с ценой неделю назад
            imoex_status = "РОСТ 📈" if imoex_last > imoex_prev else "ПАДЕНИЕ 📉"

        # Анализ Валюты
        usd_status = "Стабилен"
        if usd_data is not None:
            usd_curr = usd_data.iloc[-1]['CLOSE']
            usd_prev = usd_data.iloc[-5]['CLOSE']
            if usd_curr > usd_prev * 1.02: usd_status = "ШОК (Девальвация) ⚠️"
            elif usd_curr < usd_prev * 0.98: usd_status = "Укрепление рубля 💎"

        # Технический скоринг
        macd_hist = [col for col in data.columns if col.startswith('MACDh_')][0]
        vwma_col = [col for col in data.columns if col.startswith('VWMA')][0]
        
        t_score = 0
        if last['Close'] > last['EMA_50']: t_score += 0.4
        if last['Close'] > last[vwma_col]: t_score += 0.3
        if last[macd_hist] > 0: t_score += 0.3
        
        return t_score, imoex_status, usd_status

# --- ИНТЕРФЕЙС ---
with st.sidebar:
    st.title("⚙️ Настройки")
    ticker_input = st.text_input("Тикер акции РФ", value="SBER")
    period = st.selectbox("Период", ["1 Год", "3 Года", "5 Лет"], index=0)
    days = {"1 Год": 365, "3 Года": 1095, "5 Лет": 1825}[period]

st.title(f"⚡ QUANTUM ALGO PRO: {ticker_input.upper()}")

engine = QuantEngine(ticker_input)
with st.spinner('Сбор межрыночных данных...'):
    data = engine.fetch_data(days)
    imoex_df, usd_df = engine.fetch_market_context(days)

if data is not None:
    score, mkt_trend, currency_status = engine.analyze_context(data, imoex_df, usd_df)

    # Виджеты контекста
    st.markdown("### 🌐 Внешний фон (Межрыночный анализ)")
    c1, c2, c3 = st.columns(3)
    with c1: st.metric("Индекс Мосбиржи", mkt_trend)
    with c2: st.metric("Курс USD/RUB", f"{usd_df.iloc[-1]['CLOSE'] if usd_df is not None else 'N/A'} ₽", currency_status)
    with c3: 
        sentiment = "ПОЗИТИВНЫЙ ✅" if score > 0.6 and "РОСТ" in mkt_trend else "РИСКОВАННЫЙ ❌"
        st.metric("Общий сентимент", sentiment)

    # График с наложением Индекса
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
    
    # Свечи акции
    fig.add_trace(go.Candlestick(x=data.index, open=data['Open'], high=data['High'], low=data['Low'], close=data['Close'], name=ticker_input), row=1, col=1)
    
    # Линия Индекса (на ту же ось для корреляции)
    if imoex_df is not None:
        # Нормализуем индекс, чтобы он влез в масштаб цены
        norm_imoex = imoex_df['CLOSE'] * (data['Close'].mean() / imoex_df['CLOSE'].mean())
        fig.add_trace(go.Scatter(x=imoex_df.index, y=norm_imoex, line=dict(color='rgba(255,255,255,0.4)', width=1, dash='dot'), name='Индекс (норм.)'), row=1, col=1)

    # RSI
    fig.add_trace(go.Scatter(x=data.index, y=data['RSI_14'], line=dict(color='#E040FB'), name='RSI'), row=2, col=1)
    
    fig.update_layout(height=600, template="plotly_dark", showlegend=False)
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
    st.plotly_chart(fig, use_container_width=True)

    # Вердикт
    st.divider()
    if sentiment == "ПОЗИТИВНЫЙ ✅":
        st.success(f"🔥 ИДЕАЛЬНЫЕ УСЛОВИЯ: Акция {ticker_input} в аптренде, рынок растет, валютный шок отсутствует.")
    else:
        st.warning(f"⚠️ ВНИМАНИЕ: Технические сигналы могут быть ложными из-за слабого внешнего фона или волатильности валюты.")

else:
    st.error("Ошибка загрузки данных.")
