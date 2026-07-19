from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from travel_packing.graph import build_graph
from travel_packing.render import render_markdown
from travel_packing.state import initial_state


graph = build_graph()
config = {"configurable": {"thread_id": "packing-demo"}}

graph.invoke(
    initial_state("这周五去上海，待3天，主要参加行业展会，晚上可能有同行聚餐。"),
    config=config,
)
updated = graph.invoke(
    {
        "raw_input": "展会第二天我要做演讲，所以需要正装和笔记本电脑。",
        "is_update": True,
    },
    config=config,
)

print(render_markdown(updated))
