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
                
                # Расчет индикаторов
                df.ta.ema(length=50, append=True)
                df.ta.rsi(length=14, append=True)
                df.ta.macd(append=True)
                df.ta.vwma(length=20, append=True)
                df.fillna(method='ffill', inplace=True)
                return df
        except Exception as e:
            st.error(f"Ошибка загрузки {self.ticker}: {e}")
            return None

    def fetch_market_context(self, days):
        try:
            with requests.Session() as session:
                start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
                
                # Индекс Мосбиржи
                imoex_raw = apimoex.get_board_history(session, 'IMOEX', start=start_date, board='SNDX')
                # Курс Доллара (ТОМ)
                usd_raw = apimoex.get_board_history(session, 'USD000UTSTOM', start=start_date, board='CETS')
                
                df_imoex = pd.DataFrame(imoex_raw).set_index(pd.to_datetime(pd.DataFrame(imoex_raw)['TRADEDATE'])) if imoex_raw else None
                df_usd = pd.DataFrame(usd_raw).set_index(pd.to_datetime(pd.DataFrame(usd_raw)['TRADEDATE'])) if usd_raw else None
                
                return df_imoex, df_usd
        except Exception as e:
            st.warning(f"Контекст рынка временно недоступен: {e}")
            return None, None

    def analyze_context(self, data, imoex_data, usd_data):
        if data is None or len(data) < 10: return 0, "Нет данных", "Нет данных"
        
        last = data.iloc[-1]
        
        # 1. Анализ Индекса
        imoex_status = "Нейтрально"
        if imoex_data is not None and len(imoex_data) > 5:
            imoex_curr = imoex_data.iloc[-1]['CLOSE']
            imoex_prev = imoex_data.iloc[-5]['CLOSE']
            imoex_status = "РОСТ 📈" if imoex_curr > imoex_prev else "ПАДЕНИЕ 📉"

        # 2. Анализ Валюты
        usd_status = "Стабилен"
        usd_val = "N/A"
        if usd_data is not None and len(usd_data) > 5:
            usd_curr = usd_data.iloc[-1]['CLOSE']
            usd_prev = usd_data.iloc[-5]['CLOSE']
            usd_val = f"{usd_curr:.2f}"
            if usd_curr > usd_prev * 1.015: usd_status = "ДЕВАЛЬВАЦИЯ ⚠️"
            elif usd_curr < usd_prev * 0.985: usd_status = "УКРЕПЛЕНИЕ 💎"

        # 3. Технический скоринг
        score = 0
        macd_hist_col = [col for col in data.columns if col.startswith('MACDh_')]
        vwma_col = [col for col in data.columns if col.startswith('VWMA')]
        
        if last['Close'] > last['EMA_50']: score += 0.4
        if vwma_col and last['Close'] > last[vwma_col[0]]: score += 0.3
        if macd_hist_col and last[macd_hist_col[0]] > 0: score += 0.3
        
        return score, imoex_status, usd_status, usd_val

# --- ИНТЕРФЕЙС ---
with st.sidebar:
    st.title("⚙️ Настройки")
    ticker_input = st.text_input("Тикер (напр. SBER или GAZP)", value="SBER")
    period = st.selectbox("Период", ["1 Год", "3 Года", "5 Лет"], index=0)
    days_count = {"1 Год": 365, "3 Года": 1095, "5 Лет": 1825}[period]
    st.divider()
    st.info("Бот анализирует акции РФ в связке с индексом IMOEX и курсом Доллара.")

engine = QuantEngine(ticker_input)

with st.spinner('Анализируем рынок...'):
    data = engine.fetch_data(days_count)
    imoex_df, usd_df = engine.fetch_market_context(days_count)

if data is not None and not data.empty:
    score, mkt_trend, currency_status, usd_price = engine.analyze_context(data, imoex_df, usd_df)

    # Виджеты
    st.markdown("### 🌐 Межрыночные индикаторы")
    c1, c2, c3 = st.columns(3)
    c1.metric("Индекс Мосбиржи", mkt_trend)
    c2.metric("Курс USD/RUB", f"{usd_price} ₽", currency_status)
    
    sentiment = "ПОЗИТИВНЫЙ ✅" if score > 0.6 and "РОСТ" in mkt_trend else "РИСКОВАННЫЙ ❌"
    c3.metric("Общий сентимент", sentiment)

    # График
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
    
    # Свечи
    fig.add_trace(go.Candlestick(
        x=data.index, open=data['Open'], high=data['High'], low=data['Low'], close=data['Close'], name=ticker_input
    ), row=1, col=1)
    
    # Наложение Индекса (нормализованное)
    if imoex_df is not None:
        ratio = data['Close'].mean() / imoex_df['CLOSE'].mean()
        fig.add_trace(go.Scatter(
            x=imoex_df.index, y=imoex_df['CLOSE'] * ratio, 
            line=dict(color='rgba(255,255,255,0.3)', width=1, dash='dot'), name='Индекс (корр.)'
        ), row=1, col=1)

    # RSI
    fig.add_trace(go.Scatter(x=data.index, y=data['RSI_14'], line=dict(color='#E040FB')), row=2, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="red", row=2, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="green", row=2, col=1)

    fig.update_layout(height=700, template="plotly_dark", showlegend=False, xaxis_rangeslider_visible=False)
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
    st.plotly_chart(fig, use_container_width=True)

    # Вердикт
    st.divider()
    if sentiment == "ПОЗИТИВНЫЙ ✅":
        st.success(f"💎 Сильный сигнал по {ticker_input}. Техника и рынок подтверждают рост.")
    else:
        st.warning(f"⚠️ Осторожно. Внешний фон (Индекс или Валюта) не подтверждают уверенную покупку.")
else:
    st.error("Не удалось получить данные по тикеру. Убедитесь, что тикер написан верно (SBER, LKOH, GAZP).")
