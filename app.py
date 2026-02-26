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

                # Базовые Индикаторы
                df.ta.ema(length=20, append=True)
                df.ta.ema(length=50, append=True)
                df.ta.ema(length=200, append=True)
                df.ta.rsi(length=14, append=True)
                df.ta.bbands(length=20, std=2, append=True)
                df.ta.atr(length=14, append=True)
                df.ta.macd(fast=12, slow=26, signal=9, append=True)
                
                # Индикатор VWMA 20 (След крупных денег по объему)
                df.ta.vwma(length=20, append=True)
                
                df.fillna(0, inplace=True)
                return df
                
        except Exception:
            return None

    def fetch_imoex(self, days):
        """Скрытый радар (Скачивает Индекс Мосбиржи)"""
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
        """Продвинутая логика хедж-фонда (Мульти-факторная) - Вызов для последнего дня"""
        last = data.iloc[-1]
        imoex_last = imoex_data.iloc[-1] if imoex_data is not None and len(imoex_data) > 0 else None
        return self._calculate_signal_for_row(last, imoex_last, data.columns)

    def _calculate_signal_for_row(self, row, imoex_row, columns):
        """Внутренний метод для расчета сигнала для любой конкретной даты"""
        macd_line = [col for col in columns if col.startswith('MACD_')][0]
        macd_sig = [col for col in columns if col.startswith('MACDs_')][0]
        macd_hist = [col for col in columns if col.startswith('MACDh_')][0]
        
        # Динамический поиск VWMA
        vwma_col = [col for col in columns if col.startswith('VWMA')][0]
        vwma = row[vwma_col]
        
        # 1. Тренд Акции (С защитой от новых акций без истории в 200 дней)
        if 'EMA_200' in row and row['EMA_200'] > 0:
            if row['Close'] > row['EMA_50'] and row['EMA_50'] > row['EMA_200']:
                trend, t_score = "СИЛЬНЫЙ РОСТ 🐂", 1.0
            elif row['Close'] < row['EMA_50'] and row['EMA_50'] < row['EMA_200']:
                trend, t_score = "СИЛЬНОЕ ПАДЕНИЕ 🐻", -1.0
            else:
                trend, t_score = "БОКОВИК / ФЛЭТ ⚖️", 0
        else:
            if row['Close'] > row['EMA_50']:
                trend, t_score = "ЛОКАЛЬНЫЙ РОСТ 🐂", 0.5
            elif row['Close'] < row['EMA_50']:
                trend, t_score = "ЛОКАЛЬНОЕ ПАДЕНИЕ 🐻", -0.5
            else:
                trend, t_score = "БОКОВИК / ФЛЭТ ⚖️", 0

        # 2. VWMA (Что делают крупные фонды?)
        if row['Close'] > vwma:
            vwma_status, vwma_score = "ПОКУПАЮТ 🐋", 1.0
        else:
            vwma_status, vwma_score = "РАЗДАЮТ ТОЛПЕ 🦈", -1.0

        # 3. Моментум (MACD)
        mom_score = 1.0 if row[macd_line] > row[macd_sig] and row[macd_hist] > 0 else -1.0
        
        # 4. Перегретость (RSI)
        rsi = row['RSI_14']
        rsi_score = 0.5 if 40 <= rsi <= 60 else (1.5 if rsi < 35 else -1.5)

        # 5. Глобальный рынок (IMOEX)
        imoex_bullish = None
        imoex_trend = "НЕТ ДАННЫХ"
        if imoex_row is not None:
            if imoex_row['Close'] > imoex_row['EMA_50']:
                imoex_trend = "РАСТЕТ 🟢"
                imoex_bullish = True
            else:
                imoex_trend = "ПАДАЕТ 🔴"
                imoex_bullish = False

        # Формула ИИ-оценки
        tech_total = (t_score * 0.3) + (mom_score * 0.3) + (vwma_score * 0.3) + (rsi_score * 0.1)
        
        # ПЕНАЛЬТИ: Защита от торговли против рынка
        if imoex_bullish is False and tech_total > 0:
            tech_total -= 0.5
        elif imoex_bullish is True and tech_total < 0:
            tech_total += 0.5

        return tech_total, trend, row[macd_hist], rsi, vwma_status, imoex_trend, imoex_bullish

    def generate_plan(self, data, signal, capital, risk_pct):
        last_close = data['Close'].iloc[-1]
        
        # Безопасный поиск колонки ATR
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

