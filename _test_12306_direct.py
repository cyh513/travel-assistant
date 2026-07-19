"""Test 12306 train query directly with a near-future date."""
from datetime import date, timedelta
from travel_packing.services import query_12306_trains

tomorrow = (date.today() + timedelta(days=1)).isoformat()
print(f"Today: {date.today().isoformat()}")
print(f"Testing 12306 query for: 北京 -> 上海, {tomorrow}")
print()

result = query_12306_trains("北京", "上海", tomorrow)
if result is None:
    print("Query returned None (failed)")
else:
    trains = result.get("results", [])
    print(f"Query succeeded! Found {len(trains)} trains")
    print(f"From: {result.get('from_station')} ({result.get('from_code')})")
    print(f"To:   {result.get('to_station')} ({result.get('to_code')})")
    print()
    if trains:
        print("First 3 trains:")
        for t in trains[:3]:
            print(f"  {t.get('train_number', '')}: "
                  f"{t.get('from_station', '')} {t.get('departure_time', '')} -> "
                  f"{t.get('to_station', '')} {t.get('arrival_time', '')} "
                  f"({t.get('duration', '')})")
