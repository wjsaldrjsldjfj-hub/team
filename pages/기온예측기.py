import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go


# ---------------------------------------------------------
# 기본 설정
# ---------------------------------------------------------
st.set_page_config(
    page_title="기온 예측기",
    page_icon="🌡️",
    layout="wide",
)

DATA_URL = (
    "https://raw.githubusercontent.com/greatsong/modudata/"
    "bb860932644270ad1199f10d3e7670e30231bce4/data/seoul.csv"
)

BASE_YEAR = 1908
END_YEAR = 2025
MIN_DAYS = 300


# ---------------------------------------------------------
# 데이터 불러오기
# ---------------------------------------------------------
@st.cache_data
def load_data():
    df = pd.read_csv(
        DATA_URL,
        encoding="utf-8-sig",
    )

    # 날짜 변환
    df["날짜"] = pd.to_datetime(df["날짜"], errors="coerce")

    # 평균기온 숫자 변환
    df["평균기온"] = pd.to_numeric(
        df["평균기온"],
        errors="coerce",
    )

    # 날짜 또는 평균기온이 없는 행 제거
    df = df.dropna(subset=["날짜", "평균기온"]).copy()

    # 연도 생성
    df["연도"] = df["날짜"].dt.year

    return df


# ---------------------------------------------------------
# 연도별 평균기온 계산
# ---------------------------------------------------------
@st.cache_data
def make_annual_data(df):
    annual = (
        df.groupby("연도")
        .agg(
            연평균기온=("평균기온", "mean"),
            관측일수=("평균기온", "count"),
        )
        .reset_index()
    )

    # 수업 기준:
    # 1. 2025년 이후 자료 제외
    # 2. 관측일수가 300일 미만인 연도 제외
    annual = annual[
        (annual["연도"] <= END_YEAR)
        & (annual["관측일수"] >= MIN_DAYS)
    ].copy()

    # 회귀 독립변수: 1908년부터 지난 연수
    annual["지난연수"] = annual["연도"] - BASE_YEAR

    return annual.sort_values("연도").reset_index(drop=True)


# ---------------------------------------------------------
# 선형회귀
# ---------------------------------------------------------
def fit_regression(annual):
    x = annual["지난연수"].to_numpy(dtype=float)
    y = annual["연평균기온"].to_numpy(dtype=float)

    # y = slope * x + intercept
    slope, intercept = np.polyfit(x, y, 1)

    # 상관계수
    correlation = np.corrcoef(x, y)[0, 1]

    return slope, intercept, correlation


# ---------------------------------------------------------
# 앱
# ---------------------------------------------------------
st.title("🌡️ 기온 예측기")
st.caption("서울 연평균기온 데이터를 이용한 선형회귀 기반 기온 예측")

with st.spinner("서울 기온 데이터를 불러오는 중..."):
    daily = load_data()
    annual = make_annual_data(daily)

if annual.empty:
    st.error("조건에 맞는 연도별 기온 데이터가 없습니다.")
    st.stop()


# 회귀 계산
slope, intercept, correlation = fit_regression(annual)


# ---------------------------------------------------------
# 회귀선에 사용할 연도 범위
# ---------------------------------------------------------
start_year = int(annual["연도"].min())
last_year = int(annual["연도"].max())
n_years = len(annual)


# ---------------------------------------------------------
# 선택 연도 슬라이더
# ---------------------------------------------------------
selected_year = st.slider(
    "예측할 연도",
    min_value=1900,
    max_value=2100,
    value=2025,
    step=1,
)


# 회귀식의 x는 '1908년부터 지난 연수'
selected_elapsed = selected_year - BASE_YEAR

predicted_temp = (
    slope * selected_elapsed
    + intercept
)


# ---------------------------------------------------------
# 예측 결과
# ---------------------------------------------------------
st.subheader(f"{selected_year}년 예상 평균기온")

st.metric(
    label=f"{selected_year}년 예상 연평균기온",
    value=f"{predicted_temp:.2f} °C",
)


# ---------------------------------------------------------
# 회귀 정보
# ---------------------------------------------------------
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric(
        "회귀에 사용한 연도 수",
        f"{n_years}년",
    )

with col2:
    st.metric(
        "시작 연도",
        f"{start_year}년",
    )

with col3:
    st.metric(
        "끝 연도",
        f"{last_year}년",
    )

with col4:
    st.metric(
        "상관계수",
        f"{correlation:.3f}",
    )


# ---------------------------------------------------------
# 회귀식 표시
# ---------------------------------------------------------
st.info(
    f"회귀식: 연평균기온 = "
    f"{slope:.4f} × (연도 − {BASE_YEAR}) "
    f"+ {intercept:.4f}"
)

st.caption(
    f"회귀선 기울기: {slope:.4f} °C/년 "
    f"(10년당 {slope * 10:.3f} °C)"
)


# ---------------------------------------------------------
# 산점도 + 회귀직선
# ---------------------------------------------------------
x_line = np.linspace(
    min(BASE_YEAR, start_year),
    2100,
    300,
)

y_line = (
    slope * (x_line - BASE_YEAR)
    + intercept
)

fig = go.Figure()

# 실제 연평균기온 산점도
fig.add_trace(
    go.Scatter(
        x=annual["연도"],
        y=annual["연평균기온"],
        mode="markers",
        name="연평균기온",
        marker=dict(
            size=7,
            color="#3498DB",
            opacity=0.75,
        ),
        customdata=annual["관측일수"],
        hovertemplate=(
            "<b>%{x}년</b><br>"
            "연평균기온: %{y:.2f} °C<br>"
            "관측일수: %{customdata}일"
            "<extra></extra>"
        ),
    )
)

# 회귀 직선
fig.add_trace(
    go.Scatter(
        x=x_line,
        y=y_line,
        mode="lines",
        name="선형회귀선",
        line=dict(
            color="#E74C3C",
            width=3,
        ),
        hovertemplate=(
            "연도: %{x:.0f}<br>"
            "회귀 예측: %{y:.2f} °C"
            "<extra></extra>"
        ),
    )
)

# 선택한 연도의 예측값
fig.add_trace(
    go.Scatter(
        x=[selected_year],
        y=[predicted_temp],
        mode="markers",
        name=f"{selected_year}년 예측",
        marker=dict(
            size=15,
            color="#2ECC71",
            line=dict(
                color="white",
                width=2,
            ),
        ),
        hovertemplate=(
            f"<b>{selected_year}년</b><br>"
            "예측 기온: %{y:.2f} °C"
            "<extra></extra>"
        ),
    )
)

fig.update_layout(
    title="서울 연평균기온과 선형회귀선",
    xaxis=dict(
        title="연도",
        tickmode="linear",
        dtick=10,
        showgrid=True,
    ),
    yaxis=dict(
        title="연평균기온 (°C)",
        showgrid=True,
    ),
    hovermode="closest",
    legend=dict(
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="left",
        x=0,
    ),
    height=600,
)

st.plotly_chart(
    fig,
    use_container_width=True,
)


# ---------------------------------------------------------
# 데이터 설명
# ---------------------------------------------------------
with st.expander("📊 분석에 사용된 연도별 데이터 보기"):
    st.dataframe(
        annual[
            ["연도", "연평균기온", "관측일수", "지난연수"]
        ].style.format(
            {
                "연평균기온": "{:.2f}",
                "관측일수": "{:.0f}",
                "지난연수": "{:.0f}",
            }
        ),
        use_container_width=True,
    )

st.caption(
    "※ 2025년까지의 자료만 사용했으며, 관측일수가 300일 미만인 연도는 "
    "회귀 분석에서 제외했습니다."
)
