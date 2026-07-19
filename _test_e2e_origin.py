"""End-to-end test to verify origin is properly propagated through the graph."""
import os
from dotenv import load_dotenv
from travel_packing.graph import build_graph
from travel_packing.state import initial_state
from langgraph.types import Command

load_dotenv()

print(f"DEEPSEEK_API_KEY set: {bool(os.getenv('DEEPSEEK_API_KEY'))}")
print()

test_cases = [
    "明天从北京去上海，待3天，参加行业展会",  # Near-future date with origin
    "2026年8月20日从北京去上海，待3天，参加行业展会",  # Far-future date (12306 will fail)
    "从北京去上海，待3天",  # No date - should skip train
    "明天去上海，待2天",  # No origin - should skip train
]

graph = build_graph()

for text in test_cases:
    print(f"=== Input: {text} ===")
    state = initial_state(text)
    config = {"configurable": {"thread_id": f"test-{hash(text)}"}}
    result = graph.invoke(state, config=config)

    # Handle weather interrupt
    if result.get("__interrupt__"):
        print("  [Interrupt] Weather required, resuming with mock data...")
        result = graph.invoke(
            Command(resume="25度，多云，降水概率30%"),
            config=config,
        )

    print(f"  origin:       {result.get('origin')}")
    print(f"  destination:  {result.get('destination')}")
    print(f"  start_date:   {result.get('start_date')}")
    print(f"  train_status: {result.get('train_status')}")
    trains = result.get("train_results") or []
    print(f"  train count:  {len(trains)}")
    if trains:
        print(f"  first train:  {trains[0].get('train_number', '')} "
              f"{trains[0].get('from_station', '')} -> {trains[0].get('to_station', '')}")
    print(f"  weather_status: {result.get('weather_status')}")
    print(f"  is_complete:  {result.get('is_complete')}")
    print()
