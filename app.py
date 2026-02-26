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
                req_columns = ('TRADEDATE', 'OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOLUME')
                
                data = apimoex.get_board_history(session, self.ticker, start=start_date, board='TQBR', columns=req_columns)
                if not data: return None
                
                df = pd.DataFrame(data)
                df.columns = df.columns.str.upper()
                df.rename(columns={'TRADEDATE': 'Date', 'OPEN': 'Open', 'HIGH': 'High', 'LOW': 'Low', 'CLOSE': 'Close', 'VOLUME': 'Volume'}, inplace=True)
                df.dropna(subset=['Open', 'High', 'Low', 'Close'], inplace=True)
                df['Date'] = pd.to_datetime(df['Date'])
                df.set_index('Date', inplace=True)

                if len(df) < 30: return None

                df.ta.ema(length=20, append=True)
                df.ta.ema(length=50, append=True)
                df.ta.ema(length=200, append=True)
                df.ta.rsi(length=14, append=True)
                df.ta.bbands(length=20, std=2, append=True)
                df.ta.atr(length=14, append=True)
                df.ta.macd(fast=12, slow=26, signal=9, append=True)
                df.ta.vwma(length=20, append=True)
                df.fillna(0, inplace=True)
                return df
                
        except Exception:
            return None

    def fetch_imoex(self, days):
        try:
            with requests.Session() as session:
                start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
                data = apimoex.get_board_history(session, 'IMOEX', start=start_date, board='SNDX', columns=('TRADEDATE', 'CLOSE'))
                if not data: return None
                
                df_idx = pd.DataFrame(data)
                df_idx.rename(columns={'TRADEDATE': 'Date', 'CLOSE': 'Close'}, inplace=True)
                df_idx['Date'] = pd.to_datetime(df_idx['Date'])
                df_idx.set_index('Date', inplace=True)
                df_idx.ta.ema(length=50, append=True)
                df_idx.fillna(0, inplace=True)
                return df_idx
        except Exception:
            return None

    def analyze_context(self, data, imoex_data):
        last = data.iloc[-1]
        imoex_last = imoex_data.iloc[-1] if imoex_data is not None and len(imoex_data) > 0 else None
        return self._calculate_signal_for_row(last, imoex_last, data.columns)

    def _calculate_signal_for_row(self, row, imoex_row, columns):
        macd_line = [col for col in columns if col.startswith('MACD_')][0]
        macd_sig = [col for col in columns if col.startswith('MACDs_')][0]
        macd_hist = [col for col in columns if col.startswith('MACDh_')][0]
        vwma_col = [col for col in columns if col.startswith('VWMA')][0]
        vwma = row[vwma_col]
        
        if 'EMA_200' in row and row['EMA_200'] > 0:
            if row['Close'] > row['EMA_50'] and row['EMA_50'] > row['EMA_200']:
                trend, t_score = "СИЛЬНЫЙ РОСТ", 1.0
            elif row['Close'] < row['EMA_50'] and row['EMA_50'] < row['EMA_200']:
                trend, t_score = "СИЛЬНОЕ ПАДЕНИЕ", -1.0
            else:
                trend, t_score = "БОКОВИК", 0
        else:
            if row['Close'] > row['EMA_50']:
                trend, t_score = "ЛОКАЛЬНЫЙ РОСТ", 0.5
            elif row['Close'] < row['EMA_50']:
                trend, t_score = "ЛОКАЛЬНОЕ ПАДЕНИЕ", -0.5
            else:
                trend, t_score = "БОКОВИК", 0

        vwma_status, vwma_score = ("ПОКУПАЮТ", 1.0) if row['Close'] > vwma else ("РАЗДАЮТ", -1.0)
        mom_score = 1.0 if row[macd_line] > row[macd_sig] and row[macd_hist] > 0 else -1.0
        
        rsi = row['RSI_14']
        rsi_score = 0.5 if 40 <= rsi <= 60 else (1.5 if rsi < 35 else -1.5)

        imoex_bullish = None
        imoex_trend = "НЕТ ДАННЫХ"
        if imoex_row is not None:
            if imoex_row['Close'] > imoex_row['EMA_50']:
                imoex_trend = "РАСТЕТ 🟢"
                imoex_bullish = True
            else:
                imoex_trend = "ПАДАЕТ 🔴"
                imoex_bullish = False

        tech_total = (t_score * 0.3) + (mom_score * 0.3) + (vwma_score * 0.3) + (rsi_score * 0.1)
        
        if imoex_bullish is False and tech_total > 0: tech_total -= 0.5
        elif imoex_bullish is True and tech_total < 0: tech_total += 0.5

        return tech_total, trend, row[macd_hist], rsi, vwma_status, imoex_trend, imoex_bullish

    def generate_plan(self, data, signal, capital, risk_pct):
        last_close = data['Close'].iloc[-1]
        atr_col = [col for col in data.columns if col.startswith('ATR')][0]
        atr = data[atr_col].iloc[-1]
        if atr <= 0: atr = last_close * 0.02

        if "BUY" in signal:
            entry = last_close
            sl = entry - (atr * 1.5)
            tp1 = entry + (atr * 2.0)
            tp2 = entry + (atr * 4.0)
        else:
            entry = last_close
            sl = entry + (atr * 1.5)
            tp1 = entry - (atr * 2.0)
            tp2 = entry - (atr * 4.0)

        risk_money = capital * (risk_pct / 100)
        risk_per_share = abs(entry - sl)
        pos_size = int(risk_money / risk_per_share) if risk_per_share > 0 else 0
        rr = abs(tp1 - entry) / risk_per_share if risk_per_share > 0 else 0

        return entry, sl, tp1, tp2, pos_size, rr, risk_money

    # === НОВЫЙ МОДУЛЬ: БЭКТЕСТ ===
    def run_backtest(self, data, imoex_data, initial_capital, risk_pct):
        capital = initial_capital
        equity_curve = []
        trades = []
        
        in_position = False
        trade_type = ""
        entry_price = 0
        sl = 0
        tp = 0
        pos_size = 0
        entry_date = None
        
        atr_col = [col for col in data.columns if col.startswith('ATR')][0]

        # Для ускорения объединим данные IMOEX с основным датафреймом
        if imoex_data is not None:
            merged_data = data.join(imoex_data[['Close', 'EMA_50']], rsuffix='_idx', how='left').ffill()
        else:
            merged_data = data.copy()

        # Пропускаем первые 50 дней, пока индикаторы накапливают историю
        for i in range(50, len(merged_data)):
            row = merged_data.iloc[i]
            date = merged_data.index[i]
            
            # 1. Проверка выхода из текущей сделки
            if in_position:
                exit_price = 0
                reason = ""
                if trade_type == "LONG":
                    if row['Low'] <= sl: exit_price, reason = sl, "Stop Loss"
                    elif row['High'] >= tp: exit_price, reason = tp, "Take Profit"
                elif trade_type == "SHORT":
                    if row['High'] >= sl: exit_price, reason = sl, "Stop Loss"
                    elif row['Low'] <= tp: exit_price, reason = tp, "Take Profit"
                        
                if exit_price != 0:
                    pnl = (exit_price - entry_price) * pos_size if trade_type == "LONG" else (entry_price - exit_price) * pos_size
                    capital += pnl
                    trades.append({
                        'Вход': entry_date.strftime('%Y-%m-%d'), 'Выход': date.strftime('%Y-%m-%d'), 
                        'Тип': trade_type, 'Цена входа': round(entry_price, 2), 
                        'Цена выхода': round(exit_price, 2), 'PnL (₽)': round(pnl, 2), 'Итог': reason
                    })
                    in_position = False

            # 2. Проверка входа в новую сделку
            if not in_position:
                imoex_row = None
                if 'Close_idx' in row:
                    imoex_row = pd.Series({'Close': row['Close_idx'], 'EMA_50': row['EMA_50_idx']})
                
                h_score, _, _, _, _, _, _ = self._calculate_signal_for_row(row, imoex_row, data.columns)
                atr = row[atr_col] if row[atr_col] > 0 else row['Close'] * 0.02

                # Сигналы на вход
                if h_score > 0.2: # BUY
                    in_position = True
                    trade_type = "LONG"
                    entry_price = row['Close']
                    sl, tp = entry_price - (atr * 1.5), entry_price + (atr * 2.0)
                    risk_money = capital * (risk_pct / 100)
                    risk_per_share = abs(entry_price - sl)
                    pos_size = int(risk_money / risk_per_share) if risk_per_share > 0 else 0
                    entry_date = date
                    
                elif h_score < -0.2: # SELL
                    in_position = True
                    trade_type = "SHORT"
                    entry_price = row['Close']
                    sl, tp = entry_price + (atr * 1.5), entry_price - (atr * 2.0)
                    risk_money = capital * (risk_pct / 100)
                    risk_per_share = abs(sl - entry_price)
                    pos_size = int(risk_money / risk_per_share) if risk_per_share > 0 else 0
                    entry_date = date

            equity_curve.append({'Date': date, 'Capital': capital})

        # Принудительно закрываем сделку в конце теста
        if in_position:
            exit_price = merged_data.iloc[-1]['Close']
            pnl = (exit_price - entry_price) * pos_size if trade_type == "LONG" else (entry_price - exit_price) * pos_size
            capital += pnl
            trades.append({
                'Вход': entry_date.strftime('%Y-%m-%d'), 'Выход': merged_data.index[-1].strftime('%Y-%m-%d'), 
                'Тип': trade_type, 'Цена входа': round(entry_price, 2), 
                'Цена выхода': round(exit_price, 2), 'PnL (₽)': round(pnl, 2), 'Итог': "Конец теста"
            })
            equity_curve[-1]['Capital'] = capital
            
        return pd.DataFrame(equity_curve), pd.DataFrame(trades)

