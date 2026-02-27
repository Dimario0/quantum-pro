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
    .stMetric { background-color: #1E1E1E; padding: 15px; border-radius: 8px; border: 1px solid #333; }
    </style>
    """, unsafe_allow_html=True)

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
            
            if len(df) < 20: return None

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
                # Считаем тренд Индекса Мосбиржи
                df_idx.ta.ema(length=50, append=True)
                
            if df_usd is not None and not df_usd.empty:
                df_usd.columns = [str(c).upper() for c in df_usd.columns]
                df_usd.rename(columns={'TRADEDATE': 'Date', 'CLOSE': 'Close'}, inplace=True)
                df_usd['Date'] = pd.to_datetime(df_usd['Date'])
                df_usd.set_index('Date', inplace=True)
                
            return df_idx, df_usd
    except:
        return None, None

def run_advanced_backtest(data, df_idx, initial_cap, risk_pct):
    """Продвинутый бэктест: Режим рынка, Шорт, Трейлинг стоп и Комиссии"""
    cap = initial_cap
    trades = []
    equity = [initial_cap] * min(50, len(data))
    
    in_pos = False
    pos_type = None # 'LONG' или 'SHORT'
    entry_p = 0
    pos_size = 0
    
    macd_h = [c for c in data.columns if c.startswith('MACDh')]
    vwma = [c for c in data.columns if c.startswith('VWMA')]
    atr_col = [c for c in data.columns if c.startswith('ATR')]
    
    if not macd_h or not vwma or not atr_col or 'EMA_50' not in data.columns:
        return equity, pd.DataFrame(columns=['Дата', 'Тип', 'Вход', 'Выход', 'PnL', 'Итог'])

    mh, vw, atr = macd_h[0], vwma[0], atr_col[0]
    commission_rate = 0.0005 # 0.05% комиссия брокера

    # Синхронизируем данные Индекса с акцией
    if df_idx is not None and 'EMA_50' in df_idx.columns:
        idx_trend = df_idx['Close'] > df_idx['EMA_50']
        data['Bull_Market'] = idx_trend.reindex(data.index).ffill()
    else:
        data['Bull_Market'] = True

    for i in range(50, len(data)):
        row = data.iloc[i]
        bull_market = row['Bull_Market']
        
        # --- ЛОГИКА ВХОДА ---
        if not in_pos:
            # СИГНАЛ LONG: Рынок растет, Тренд акции вверх, Импульс +, Объемы +
            if bull_market and row['Close'] > row['EMA_50'] and row[mh] > 0 and row['Close'] > row[vw]:
                in_pos = True
                pos_type = 'LONG'
                entry_p = row['Close']
                sl = entry_p - (row[atr] * 2.5) # Даем больше пространства для "дыхания"
                
                risk_rub = cap * (risk_pct / 100)
                pos_size = int(risk_rub / abs(entry_p - sl)) if abs(entry_p - sl) > 0 else 0
                cap -= (entry_p * pos_size * commission_rate) # Списываем комиссию за вход
                entry_date = data.index[i]

            # СИГНАЛ SHORT: Рынок падает, Тренд акции вниз, Импульс -, Объемы продают
            elif not bull_market and row['Close'] < row['EMA_50'] and row[mh] < 0 and row['Close'] < row[vw]:
                in_pos = True
                pos_type = 'SHORT'
                entry_p = row['Close']
                sl = entry_p + (row[atr] * 2.5)
                
                risk_rub = cap * (risk_pct / 100)
                pos_size = int(risk_rub / abs(sl - entry_p)) if abs(sl - entry_p) > 0 else 0
                cap -= (entry_p * pos_size * commission_rate)
                entry_date = data.index[i]

        # --- ЛОГИКА ВЫХОДА (Трейлинг стоп) ---
        elif in_pos:
            exit_p = 0
            reason = ""
            
            if pos_type == 'LONG':
                # Выход если сработал жесткий стоп ИЛИ цена пробила быструю EMA_20 вниз (слом тренда)
                if row['Low'] <= sl:
                    exit_p, reason = sl, "Stop Loss 🔴"
                elif row['Close'] < row['EMA_20']:
                    exit_p, reason = row['Close'], "Trend Exit 🟡"
                    
                if exit_p > 0 or i == len(data)-1:
                    exit_p = exit_p if exit_p > 0 else row['Close']
                    gross_pnl = (exit_p - entry_p) * pos_size
                    comm = exit_p * pos_size * commission_rate
                    net_pnl = gross_pnl - comm
                    cap += gross_pnl - comm # Возвращаем капитал с учетом PnL и комиссии выхода
                    trades.append({'Дата': data.index[i].strftime('%Y-%m-%d'), 'Тип': 'LONG 🟢', 'Вход': entry_p, 'Выход': exit_p, 'PnL': net_pnl, 'Итог': reason})
                    in_pos = False

            elif pos_type == 'SHORT':
                if row['High'] >= sl:
                    exit_p, reason = sl, "Stop Loss 🔴"
                elif row['Close'] > row['EMA_20']:
                    exit_p, reason = row['Close'], "Trend Exit 🟡"
                    
                if exit_p > 0 or i == len(data)-1:
                    exit_p = exit_p if exit_p > 0 else row['Close']
                    gross_pnl = (entry_p - exit_p) * pos_size # В шорте прибыль, когда цена падает
                    comm = exit_p * pos_size * commission_rate
                    net_pnl = gross_pnl - comm
                    cap += gross_pnl - comm
                    trades.append({'Дата': data.index[i].strftime('%Y-%m-%d'), 'Тип': 'SHORT 🔴', 'Вход': entry_p, 'Выход': exit_p, 'PnL': net_pnl, 'Итог': reason})
                    in_pos = False
        
        equity.append(cap)
        
    return equity, pd.DataFrame(trades, columns=['Дата', 'Тип', 'Вход', 'Выход', 'PnL', 'Итог'])

# --- ИНТЕРФЕЙС ---
with st.sidebar:
    st.title("⚙️ Настройки")
    ticker = st.text_input("Тикер (MOEX)", value="SBER").upper().strip()
    period = st.selectbox("История", ["1 Год", "3 Года", "5 Лет"], index=2)
    days_map = {"1 Год": 365, "3 Года": 1095, "5 Лет": 1825}
    
    st.divider()
    capital = st.number_input("Начальный депозит (₽)", value=100000, step=10000)
    risk = st.slider("Риск на сделку (%)", 0.5, 5.0, 1.5)

with st.spinner('Анализ рыночных режимов...'):
    df_stock = fetch_stock_data(ticker, days_map[period])
    df_idx, df_usd = fetch_context_data(days_map[period])

if df_stock is not None and not df_stock.empty:
    last = df_stock.iloc[-1]
    
    mh = [c for c in df_stock.columns if c.startswith('MACDh')]
    vw = [c for c in df_stock.columns if c.startswith('VWMA')]
    atr_col = [c for c in df_stock.columns if c.startswith('ATR')]
    
    bull_market = True
    if df_idx is not None and 'EMA_50' in df_idx.columns:
        bull_market = df_idx.iloc[-1]['Close'] > df_idx.iloc[-1]['EMA_50']
    
    # Расчет статуса
    if bull_market and last['Close'] > last['EMA_50'] and mh and last[mh[0]] > 0 and vw and last['Close'] > last[vw[0]]:
        signal = "STRONG BUY 🟢"
    elif not bull_market and last['Close'] < last['EMA_50'] and mh and last[mh[0]] < 0 and vw and last['Close'] < last[vw[0]]:
        signal = "STRONG SHORT 🔴"
    else:
        signal = "HOLD / CASH ⚖️"
    
    # 1. МЕТРИКИ
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Цена Акции", f"{last['Close']:.2f} ₽")
    m2.metric("Режим Рынка (IMOEX)", "БЫЧИЙ 🐂" if bull_market else "МЕДВЕЖИЙ 🐻")
    m3.metric("Крупный капитал", "АНОМАЛИЯ 🐳" if last['Anomaly'] else "Норма")
    m4.metric("Торговый Сигнал", signal)

    # 2. ГРАФИК
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
    
    fig.add_trace(go.Candlestick(x=df_stock.index, open=df_stock['Open'], high=df_stock['High'], low=df_stock['Low'], close=df_stock['Close'], name='Цена'), row=1, col=1)
    if 'EMA_50' in df_stock.columns:
        fig.add_trace(go.Scatter(x=df_stock.index, y=df_stock['EMA_50'], line=dict(color='#FF6D00', width=1.5), name='EMA 50 (Тренд)'), row=1, col=1)
    if 'EMA_20' in df_stock.columns:
        fig.add_trace(go.Scatter(x=df_stock.index, y=df_stock['EMA_20'], line=dict(color='#2962FF', width=1.5, dash='dot'), name='EMA 20 (Выход)'), row=1, col=1)
    
    anomalies = df_stock[df_stock['Anomaly']]
    fig.add_trace(go.Scatter(x=anomalies.index, y=anomalies['High']*1.02, mode='markers', marker=dict(color='#00E5FF', size=8, symbol='diamond'), name='Всплеск объема'), row=1, col=1)

    colors = ['#ef5350' if c < o else '#26a69a' for o, c in zip(df_stock['Open'], df_stock['Close'])]
    fig.add_trace(go.Bar(x=df_stock.index, y=df_stock['Volume'], marker_color=colors, name='Объем'), row=2, col=1)

    fig.update_layout(height=700, template="plotly_dark", xaxis_rangeslider_visible=False, showlegend=False)
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
    st.plotly_chart(fig, use_container_width=True)

    # 3. БЭКТЕСТ (Открыт по умолчанию для наглядности)
    st.divider()
    st.subheader("🧪 РЕЗУЛЬТАТЫ БЭКТЕСТА (Long & Short + Комиссии)")
    equity, trades = run_advanced_backtest(df_stock, df_idx, capital, risk)
    
    b_col1, b_col2, b_col3, b_col4 = st.columns(4)
    final_profit = equity[-1] - capital
    b_col1.metric("Чистая прибыль", f"{final_profit:,.0f} ₽", f"{(final_profit/capital)*100:.1f}%")
    b_col2.metric("Всего сделок", len(trades))
    
    if len(trades) > 0:
        winrate = (len(trades[trades['PnL'] > 0]) / len(trades)) * 100
        long_trades = len(trades[trades['Тип'] == 'LONG 🟢'])
        short_trades = len(trades[trades['Тип'] == 'SHORT 🔴'])
        b_col3.metric("Винрейт", f"{winrate:.1f}%")
        b_col4.metric("Лонг / Шорт", f"{long_trades} / {short_trades}")
    else:
        b_col3.metric("Винрейт", "0%")
        b_col4.metric("Лонг / Шорт", "
