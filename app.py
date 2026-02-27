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

# --- СТИЛИЗАЦИЯ ИНТЕРФЕЙСА ---
st.markdown("""
    <style>
    .stApp { background-color: #0E1117; color: #FAFAFA; }
    .stMetric { background-color: #1E1E1E; padding: 15px; border-radius: 8px; border: 1px solid #333; }
    </style>
    """, unsafe_allow_html=True)

# --- КЭШИРОВАНИЕ ДАННЫХ (УСКОРЯЕТ РАБОТУ В 10 РАЗ) ---
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_moex_data(ticker, days, board='TQBR'):
    """Универсальная функция скачивания данных с защитой от ошибок API"""
    try:
        with requests.Session() as session:
            start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            data = apimoex.get_board_history(session, ticker, start=start_date, board=board)
            
            if not data: return None
            
            df = pd.DataFrame(data)
            # Принудительно переводим все колонки в верхний регистр (защита от смены регистра на стороне MOEX)
            df.columns = [c.upper() for c in df.columns]
            
            rename_map = {'TRADEDATE': 'Date', 'OPEN': 'Open', 'HIGH': 'High', 'LOW': 'Low', 'CLOSE': 'Close', 'VOLUME': 'Volume'}
            df.rename(columns=rename_map, inplace=True)
            
            if 'Date' in df.columns:
                df['Date'] = pd.to_datetime(df['Date'])
                df.set_index('Date', inplace=True)
                df.sort_index(inplace=True)
            return df
    except Exception:
        return None

class QuantEngine:
    def __init__(self, ticker):
        self.ticker = ticker.upper().strip()

    def get_prepared_data(self, days):
        df = fetch_moex_data(self.ticker, days, 'TQBR')
        if df is None or df.empty: return None
        
        # Защита: проверяем наличие нужных колонок
        req_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
        if not all(c in df.columns for c in req_cols): return None
        
        # Расчет индикаторов
        df.ta.ema(length=20, append=True)
        df.ta.ema(length=50, append=True)
        df.ta.ema(length=200, append=True)
        df.ta.rsi(length=14, append=True)
        df.ta.macd(append=True)
        df.ta.atr(length=14, append=True)
        df.ta.vwma(length=20, append=True)
        df.ta.bbands(length=20, std=2, append=True)

        # Детекция аномальных объемов (Круглые числа: > 2.5 от среднего)
        df['Vol_Avg'] = df['Volume'].rolling(window=20).mean()
        df['Anomaly'] = df['Volume'] > (df['Vol_Avg'] * 2.5)

        # Безопасное заполнение пустот (pandas 2.0+ совместимость)
        df = df.ffill().fillna(0)
        return df

    def get_context(self, days):
        df_idx = fetch_moex_data('IMOEX', days, 'SNDX')
        df_usd = fetch_moex_data('USD000UTSTOM', days, 'CETS')
        return df_idx, df_usd

    def get_signal_params(self, columns):
        """Безопасный поиск динамических названий индикаторов"""
        macd_h = [c for c in columns if c.startswith('MACDh')]
        vwma = [c for c in columns if c.startswith('VWMA')]
        atr = [c for c in columns if c.startswith('ATR')]
        
        return (macd_h[0] if macd_h else None, 
                vwma[0] if vwma else None, 
                atr[0] if atr else None)

    def run_backtest(self, data, initial_cap, risk_pct):
        """Прогон стратегии на исторических данных"""
        cap = initial_cap
        trades = []
        equity = [initial_cap] * 50 # Заглушка для первых 50 дней (пока копятся индикаторы)
        in_pos = False
        
        macd_h_col, vwma_col, atr_col = self.get_signal_params(data.columns)
        
        # Если индикаторы не рассчитались, возвращаем пустой результат
        if not all([macd_h_col, vwma_col, atr_col]):
            return equity, pd.DataFrame(columns=['Дата', 'PnL', 'Итог'])

        for i in range(50, len(data)):
            row = data.iloc[i]
            
            # ЛОГИКА ВХОДА: Тренд + Импульс + Подтверждение объемом
            if not in_pos and row['Close'] > row['EMA_50'] and row[macd_h_col] > 0 and row['Close'] > row[vwma_col]:
                in_pos = True
                entry_p = row['Close']
                sl = entry_p - (row[atr_col] * 2) # Стоп за 2 ATR
                tp = entry_p + (row[atr_col] * 4) # Тейк за 4 ATR
                
                risk_rub = cap * (risk_pct / 100)
                pos_size = int(risk_rub / abs(entry_p - sl)) if abs(entry_p - sl) > 0 else 0
                entry_date = data.index[i]

            # ЛОГИКА ВЫХОДА
            elif in_pos:
                if row['Low'] <= sl or row['High'] >= tp or i == len(data)-1:
                    exit_p = sl if row['Low'] <= sl else (tp if row['High'] >= tp else row['Close'])
                    pnl = (exit_p - entry_p) * pos_size
                    cap += pnl
                    trades.append({'Дата': entry_date.strftime('%Y-%m-%d'), 'PnL': pnl, 'Итог': 'TP 🟢' if exit_p >= tp else 'SL 🔴'})
                    in_pos = False
            
            equity.append(cap)
            
        # Защита от KeyError при пустом списке сделок
        df_trades = pd.DataFrame(trades, columns=['Дата', 'PnL', 'Итог'])
        return equity, df_trades

