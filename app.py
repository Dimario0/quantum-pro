import streamlit as st
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import apimoex
from datetime import datetime, timedelta

st.set_page_config(page_title="QUANTUM TRADER PRO", layout="wide", page_icon="🇷🇺")

st.markdown("""
    <style>
    .stApp { background-color: #0E1117; color: #FAFAFA; }
    .metric-card { background-color: #1E1E1E; padding: 15px; border-radius: 10px; border: 1px solid #333; text-align: center; }
    .stButton>button { width: 100%; background: linear-gradient(45deg, #26A69A, #2962FF); color: white; border: none; height: 50px; font-size: 18px; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

class QuantEngine:
    def __init__(self, ticker):
        self.ticker = ticker.upper().replace(".ME", "").strip()

    def fetch_data(self, days=400):
        try:
            with requests.Session() as session:
                start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
                req_columns = ('TRADEDATE', 'OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOLUME')
                
                data = apimoex.get_board_history(session, self.ticker, start=start_date, board='TQBR', columns=req_columns)
                
                if not data:
                    st.warning(f"Биржа не вернула данные по тикеру {self.ticker}. Проверьте правильность (например: SBER).")
                    return None
                
                df = pd.DataFrame(data)
                df.columns = df.columns.str.upper()
                df.rename(columns={'TRADEDATE': 'Date', 'OPEN': 'Open', 'HIGH': 'High', 'LOW': 'Low', 'CLOSE': 'Close', 'VOLUME': 'Volume'}, inplace=True)
                df.dropna(subset=['Open', 'High', 'Low', 'Close'], inplace=True)
                df['Date'] = pd.to_datetime(df['Date'])
                df.set_index('Date', inplace=True)

                if len(df) < 30:
                    st.warning("Слишком мало данных для анализа (нужно минимум 30 дней торгов).")
                    return None

                # Индикаторы
                df.ta.ema(length=20, append=True)
                df.ta.ema(length=50, append=True)
                df.ta.ema(length=200, append=True)
                df.ta.rsi(length=14, append=True)
                df.ta.bbands(length=20, std=2, append=True)
                df.ta.atr(length=14, append=True)
                df.ta.macd(fast=12, slow=26, signal=9, append=True)
                
                df.fillna(0, inplace=True)
                return df
                
        except Exception as e:
            st.error(f"Сбой подключения: {e}")
            return None

    def generate_trading_plan(self, data, signal_type, capital, risk_pct):
        last_close = data['Close'].iloc[-1]
        atr = data['ATRr_14'].iloc[-1]
        if atr <= 0: atr = last_close * 0.02

        if "BUY" in signal_type:
            entry = last_close
            stop_loss = entry - (atr * 1.5)
            take_profit_1 = entry + (atr * 2.0)
            take_profit_2 = entry + (atr * 4.0)
        else:
            entry = last_close
            stop_loss = entry + (atr * 1.5)
            take_profit_1 = entry - (atr * 2.0)
            take_profit_2 = entry - (atr * 4.0)

        risk_money = capital * (risk_pct / 100)
        risk_per_share = abs(entry - stop_loss)
        position_size = int(risk_money / risk_per_share) if risk_per_share > 0 else 0
        rr_ratio = abs(take_profit_1 - entry) / risk_per_share if risk_per_share > 0 else 0

        return entry, stop_loss, take_profit_1, take_profit_2, position_size, rr_ratio, risk_money

# --- ИНТЕРФЕЙС ---
with st.sidebar:
    st.title("⚙️ PRO Настройки")
    ticker_input = st.text_input("Тикер актива (MOEX)", value="SBER")
    capital = st.number_input("Размер депозита (₽)", value=100000, step=10000)
    risk_pct = st.slider("Допустимый риск (%)", 0.5, 5.0, 1.5)

st.title(f"⚡ QUANTUM ALGO: {ticker_input.upper()}")

engine = QuantEngine(ticker_input)
with st.spinner('Связь с Московской биржей...'):
    data = engine.fetch_data()

if data is not None:
    bb_upper = [col for col in data.columns if col.startswith('BBU')][0]
    bb_lower = [col for col in data.columns if col.startswith('BBL')][0]
    macd_hist_col = [col for col in data.columns if col.startswith('MACDh_')][0]
    macd_line = [col for col in data.columns if col.startswith('MACD_')][0]
    macd_sig = [col for col in data.columns if col.startswith('MACDs_')][0]

    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.05, 
                        row_heights=[0.6, 0.2, 0.2], subplot_titles=('Цена, Тренд (EMA) и Боллинджер', 'MACD (Моментум)', 'RSI'))

    fig.add_trace(go.Candlestick(x=data.index, open=data['Open'], high=data['High'], low=data['Low'], close=data['Close'], name='Цена'), row=1, col=1)
    fig.add_trace(go.Scatter(x=data.index, y=data['EMA_20'], line=dict(color='#2962FF', width=1.5), name='EMA 20'), row=1, col=1)
    fig.add_trace(go.Scatter(x=data.index, y=data['EMA_50'], line=dict(color='#FF6D00', width=1.5), name='EMA 50'), row=1, col=1)
    fig.add_trace(go.Scatter(x=data.index, y=data['EMA_200'], line=dict(color='#AA00FF', width=2, dash='dot'), name='EMA 200'), row=1, col=1)

    colors_macd = ['#26A69A' if val >= 0 else '#EF5350' for val in data[macd_hist_col]]
    fig.add_trace(go.Bar(x=data.index, y=data[macd_hist_col], marker_color=colors_macd, name='MACD Hist'), row=2, col=1)

    fig.add_trace(go.Scatter(x=data.index, y=data['RSI_14'], line=dict(color='#E040FB', width=2), name='RSI'), row=3, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="rgba(239, 83, 80, 0.5)", row=3, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="rgba(38, 166, 154, 0.5)", row=3, col=1)

    fig.update_layout(height=750, template="plotly_dark", hovermode="x unified", margin=dict(l=10, r=10, t=40, b=10))
    fig.update_xaxes(rangeslider_visible=False)
    st.plotly_chart(fig, use_container_width=True)

    # Логика сигналов
    last = data.iloc[-1]
    trend_score = 1 if last['Close'] > last['EMA_50'] > last['EMA_200'] else (-1 if last['Close'] < last['EMA_50'] < last['EMA_200'] else 0)
    mom_score = 1 if last[macd_line] > last[macd_sig] and last[macd_hist_col] > 0 else -1
    rsi_score = 1.5 if last['RSI_14'] < 35 else (-1.5 if last['RSI_14'] > 65 else 0.5)
    
    tech_score = (trend_score * 0.4) + (mom_score * 0.4) + (rsi_score * 0.2)

    if tech_score > 0.6: final_signal = "STRONG BUY"
    elif tech_score > 0.2: final_signal = "BUY"
    elif tech_score < -0.6: final_signal = "STRONG SELL"
    elif tech_score < -0.2: final_signal = "SELL"
    else: final_signal = "HOLD / НЕ ВХОДИТЬ"

    st.divider()
    st.markdown(f"## 🎯 ТОРГОВЫЙ ПЛАН: <span style='color:{'#26A69A' if 'BUY' in final_signal else '#EF5350' if 'SELL' in final_signal else 'gray'};'>{final_signal}</span>", unsafe_allow_html=True)

    if "HOLD" not in final_signal:
        entry, sl, tp1, tp2, pos_size, rr, risk_m = engine.generate_trading_plan(data, final_signal, capital, risk_pct)
        c1, c2, c3 = st.columns(3)
        c1.success(f"**🟢 TAKE PROFIT:**\n\nЦель 1: **{tp1:.2f} ₽**\n\nЦель 2: **{tp2:.2f} ₽**")
        c2.warning(f"**🟡 ВХОД:**\n\nЦена: **{entry:.2f} ₽**\n\nОбъем: **{pos_size} шт.**")
        c3.error(f"**🔴 СТОП-ЛОСС:**\n\nЦена: **{sl:.2f} ₽**\n\nРиск: **-{risk_m:.0f} ₽**")
    else:
        st.write("На рынке сейчас «каша». Лучшая позиция сейчас — находиться в деньгах.")