# --- ИНТЕРФЕЙС ---
with st.sidebar:
    st.title("⚙️ Настройки")
    ticker_input = st.text_input("Тикер актива", value="SBER")
    
    period_options = {"1 Год": 365, "3 Года": 1095, "5 Лет": 1825}
    selected_period_label = st.selectbox("Исторический период", list(period_options.keys()), index=2)
    days_history = period_options[selected_period_label]
    
    capital = st.number_input("Депозит (₽)", value=100000, step=10000)
    risk_pct = st.slider("Риск (%)", 0.5, 5.0, 1.5)

st.title(f"⚡ QUANTUM ALGO: {ticker_input.upper()}")

engine = QuantEngine(ticker_input)
with st.spinner(f'Анализ рыночной структуры за {selected_period_label} и сканирование Индекса...'):
    data = engine.fetch_data(days=days_history)
    imoex_data = engine.fetch_imoex(days=days_history)

if data is not None:
    bb_upper = [col for col in data.columns if col.startswith('BBU')][0]
    bb_lower = [col for col in data.columns if col.startswith('BBL')][0]
    macd_hist_col = [col for col in data.columns if col.startswith('MACDh_')][0]
    vwma_col = [col for col in data.columns if col.startswith('VWMA')][0]
    atr_col = [col for col in data.columns if col.startswith('ATR')][0]

    last_close = data['Close'].iloc[-1]
    prev_close = data['Close'].iloc[-2]
    pct_change = ((last_close - prev_close) / prev_close) * 100
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Цена (₽)", f"{last_close:.2f}", f"{pct_change:.2f}%")
    col2.metric("След Денег (VWMA)", f"{data[vwma_col].iloc[-1]:.2f}")
    col3.metric("EMA 200 (Глобал)", f"{data['EMA_200'].iloc[-1]:.2f}" if 'EMA_200' in data.columns and data['EMA_200'].iloc[-1] > 0 else "Нет данных")
    col4.metric("Волатильность (ATR)", f"{data[atr_col].iloc[-1]:.2f}")

    # Основной график
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.05, 
                        row_heights=[0.6, 0.2, 0.2], subplot_titles=('Цена, Тренд и Объемы (VWMA)', 'MACD (Импульс)', 'RSI'))

    fig.add_trace(go.Candlestick(x=data.index, open=data['Open'], high=data['High'], low=data['Low'], close=data['Close'], name='Цена'), row=1, col=1)
    fig.add_trace(go.Scatter(x=data.index, y=data[bb_upper], line=dict(color='rgba(255, 255, 255, 0.2)', width=1), name='BB Верх'), row=1, col=1)
    fig.add_trace(go.Scatter(x=data.index, y=data[bb_lower], line=dict(color='rgba(255, 255, 255, 0.2)', width=1), fill='tonexty', fillcolor='rgba(255, 255, 255, 0.05)', name='BB Низ'), row=1, col=1)
    fig.add_trace(go.Scatter(x=data.index, y=data[vwma_col], line=dict(color='#FFEA00', width=2.5, dash='dot'), name='VWMA'), row=1, col=1)
    fig.add_trace(go.Scatter(x=data.index, y=data['EMA_20'], line=dict(color='#2962FF', width=1.5), name='EMA 20'), row=1, col=1)
    fig.add_trace(go.Scatter(x=data.index, y=data['EMA_50'], line=dict(color='#FF6D00', width=1.5), name='EMA 50'), row=1, col=1)

    colors_macd = ['#26A69A' if val >= 0 else '#EF5350' for val in data[macd_hist_col]]
    fig.add_trace(go.Bar(x=data.index, y=data[macd_hist_col], marker_color=colors_macd, name='MACD'), row=2, col=1)
    fig.add_trace(go.Scatter(x=data.index, y=data['RSI_14'], line=dict(color='#E040FB', width=2), name='RSI'), row=3, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="rgba(239, 83, 80, 0.5)", row=3, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="rgba(38, 166, 154, 0.5)", row=3, col=1)

    fig.update_layout(height=800, template="plotly_dark", hovermode="x unified", margin=dict(l=10, r=10, t=40, b=10))
    fig.update_xaxes(rangeslider_visible=False, rangebreaks=[dict(bounds=["sat", "mon"])])
    st.plotly_chart(fig, use_container_width=True)

    tech_score, trend_desc, macd_val, rsi_val, vwma_status, imoex_trend, imoex_bullish = engine.analyze_context(data, imoex_data)
    
    st.markdown("### 🧠 Радар Хедж-Фонда")
    c1, c2, c3, c4 = st.columns(4)
    c1.info(f"**Рынок РФ (IMOEX):**\n{imoex_trend}")
    c2.info(f"**Тренд Акции:**\n{trend_desc}")
    c3.info(f"**Объемы (VWMA):**\n{vwma_status}")
    c4.info(f"**Импульс (MACD):**\n{'Растет 🚀' if macd_val > 0 else 'Падает 📉'}")

    if tech_score > 0.6: final_signal = "STRONG BUY"
    elif tech_score > 0.2: final_signal = "BUY"
    elif tech_score < -0.6: final_signal = "STRONG SELL"
    elif tech_score < -0.2: final_signal = "SELL"
    else: final_signal = "HOLD / НЕ ВХОДИТЬ"

    st.divider()
    st.markdown(f"## 🎯 ТОРГОВЫЙ ПЛАН: <span style='color:{'#26A69A' if 'BUY' in final_signal else '#EF5350' if 'SELL' in final_signal else 'gray'};'>{final_signal}</span>", unsafe_allow_html=True)

    if "HOLD" not in final_signal:
        entry, sl, tp1, tp2, pos_size, rr, risk_m = engine.generate_plan(data, final_signal, capital, risk_pct)
        plan_c1, plan_c2, plan_c3 = st.columns(3)
        plan_c1.success(f"**🟢 TAKE PROFIT:**\n\n🎯 Цель 1: **{tp1:.2f} ₽**\n\n🚀 Цель 2: **{tp2:.2f} ₽**")
        plan_c2.warning(f"**🟡 ВХОД И ОБЪЕМ:**\n\nЦена: **{entry:.2f} ₽**\n\nОбъем: **{pos_size} шт.**")
        plan_c3.error(f"**🔴 СТОП-ЛОСС:**\n\nЦена: **{sl:.2f} ₽**\n\nРиск: **-{risk_m:.0f} ₽**")
    else:
        st.write("На рынке противоречивая ситуация. Лучшая позиция — просто наблюдать.")

    # === ИНТЕРФЕЙС БЭКТЕСТА ===
    st.divider()
    with st.expander("🧪 ЗАПУСТИТЬ БЭКТЕСТ (Симуляция стратегии на истории)", expanded=False):
        st.write(f"Симуляция торговли **{ticker_input}** за выбранный период ({selected_period_label}). Капитал: **{capital} ₽**, Риск на сделку: **{risk_pct}%**.")
        
        with st.spinner("Прогоняем историю..."):
            eq_df, trades_df = engine.run_backtest(data, imoex_data, capital, risk_pct)
        
        if not trades_df.empty:
            final_capital = eq_df['Capital'].iloc[-1]
            total_return = ((final_capital - capital) / capital) * 100
            
            # Статистика
            win_trades = len(trades_df[trades_df['PnL (₽)'] > 0])
            total_trades = len(trades_df)
            win_rate = (win_trades / total_trades) * 100
            
            # Максимальная просадка
            eq_df['Peak'] = eq_df['Capital'].cummax()
            eq_df['Drawdown'] = (eq_df['Capital'] - eq_df['Peak']) / eq_df['Peak'] * 100
            max_dd = eq_df['Drawdown'].min()

            b1, b2, b3, b4 = st.columns(4)
            b1.metric("Итоговый Капитал", f"{final_capital:,.0f} ₽", f"{total_return:.2f}%")
            b2.metric("Винрейт (Успешные сделки)", f"{win_rate:.1f}%")
            b3.metric("Всего сделок", f"{total_trades}")
            b4.metric("Макс. Просадка", f"{max_dd:.2f}%")

            # График Эквити (Кривая капитала)
            fig_eq = go.Figure()
            fig_eq.add_trace(go.Scatter(x=eq_df['Date'], y=eq_df['Capital'], fill='tozeroy', line=dict(color='#00E676', width=2), name='Капитал'))
            fig_eq.update_layout(title="Кривая доходности (Эквити)", template="plotly_dark", height=400, margin=dict(l=10, r=10, t=40, b=10))
            st.plotly_chart(fig_eq, use_container_width=True)

            # Таблица сделок
            st.markdown("### 📋 Журнал сделок")
            st.dataframe(trades_df.style.map(lambda x: 'color: #00E676;' if x > 0 else 'color: #FF1744;' if x < 0 else '', subset=['PnL (₽)']), use_container_width=True)
        else:
            st.warning("За выбранный период стратегия не нашла ни одной точки входа.")
else:
    st.error("Не удалось загрузить данные.")
