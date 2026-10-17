import html
import os
import re

import pandas as pd

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
import yfinance as yf
from newsapi import NewsApiClient
from textblob import TextBlob

from analytics import add_indicators, analyze, completed_history, demo_history
from product import render_product_page
from journal_view import render_forecast_journal

st.set_page_config(page_title="InfinityTrader · Market research", page_icon="📈", layout="wide")
st.markdown("""
<style>
.block-container {padding-top:4rem; padding-bottom:2rem; max-width:1550px;}
[data-testid="stSidebar"] {border-right:1px solid #213043;}
[data-testid="stMetric"] {background:#101c2c; border:1px solid #26364a; border-radius:12px; padding:18px;}
[data-testid="stMetricLabel"] {color:#a2b2c7; font-size:.8rem;}
[data-testid="stMetricValue"] {font-size:1.85rem; letter-spacing:-.06rem;}
h1 {font-size:2.5rem !important; letter-spacing:-.08rem; padding-bottom:.3rem !important;}
h3 {font-size:1.15rem !important;}
.eyebrow {font-size:.7rem; letter-spacing:.17em; color:#8397b1; font-weight:700;}
.brand {font-size:1.35rem; font-weight:750; letter-spacing:-.04em; margin-bottom:1.5rem;}
.brand span {color:#56e0b4;}
.tag {display:inline-block; padding:.4rem .7rem; border:1px solid #3c4d65;
 border-radius:6px; color:#c4b5fd; font-size:.7rem; letter-spacing:.06em; font-weight:700;}
.signal {font-size:2rem; font-weight:700; color:#56e0b4; margin:.3rem 0;}
.hero {font-size:3.5rem; font-weight:750; letter-spacing:-.12rem; line-height:1.1; margin:1.3rem 0;}
.hero span {color:#56e0b4;}
.muted {color:#91a5bf; font-size:1rem; line-height:1.7;}
.footer {color:#8094ae; font-size:.75rem; padding-top:1.5rem; border-top:1px solid #213043; margin-top:1rem;}
</style>
""", unsafe_allow_html=True)

COMPANIES = {"AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "NVIDIA", "GOOG": "Alphabet",
             "AMZN": "Amazon", "TSLA": "Tesla", "META": "Meta", "SPY": "S&P 500 ETF"}


@st.cache_data(ttl=300, show_spinner=False)
def load_history(symbol, mode):
    if mode == "Demo":
        return demo_history(symbol)
    history = yf.Ticker(symbol).history(period="5y", auto_adjust=True, raise_errors=True, timeout=12)
    if history.empty:
        raise ValueError("No history returned for this symbol.")
    return completed_history(history)


@st.cache_data(ttl=300, show_spinner=False)
def model_result(data):
    return analyze(data)


@st.cache_data(ttl=900, show_spinner=False)
def load_news(symbol, _api_key):
    response = NewsApiClient(api_key=_api_key).get_everything(
        q=symbol, language="en", sort_by="publishedAt", page_size=5)
    articles = [a for a in response.get("articles", []) if a.get("title") and a["title"] != "[Removed]"]
    score = sum(TextBlob(a["title"]).sentiment.polarity for a in articles) / len(articles) if articles else None
    return articles, score


