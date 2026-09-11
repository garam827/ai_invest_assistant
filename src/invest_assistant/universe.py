"""Shared instrument metadata; no network or storage dependencies."""

UNIVERSE_FILENAME = "_universe.json"

ASSET_CLASS_TICKERS = {
    "SPY": {
        "label": "S&P 500 (미국 대형주)",
        "category": "주식",
        "description": "S&P 500 지수를 추종하는 대표 ETF",
        "news_query": "S&P 500 stock market outlook analysis",
    },
    "QQQ": {
        "label": "나스닥 100 (Nasdaq-100)",
        "category": "주식",
        "description": "나스닥 상장 시가총액 상위 100대 비금융 기업에 투자하는 ETF (기술주 비중 높음)",
        "news_query": "Nasdaq tech stock market outlook analysis",
    },
    "BTC-USD": {
        "label": "비트코인 (Bitcoin)",
        "category": "암호화폐",
        "description": "비트코인 현물 가격(USD 기준)",
        "news_query": "bitcoin price outlook analysis",
    },
    "GLD": {
        "label": "금 (Gold)",
        "category": "귀금속",
        "description": "금 현물 가격을 추종하는 ETF",
        "news_query": "gold price outlook macro drivers analysis",
    },
    "TLT": {
        "label": "미국 장기국채 (20년+)",
        "category": "채권",
        "description": "만기 20년 이상 미국 국채에 투자하는 ETF",
        "news_query": "US long-term treasury bond yields outlook analysis",
    },
    "IEF": {
        "label": "미국 중기국채 (7-10년)",
        "category": "채권",
        "description": "만기 7~10년 미국 국채에 투자하는 ETF",
        "news_query": "US treasury bond yields outlook analysis",
    },
    "DBC": {
        "label": "원자재 종합 (Broad Commodities)",
        "category": "원자재",
        "description": "에너지·금속·농산물 등 원자재 선물에 분산 투자하는 종합 ETF",
        "news_query": "commodities market outlook analysis",
    },
    "USO": {
        "label": "원유 (Crude Oil)",
        "category": "원자재",
        "description": "WTI 원유 선물 가격을 추종하는 ETF",
        "news_query": "crude oil price outlook macro analysis",
    },
    "UNG": {
        "label": "천연가스 (Natural Gas)",
        "category": "원자재",
        "description": "천연가스 선물 가격을 추종하는 ETF",
        "news_query": "natural gas price outlook macro analysis",
    },
    "DBA": {
        "label": "농산물 (Agriculture)",
        "category": "원자재",
        "description": "옥수수·대두·밀·설탕 등 주요 농산물 선물에 분산 투자하는 ETF",
        "news_query": "agricultural commodities market outlook analysis",
    },
    "DBB": {
        "label": "기초금속 (Base Metals)",
        "category": "원자재",
        "description": "구리·알루미늄·아연 선물에 분산 투자하는 ETF (산업 수요 프록시, 경기 선행지표로도 참고됨)",
        "news_query": "base metals copper aluminum zinc price outlook macro analysis",
    },
    "UUP": {
        "label": "미국 달러 인덱스 (US Dollar Index)",
        "category": "통화",
        "description": "주요 6개국 통화 대비 미국 달러 강세를 추종하는 ETF",
        "news_query": "US dollar index DXY outlook macro analysis",
    },
}

MACRO_TICKERS = {
    "^VIX": {"label": "VIX (변동성지수)", "format": "index"},
    "^IRX": {"label": "美 13주 단기 국채금리", "format": "yield_pct"},
    "^TNX": {"label": "美 10년물 국채금리", "format": "yield_pct"},
    "^TYX": {"label": "美 30년 장기 국채금리", "format": "yield_pct"},
}
