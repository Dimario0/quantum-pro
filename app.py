import streamlit as st
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import apimoex
from datetime import datetime, timedelta

# --- КОНФИГУРАЦИЯ СТРАНИЦЫ ---
st.set_page_config(page_title="QUANTUM TRADER PRO", layout="wide", page_icon="🇷🇺")

st.markdown("""
    <style>
    .stApp { background-color: #0E1117; color: #FAFAFA; }
    .stMetric { background-color: #1E1E1E; padding: 15px; border-radius: 8px; border: 1px solid #333; }
    </style>
    """, unsafe_allow_html=True)

# Кэшируем данные, чтобы приложение летало
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_stock_data(ticker, days):
    try:
        with requests.Session() as session:
            start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            req_columns = ('TRADEDATE', 'OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOLUME')
            data = apimoex.get_board_history(session, ticker, start=start_date, board='TQBR', columns=req_columns)
            if not data: return None
            
            df = pd.DataFrame(data)
            df.columns = [str(c).upper() for c in df.columns]
            df.rename(columns={'TRADEDATE': 'Date', 'OPEN': 'Open', 'HIGH': 'High', 'LOW': 'Low', 'CLOSE': 'Close', 'VOLUME': 'Volume'}, inplace=True)
            df.dropna(subset=['Open', 'High', 'Low', 'Close'], inplace=True)
            
            df['Date'] = pd.to_datetime(df['Date'])
            df.set_index('Date', inplace=True)
            df.sort_index(inplace=True)
            
            if len(df) < 20: return None # Минимум 20 дней для расчетов

            # Безопасный расчет индикаторов (не крашится на молодых акциях)
            try: df.ta.ema(length=20, append=True)
            except: pass
            try: df.ta.ema(length=50, append=True)
            except: pass
            try: df.ta.rsi(length=14, append=True)
            except: pass
            try: df.ta.macd(append=True)
            except: pass
            try: df.ta.atr(length=14, append=True)
            except: pass
            try: df.ta.vwma(length=20, append=True)
            except: pass
            
            df['Vol_Avg'] = df['Volume'].rolling(window=20).mean()
            df['Anomaly'] = df['Volume'] > (df['Vol_Avg'] * 2.5)

            df = df.ffill().fillna(0)
            return df
    except:
        return None

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_context_data(days):
    try:
        with requests.Session() as session:
            start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            imoex = apimoex.get_board_history(session, 'IMOEX', start=start_date, board='SNDX', columns=('TRADEDATE', 'CLOSE'))
            usd = apimoex.get_board_history(session, 'USD000UTSTOM', start=start_date, board='CETS', columns=('TRADEDATE', 'CLOSE'))
            
            df_idx = pd.DataFrame(imoex) if imoex else None
            df_usd = pd.DataFrame(usd) if usd else None
            
            if df_idx is not None and not df_idx.empty:
                df_idx.columns = [str(c).upper() for c in df_idx.columns]
                df_idx.rename(columns={'TRADEDATE': 'Date', 'CLOSE': 'Close'}, inplace=True)
                df_idx['Date'] = pd.to_datetime(df_idx['Date'])
                df_idx.set_index('Date', inplace=True)
                
            if df_usd is not None and not df_usd.empty:
                df_usd.columns = [str(c).upper() for c in df_usd.columns]
                df_usd.rename(columns={'TRADEDATE': 'Date', 'CLOSE': 'Close'}, inplace=True)
                df_usd['Date'] = pd.to_datetime(df_usd['Date'])
                df_usd.set_index('Date', inplace=True)
                
            return df_idx, df_usd
    except:
        return None, None

def run_backtest(data, initial_cap, risk_pct):
    cap = initial_cap
    trades = []
    equity = [initial_cap] * min(50, len(data))
    in_pos = False
    
    macd_h = [c for c in data.columns if c.startswith('MACDh')]
    vwma = [c for c in data.columns if c.startswith('VWMA')]
    atr_col = [c for c in data.columns if c.startswith('ATR')]
    
    # Если нужных индикаторов нет, отменяем бэктест во избежание ошибки
    if not macd_h or not vwma or not atr_col or 'EMA_50' not in data.columns:
        return equity, pd.DataFrame(columns=['Дата', 'PnL', 'Итог'])

    mh, vw, atr = macd_h[0], vwma[0], atr_col[0]

    for i in range(50, len(data)):
        row = data.iloc[i]
        
        if not in_pos and row['Close'] > row['EMA_50'] and row[mh] > 0 and row['Close'] > row[vw]:
            in_pos = True
            entry_p = row['Close']
            sl = entry_p - (row[atr] * 2)
            tp = entry_p + (row[atr] * 4)
            
            risk_rub = cap * (risk_pct / 100)
            pos_size = int(risk_rub / abs(entry_p - sl)) if abs(entry_p - sl) > 0 else 0
            entry_date = data.index[i]

        elif in_pos:
            if row['Low'] <= sl or row['High'] >= tp or i == len(data)-1:
                exit_p = sl if row['Low'] <= sl else (tp if row['High'] >= tp else row['Close'])
                pnl = (exit_p - entry_p) * pos_size
                cap += pnl
                trades.append({'Дата': entry_date.strftime('%Y-%m-%d'), 'PnL': pnl, 'Итог': 'TP 🟢' if exit_p >= tp else 'SL 🔴'})
                in_pos = False
        
        equity.append(cap)
        
    return equity, pd.DataFrame(trades, columns=['Дата', 'PnL', 'Итог'])