def price_chart(data, style):
    figure = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=.07, row_heights=[.76, .24])
    if style == "Candles":
        figure.add_trace(go.Candlestick(x=data.index, open=data.Open, high=data.High, low=data.Low,
            close=data.Close, increasing_line_color="#56e0b4", decreasing_line_color="#fb7185", name="Price"), row=1, col=1)
    else:
        figure.add_trace(go.Scatter(x=data.index, y=data.Close, name="Close", line=dict(color="#56e0b4", width=2),
            fill="tozeroy", fillcolor="rgba(86,224,180,.05)"), row=1, col=1)
    for key, color, label in [("SMA_20", "#c4b5fd", "20-day average"), ("SMA_50", "#fbbf24", "50-day average")]:
        figure.add_trace(go.Scatter(x=data.index, y=data[key], name=label,
            line=dict(color=color, width=1.5)), row=1, col=1)
    figure.add_trace(go.Bar(x=data.index, y=data.Volume, name="Volume", marker_color="#294659"), row=2, col=1)
    figure.update_layout(height=440, margin=dict(l=0, r=0, t=15, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#a2b2c7"),
        legend=dict(orientation="h", y=1.08, x=0), xaxis_rangeslider_visible=False,
        hovermode="x unified", dragmode="pan")
    figure.update_xaxes(showgrid=False, rangebreaks=[dict(bounds=["sat", "mon"])])
    figure.update_yaxes(gridcolor="#213043", zeroline=False)
    figure.update_yaxes(tickprefix="$", row=1, col=1)
    return figure


st.session_state.setdefault("selected_symbol", "AAPL")
st.session_state.setdefault("selected_mode", "Demo")
st.session_state.setdefault("watchlist", ["AAPL", "MSFT", "NVDA", "SPY"])
st.session_state.setdefault("page", "Research workspace")
with st.sidebar:
    st.markdown('<div class="brand"><span>◈</span> InfinityTrader</div>', unsafe_allow_html=True)
    page = st.radio("Explore", ["Research workspace", "Product & pricing"], key="page", label_visibility="collapsed")
    st.divider()
    if page == "Research workspace":
        with st.form("analysis_controls"):
            entered_symbol = st.text_input("Stock symbol", value=st.session_state.selected_symbol, max_chars=12)
            entered_mode = st.radio("Data source", ["Demo", "Live"],
                index=0 if st.session_state.selected_mode == "Demo" else 1, horizontal=True)
            submitted = st.form_submit_button("Analyze stock →", width="stretch", type="primary")
        if submitted:
            candidate = entered_symbol.strip().upper()
            if re.fullmatch(r"[A-Z^][A-Z0-9.^-]{0,11}", candidate):
                st.session_state.selected_symbol = candidate
                st.session_state.selected_mode = entered_mode
            else:
                st.error("Enter a ticker such as AAPL or BRK-B.")
        st.caption("Apply changes with Analyze stock.")
        st.divider()
        st.caption("WATCHLIST")
        for ticker in st.session_state.watchlist:
            if st.button(f"{ticker}  ·  {COMPANIES.get(ticker, 'Stock')}", width="stretch"):
                st.session_state.selected_symbol = ticker
                st.rerun()
        if st.button("+ Add current stock", width="stretch"):
            if st.session_state.selected_symbol not in st.session_state.watchlist:
                st.session_state.watchlist.append(st.session_state.selected_symbol)
                st.rerun()
        if st.button("Remove current stock", width="stretch"):
            if st.session_state.selected_symbol in st.session_state.watchlist:
                st.session_state.watchlist.remove(st.session_state.selected_symbol)
                st.rerun()
        st.caption("Watchlist is saved for this browser session.")
    st.divider()
    st.markdown("**Research with perspective.**")
    st.caption("Price action, momentum, and model signals in one workspace.")
    st.caption("Created by Shriyan Kandula")

if page == "Product & pricing":
    render_product_page()
    st.stop()

symbol, mode = st.session_state.selected_symbol, st.session_state.selected_mode
title_col, source_col = st.columns([4, 1])
with title_col:
    st.markdown('<div class="eyebrow">YOUR MARKET WORKSPACE</div>', unsafe_allow_html=True)
    st.title(f"{symbol} · {COMPANIES.get(symbol, 'Stock analysis')}")
    st.caption("Price action. Clearer signals. More context.")
with source_col:
    label = "DEMO · SIMULATED" if mode == "Demo" else "YAHOO · DAILY DATA"
    st.markdown(f'<div class="tag">{label}</div>', unsafe_allow_html=True)
    if st.button("↻ Refresh data", width="stretch"):
        load_history.clear()
        model_result.clear()

if mode == "Demo":
    st.info("Demo workspace — prices, indicators, and model results use simulated data. Switch to Live to analyze market history.", icon="ℹ️")
try:
    with st.spinner(f"Analyzing {symbol}…"):
        data = add_indicators(load_history(symbol, mode))
        result = model_result(data)
except Exception:
    st.error(f"Could not analyze {symbol}. The symbol may have too little history, or the data provider may be unavailable.")
    st.caption("Live mode needs Yahoo Finance access. Try another symbol, refresh, or use Demo to explore the dashboard.")
    if st.button("Open demo workspace", type="primary"):
        st.session_state.selected_mode = "Demo"
        st.rerun()
    st.stop()

last = data.iloc[-1]
daily_change = last.Close / data.Close.iloc[-2] - 1
period_change = last.Close / data.Close.iloc[0] - 1
metrics = st.columns(4)
metrics[0].metric("Latest daily close", f"${last.Close:,.2f}", f"{daily_change:+.2%} vs previous session")
metrics[1].metric("History return", f"{period_change:+.2%}", f"{len(data)} sessions", delta_color="off")
metrics[2].metric("Daily volume", f"{last.Volume / 1_000_000:.1f}M", f"{last.Volume_ratio:.2f}× 20-day average", delta_color="off")
metrics[3].metric("RSI · 14 sessions", f"{last.RSI:.1f}",
    "Overbought" if last.RSI > 70 else "Oversold" if last.RSI < 30 else "Middle range", delta_color="off")
st.caption(f"Last data session: {data.index[-1]:%b %d, %Y} · Live prices are split/dividend adjusted. Today's candle is excluded; daily data is not a real-time quote.")
if mode == "Live":
    age = (pd.Timestamp.now(tz="America/New_York").date() - data.index[-1].date()).days
    if age > 7:
        st.warning(f"Price history is {age} calendar days old. Refresh or check the provider before relying on this outlook.")

chart_col, signal_col = st.columns([2.2, 1], gap="large")
with chart_col, st.container(border=True):
    st.subheader("Price & volume")
    range_col, style_col = st.columns([2, 1])
    window = range_col.radio("Chart range", ["1M", "3M", "6M", "1Y"], index=1,
        horizontal=True, label_visibility="collapsed")
    style = style_col.selectbox("Chart style", ["Candles", "Line"], label_visibility="collapsed")
    count = {"1M": 21, "3M": 63, "6M": 126, "1Y": 252}[window]
    st.plotly_chart(price_chart(data.tail(count), style), width="stretch",
        config={"displaylogo": False, "scrollZoom": False})
    st.download_button("↓ Download analysis CSV", data=data.to_csv().encode(),
        file_name=f"{symbol}_{mode.lower()}_analysis.csv", mime="text/csv")
with signal_col, st.container(border=True):
    st.markdown('<div class="eyebrow">NEXT-SESSION OUTLOOK</div>', unsafe_allow_html=True)
    signal = "Bullish lean" if result.upward_score >= .6 else "Bearish lean" if result.upward_score <= .4 else "Mixed signals"
    color = "#56e0b4" if result.upward_score >= .6 else "#fb7185" if result.upward_score <= .4 else "#c4b5fd"
    st.markdown(f'<div class="signal" style="color:{color}">{signal}</div>', unsafe_allow_html=True)
    st.write(f"Upward model score · **{result.upward_score:.0%}**")
    st.progress(result.upward_score)
    st.caption(f"{result.model_name} score for a higher next-session close. Uncalibrated; not a guaranteed probability.")
    st.divider()
    st.metric("Chronological validation accuracy", f"{result.accuracy:.1%}")
    st.caption(f"Compared with a {result.baseline:.1%} majority-class baseline over {result.validation_sessions} later sessions.")
    if result.accuracy <= result.baseline:
        st.caption("The model did not outperform the baseline in this period.")
    with st.expander("How the signal is evaluated"):
        st.write("Three earlier chronological folds select between historical frequency, regularized logistic regression, and random forest using Brier loss. The model family is then fixed. The final 20% are evaluated in three successive blocks, retraining only on known earlier outcomes with one boundary session excluded. The latest forecast is fitted afterward on all known outcomes.")
        st.caption(f"Brier loss: {result.brier:.3f}; historical-frequency baseline: {result.baseline_brier:.3f}. Lower is better; this measures score quality, not trading returns.")
        st.dataframe(result.folds, hide_index=True, width="stretch")
        st.caption(f"Training ends {result.train_end:%b %d, %Y}; validation starts {result.test_start:%b %d, %Y}. Options chains, premiums, and expiry calendars are not analyzed.")

indicator_tab, model_tab, news_tab, journal_tab = st.tabs(["Technical indicators", "Model details", "News & sentiment", "Forecast journal"])
with indicator_tab:
    cols = st.columns(3)
    cols[0].metric("20-day moving average", f"${last.SMA_20:,.2f}", f"Price {last.SMA20_gap:+.1%} vs average", delta_color="off")
    cols[1].metric("50-day moving average", f"${last.SMA_50:,.2f}", f"Price {last.SMA50_gap:+.1%} vs average", delta_color="off")
    cols[2].metric("Average true range · 14", f"${last.ATR:.2f}", f"{last.ATR_pct:.1%} of price", delta_color="off")
    st.caption("RSI measures gains versus losses on a 0–100 scale. ATR includes gaps between sessions. Moving averages describe historical trends.")
with model_tab:
    st.write("**What influences this model**")
    importance = result.importance.head(8).rename(index={"Return": "Daily return", "RSI": "RSI",
        "ATR_pct": "Relative volatility", "SMA20_gap": "20-day trend", "SMA50_gap": "50-day trend", "Volume_ratio": "Relative volume",
        "Return_lag1": "Previous daily return", "Return_lag2": "Return two sessions ago",
        "Momentum5": "5-day momentum", "Momentum20": "20-day momentum",
        "Volatility10": "10-day volatility", "Volatility20": "20-day volatility",
        "RSI_delta5": "5-day RSI change", "MACD_pct": "Relative MACD",
        "Range_pct": "Daily price range", "Close_position": "Close within daily range",
        "Gap_open": "Opening gap", "Body_pct": "Open-to-close return"})
    figure = go.Figure(go.Bar(x=importance.values, y=importance.index, orientation="h", marker_color="#a78bfa"))
    figure.update_layout(height=250, margin=dict(l=0, r=0, t=0, b=0), paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)", font_color="#a2b2c7", yaxis_autorange="reversed", xaxis_tickformat=".0%")
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})
    if result.model_name == "Historical frequency":
        st.caption("Earlier validation favored historical frequency. Its score uses the fraction of rising sessions; individual indicators have no assigned influence.")
    else:
        st.caption("Top eight relative influences: forest importance or absolute standardized logistic coefficients. These describe the model, not causation. Historical evaluation does not establish trading profitability.")
with news_tab:
    api_key = os.environ.get("NEWSAPI_KEY", "")
    if mode == "Demo":
        st.info("Live headlines are available in Live mode. Demo data has no associated news.")
    elif not api_key:
        st.info("Headlines aren't enabled in this workspace yet. Price analysis is still available.")
    elif st.button("Load latest headlines"):
        try:
            articles, sentiment = load_news(symbol, api_key)
            if sentiment is not None:
                st.metric("Headline sentiment", f"{sentiment:+.2f}")
                st.caption("TextBlob polarity from −1 to +1. Sentiment does not change the price model.")
            for article in articles:
                title = html.escape(article["title"])
                url = article.get("url", "")
                if url.startswith("https://"):
                    st.markdown(f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{title}</a>', unsafe_allow_html=True)
                else:
                    st.write(article["title"])
            if not articles:
                st.info("No recent headlines found.")
        except Exception:
            st.warning("News is unavailable. Check your NewsAPI access and try again later.")
with journal_tab:
    render_forecast_journal(symbol, mode, data, result)
st.markdown('<div class="footer">InfinityTrader · Educational market research. Signals are not investment advice. Demo results describe simulated prices.</div>', unsafe_allow_html=True)