# --- ИНТЕРФЕЙС SIDEBAR ---
with st.sidebar:
    st.title("⚙️ Настройки")
    ticker = st.text_input("Тикер (MOEX)", value="SBER")
    period = st.selectbox("История", ["1 Год", "3 Года", "5 Лет"], index=0)
    days_map = {"1 Год": 365, "3 Года": 1095, "5 Лет": 1825}
    
    st.divider()
    capital = st.number_input("Начальный депозит (₽)", value=100000, step=10000)
    risk = st.slider("Риск на сделку (%)", 0.5, 5.0, 1.5)

# --- ОСНОВНОЙ РАБОЧИЙ ПРОЦЕСС ---
engine = QuantEngine(ticker)

with st.spinner('Синхронизация с серверами MOEX...'):
    df_stock = engine.get_prepared_data(days_map[period])
    df_idx, df_usd = engine.get_context(days_map[period])

if df_stock is not None:
    last = df_stock.iloc[-1]
    mh, vw, atr_col = engine.get_signal_params(df_stock.columns)
    
    # Расчет текущего сигнала
    score = sum([
        1 if last['Close'] > last['EMA_50'] else 0,
        1 if mh and last[mh] > 0 else 0,
        1 if vw and last['Close'] > last[vw] else 0
    ])
    
    # 1. МЕТРИКИ ВЕРХНЕЙ ПАНЕЛИ
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Цена Акции", f"{last['Close']:.2f} ₽")
    if df_usd is not None and not df_usd.empty: 
        m2.metric("USD/RUB", f"{df_usd.iloc[-1]['Close']:.2f} ₽")
    else:
        m2.metric("USD/RUB", "Нет данных")
        
    m3.metric("Активность Крупного капитала", "АНОМАЛИЯ 🐳" if last['Anomaly'] else "Норма")
    m4.metric("Торговый Сигнал", "STRONG BUY 🚀" if score == 3 else "HOLD ⚖️" if score > 1 else "SELL 🐻")

    # 2. ИНТЕРАКТИВНЫЙ ГРАФИК
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
    
    # Свечи + Скользящие
    fig.add_trace(go.Candlestick(x=df_stock.index, open=df_stock['Open'], high=df_stock['High'], low=df_stock['Low'], close=df_stock['Close'], name='Цена'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_stock.index, y=df_stock['EMA_50'], line=dict(color='#FF6D00', width=1.5), name='EMA 50'), row=1, col=1)
    
    # Визуализация "Китов" (синие алмазы)
    anomalies = df_stock[df_stock['Anomaly']]
    fig.add_trace(go.Scatter(x=anomalies.index, y=anomalies['High']*1.02, mode='markers', marker=dict(color='#00E5FF', size=8, symbol='diamond'), name='Всплеск объема'), row=1, col=1)

    # Гистограмма объемов
    colors = ['#ef5350' if c < o else '#26a69a' for o, c in zip(df_stock['Open'], df_stock['Close'])]
    fig.add_trace(go.Bar(x=df_stock.index, y=df_stock['Volume'], marker_color=colors, name='Объем'), row=2, col=1)

    fig.update_layout(height=700, template="plotly_dark", xaxis_rangeslider_visible=False, showlegend=False)
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])]) # Скрываем выходные дни
    st.plotly_chart(fig, use_container_width=True)

    # 3. ТОРГОВЫЙ ПЛАН
    st.subheader("🎯 Актуальный план:")
    if score == 3 and atr_col:
        st.success(f"**🟢 ВХОД:** {last['Close']:.2f} ₽ &nbsp;|&nbsp; **🔴 СТОП-ЛОСС:** {last['Close'] - last[atr_col]*2:.2f} ₽ &nbsp;|&nbsp; **🚀 ТЕЙК-ПРОФИТ:** {last['Close'] + last[atr_col]*4:.2f} ₽")
    else:
        st.info("💡 Условия для идеального входа сейчас не выполнены. Алгоритм ждет подтверждения тренда и объемов.")

    # 4. РЕЗУЛЬТАТЫ БЭКТЕСТА (Скрыты под спойлер, чтобы не загромождать экран)
    st.divider()
    with st.expander("🧪 РЕЗУЛЬТАТЫ БЭКТЕСТА (Симуляция стратегии на истории)", expanded=False):
        equity, trades = engine.run_backtest(df_stock, capital, risk)
        
        b_col1, b_col2, b_col3 = st.columns(3)
        final_profit = equity[-1] - capital
        b_col1.metric("Чистая прибыль", f"{final_profit:,.0f} ₽", f"{(final_profit/capital)*100:.1f}%")
        b_col2.metric("Всего сделок", len(trades))
        
        if len(trades) > 0:
            winrate = (len(trades[trades['PnL'] > 0]) / len(trades)) * 100
            b_col3.metric("Успешных сделок (Винрейт)", f"{winrate:.1f}%")
        else:
            b_col3.metric("Успешных сделок (Винрейт)", "0%")
        
        st.line_chart(equity)
        
        if not trades.empty:
            # Красивая раскраска таблицы сделок
            st.dataframe(trades.style.map(lambda x: 'color: #00E676;' if x > 0 else 'color: #FF1744;' if x < 0 else '', subset=['PnL']), use_container_width=True)

else:
    st.error("❌ Ошибка: Не удалось загрузить данные. Проверьте правильность тикера (например: SBER, GAZP) или доступность серверов Мосбиржи.")