# --- ИНТЕРФЕЙС ---
with st.sidebar:
    st.title("⚙️ Настройки")
    ticker = st.text_input("Тикер (MOEX)", value="SBER").upper().strip()
    period = st.selectbox("История", ["1 Год", "3 Года", "5 Лет"], index=0)
    days_map = {"1 Год": 365, "3 Года": 1095, "5 Лет": 1825}
    
    st.divider()
    capital = st.number_input("Начальный депозит (₽)", value=100000, step=10000)
    risk = st.slider("Риск на сделку (%)", 0.5, 5.0, 1.5)

with st.spinner('Синхронизация с серверами MOEX...'):
    df_stock = fetch_stock_data(ticker, days_map[period])
    df_idx, df_usd = fetch_context_data(days_map[period])

if df_stock is not None and not df_stock.empty:
    last = df_stock.iloc[-1]
    
    mh = [c for c in df_stock.columns if c.startswith('MACDh')]
    vw = [c for c in df_stock.columns if c.startswith('VWMA')]
    atr_col = [c for c in df_stock.columns if c.startswith('ATR')]
    
    score = sum([
        1 if 'EMA_50' in df_stock.columns and last['Close'] > last['EMA_50'] else 0,
        1 if mh and last[mh[0]] > 0 else 0,
        1 if vw and last['Close'] > last[vw[0]] else 0
    ])
    
    # 1. МЕТРИКИ
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Цена Акции", f"{last['Close']:.2f} ₽")
    if df_usd is not None and not df_usd.empty: 
        m2.metric("USD/RUB", f"{df_usd.iloc[-1]['Close']:.2f} ₽")
    else:
        m2.metric("USD/RUB", "Нет данных")
        
    m3.metric("Крупный капитал", "АНОМАЛИЯ 🐳" if last['Anomaly'] else "Норма")
    m4.metric("Торговый Сигнал", "STRONG BUY 🚀" if score == 3 else "HOLD ⚖️" if score > 1 else "SELL 🐻")

    # 2. ГРАФИК
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
    
    fig.add_trace(go.Candlestick(x=df_stock.index, open=df_stock['Open'], high=df_stock['High'], low=df_stock['Low'], close=df_stock['Close'], name='Цена'), row=1, col=1)
    if 'EMA_50' in df_stock.columns:
        fig.add_trace(go.Scatter(x=df_stock.index, y=df_stock['EMA_50'], line=dict(color='#FF6D00', width=1.5), name='EMA 50'), row=1, col=1)
    
    anomalies = df_stock[df_stock['Anomaly']]
    fig.add_trace(go.Scatter(x=anomalies.index, y=anomalies['High']*1.02, mode='markers', marker=dict(color='#00E5FF', size=8, symbol='diamond'), name='Всплеск объема'), row=1, col=1)

    colors = ['#ef5350' if c < o else '#26a69a' for o, c in zip(df_stock['Open'], df_stock['Close'])]
    fig.add_trace(go.Bar(x=df_stock.index, y=df_stock['Volume'], marker_color=colors, name='Объем'), row=2, col=1)

    fig.update_layout(height=700, template="plotly_dark", xaxis_rangeslider_visible=False, showlegend=False)
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
    st.plotly_chart(fig, use_container_width=True)

    # 3. ПЛАН И КНОПКА СОХРАНЕНИЯ
    st.subheader("🎯 Актуальный план:")
    plan_col, save_col = st.columns([3, 1])
    
    with plan_col:
        if score == 3 and atr_col:
            st.success(f"**🟢 ВХОД:** {last['Close']:.2f} ₽ &nbsp;|&nbsp; **🔴 СТОП-ЛОСС:** {last['Close'] - last[atr_col[0]]*2:.2f} ₽ &nbsp;|&nbsp; **🚀 ТЕЙК-ПРОФИТ:** {last['Close'] + last[atr_col[0]]*4:.2f} ₽")
        else:
            st.info("💡 Условия для идеального входа сейчас не выполнены. Ждем подтверждения тренда и объемов.")
            
    with save_col:
        # Вот функционал выгрузки и сохранения
        csv = df_stock.to_csv().encode('utf-8')
        st.download_button(
            label="💾 Скачать данные (CSV)", 
            data=csv, 
            file_name=f"{ticker}_quantum_data.csv", 
            mime="text/csv", 
            use_container_width=True
        )

    # 4. БЭКТЕСТ
    st.divider()
    with st.expander("🧪 РЕЗУЛЬТАТЫ БЭКТЕСТА (Симуляция стратегии)", expanded=False):
        equity, trades = run_backtest(df_stock, capital, risk)
        
        b_col1, b_col2, b_col3 = st.columns(3)
        final_profit = equity[-1] - capital
        b_col1.metric("Чистая прибыль", f"{final_profit:,.0f} ₽", f"{(final_profit/capital)*100:.1f}%")
        b_col2.metric("Всего сделок", len(trades))
        
        if len(trades) > 0:
            winrate = (len(trades[trades['PnL'] > 0]) / len(trades)) * 100
            b_col3.metric("Успешных сделок", f"{winrate:.1f}%")
        else:
            b_col3.metric("Успешных сделок", "0%")
        
        st.line_chart(equity)
        if not trades.empty:
            st.dataframe(trades.style.map(lambda x: 'color: #00E676;' if x > 0 else 'color: #FF1744;' if x < 0 else '', subset=['PnL']), use_container_width=True)

else:
    st.error("❌ Ошибка загрузки. Убедитесь, что тикер введен верно (например, SBER) и биржа не проводит тех. работы.")
