"""국가·장소 로컬 데이터 로더."""

import json
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_COUNTRIES_PATH = _DATA_DIR / "countries.json"
_PLACES_DIR = _DATA_DIR / "places"

MONTH_NAMES = [
    "1월", "2월", "3월", "4월", "5월", "6월",
    "7월", "8월", "9월", "10월", "11월", "12월",
]


def load_countries() -> list[dict]:
    """큐레이션된 국가 메타데이터(예산·안전도·기후·목적 태그)를 불러온다."""
    with open(_COUNTRIES_PATH, encoding="utf-8") as f:
        return json.load(f)


def find_country(slug: str) -> dict | None:
    """slug로 국가 메타데이터 하나를 찾는다. 없으면 None을 돌려준다."""
    for country in load_countries():
        if country["slug"] == slug:
            return country
    return None


def resolve_slug(text: str) -> str | None:
    """국가/도시 이름이나 slug를 받아 실제 등록된 slug로 정규화한다.
    LLM이 score_countries를 거치지 않고 "태국", "방콕", "베트남 다낭"처럼
    자연어로 목적지를 넘겨도 올바른 slug를 찾을 수 있게 한다. 못 찾으면 None.
    """
    text = text.strip()
    countries = load_countries()
    for country in countries:
        if text == country["slug"]:
            return country["slug"]
    for country in countries:
        if country["country"] in text or country["city"] in text:
            return country["slug"]
        if text in country["country"] or text in country["city"]:
            return country["slug"]
    return None


def load_places(slug: str) -> list[dict]:
    """국가 slug에 해당하는 큐레이션된 장소 목록을 불러온다. 데이터가 없으면 빈 리스트."""
    path = _PLACES_DIR / f"{slug}.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def maps_url(place_name: str, city: str) -> str:
    """장소명과 도시명으로 구글맵 검색 링크를 만든다 (API 키 없이도 항상 유효)."""
    from urllib.parse import quote

    query = quote(f"{place_name} {city}")
    return f"https://www.google.com/maps/search/?api=1&query={query}"
