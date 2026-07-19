from travel_packing.services import WEATHER_CODE_LABELS


def test_hail_weather_code_is_described_as_risk():
    label = WEATHER_CODE_LABELS[96]
    assert "风险" in label
    assert label != "雷暴伴小冰雹"