# --- ИНТЕРФЕЙС ---
with st.sidebar:
    st.title("⚙️ Настройки")
    ticker_input = st.text_input("Тикер актива", value="SBER")
    
    # Выбор исторического периода
    period_options = {
        "1 Год": 365,
        "3 Года": 1095,
        "5 Лет": 1825
    }
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
    # Динамический поиск нужных колонок
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
    col2.metric("След Денег (VWMA)", f"{data[vwma_col].iloc[-1]:.2f}", help="Средневзвешенная по объему цена")
    col3.metric("EMA 200 (Глобал)", f"{data['EMA_200'].iloc[-1]:.2f}" if 'EMA_200' in data.columns and data['EMA_200'].iloc[-1] > 0 else "Нет данных")
    col4.metric("Волатильность (ATR)", f"{data[atr_col].iloc[-1]:.2f}")

    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.05, 
                        row_heights=[0.6, 0.2, 0.2], subplot_titles=('Цена, Тренд и Объемы (VWMA)', 'MACD (Импульс)', 'RSI'))

    # Отрисовка свечей
    fig.add_trace(go.Candlestick(x=data.index, open=data['Open'], high=data['High'], low=data['Low'], close=data['Close'], name='Цена'), row=1, col=1)
    
    # Отрисовка Полос Боллинджера (полупрозрачный канал)
    fig.add_trace(go.Scatter(x=data.index, y=data[bb_upper], line=dict(color='rgba(255, 255, 255, 0.2)', width=1), name='BB Верх'), row=1, col=1)
    fig.add_trace(go.Scatter(x=data.index, y=data[bb_lower], line=dict(color='rgba(255, 255, 255, 0.2)', width=1), fill='tonexty', fillcolor='rgba(255, 255, 255, 0.05)', name='BB Низ'), row=1, col=1)

    # Выделяем VWMA и EMA
    fig.add_trace(go.Scatter(x=data.index, y=data[vwma_col], line=dict(color='#FFEA00', width=2.5, dash='dot'), name='Крупные деньги (VWMA)'), row=1, col=1)
    fig.add_trace(go.Scatter(x=data.index, y=data['EMA_20'], line=dict(color='#2962FF', width=1.5), name='EMA 20'), row=1, col=1)
    fig.add_trace(go.Scatter(x=data.index, y=data['EMA_50'], line=dict(color='#FF6D00', width=1.5), name='EMA 50'), row=1, col=1)

    # Индикаторы (MACD, RSI)
    colors_macd = ['#26A69A' if val >= 0 else '#EF5350' for val in data[macd_hist_col]]
    fig.add_trace(go.Bar(x=data.index, y=data[macd_hist_col], marker_color=colors_macd, name='MACD'), row=2, col=1)

    fig.add_trace(go.Scatter(x=data.index, y=data['RSI_14'], line=dict(color='#E040FB', width=2), name='RSI'), row=3, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="rgba(239, 83, 80, 0.5)", row=3, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="rgba(38, 166, 154, 0.5)", row=3, col=1)

    # Настройки отображения графика (скрываем выходные дни)
    fig.update_layout(height=800, template="plotly_dark", hovermode="x unified", margin=dict(l=10, r=10, t=40, b=10))
    fig.update_xaxes(
        rangeslider_visible=False,
        rangebreaks=[
            dict(bounds=["sat", "mon"]) # Вырезаем субботу и воскресенье
        ]
    )
    st.plotly_chart(fig, use_container_width=True)

    tech_score, trend_desc, macd_val, rsi_val, vwma_status, imoex_trend, imoex_bullish = engine.analyze_context(data, imoex_data)
    
    st.markdown("### 🧠 Радар Хедж-Фонда (Оценка контекста)")
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

    if imoex_bullish is False and "BUY" in final_signal:
        st.warning("⚠️ ВНИМАНИЕ: Индекс Мосбиржи сейчас падает! Покупать акцию против рынка ОЧЕНЬ ОПАСНО. Рейтинг сигнала понижен.")
    if imoex_bullish is True and "SELL" in final_signal:
        st.warning("⚠️ ВНИМАНИЕ: Весь рынок сейчас растет! Играть на понижение этой акции (Шортить) против рынка ОЧЕНЬ ОПАСНО.")

    st.divider()
    st.markdown(f"## 🎯 ТОРГОВЫЙ ПЛАН: <span style='color:{'#26A69A' if 'BUY' in final_signal else '#EF5350' if 'SELL' in final_signal else 'gray'};'>{final_signal}</span>", unsafe_allow_html=True)

    if "HOLD" not in final_signal:
        entry, sl, tp1, tp2, pos_size, rr, risk_m = engine.generate_plan(data, final_signal, capital, risk_pct)
        plan_c1, plan_c2, plan_c3 = st.columns(3)
        plan_c1.success(f"**🟢 TAKE PROFIT:**\n\n🎯 Цель 1: **{tp1:.2f} ₽**\n\n🚀 Цель 2: **{tp2:.2f} ₽**")
        plan_c2.warning(f"**🟡 ВХОД И ОБЪЕМ:**\n\nЦена: **{entry:.2f} ₽**\n\nОбъем: **{pos_size} шт.**")
        plan_c3.error(f"**🔴 СТОП-ЛОСС:**\n\nЦена: **{sl:.2f} ₽**\n\nРиск: **-{risk_m:.0f} ₽**")
        st.markdown(f"**Соотношение Риск/Прибыль (R/R):** 1 к {rr:.1f}")
    else:
        st.write("На рынке противоречивая ситуация (Например: акция растет, но Индекс падает, или наоборот). Лучшая позиция — просто наблюдать.")

    # --- ИСТОРИЯ СИГНАЛОВ ---
    st.divider()
    st.markdown("### 📜 История Сигналов (Последние 5 дней)")
    
    history_data = []
    
    for i in range(1, 6):
        if len(data) >= i:
            hist_row = data.iloc[-i]
            hist_date = data.index[-i].strftime('%d.%m.%Y')
            
            hist_imoex_row = None
            if imoex_data is not None:
                try:
                    idx_loc = imoex_data.index.get_indexer([data.index[-i]], method='nearest')[0]
                    hist_imoex_row = imoex_data.iloc[idx_loc]
                except Exception:
                    pass

            h_score, h_trend, h_macd, h_rsi, h_vwma, _, _ = engine._calculate_signal_for_row(hist_row, hist_imoex_row, data.columns)
            
            if h_score > 0.6: h_sig = "STRONG BUY 🟢"
            elif h_score > 0.2: h_sig = "BUY ↗️"
            elif h_score < -0.6: h_sig = "STRONG SELL 🔴"
            elif h_score < -0.2: h_sig = "SELL ↘️"
            else: h_sig = "HOLD ⚖️"
            
            history_data.append({
                "Дата": hist_date,
                "Цена Закрытия (₽)": f"{hist_row['Close']:.2f}",
                "Сигнал ИИ": h_sig,
                "Объемы (VWMA)": h_vwma.split()[0], 
                "MACD": "Рост 📈" if h_macd > 0 else "Падение 📉",
                "RSI": f"{h_rsi:.1f}"
            })

    if history_data:
        df_history = pd.DataFrame(history_data)
        st.dataframe(
            df_history, 
            hide_index=True, 
            use_container_width=True,
            column_config={
                "Сигнал ИИ": st.column_config.TextColumn(
                    "Сигнал ИИ",
                    help="Итоговый торговый сигнал на конец дня"
                )
            }
        )
else:
    st.error("Не удалось загрузить данные. Проверьте тикер (например, SBER, LKOH) и подключение к сети.")
