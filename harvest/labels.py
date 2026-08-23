"""Human names for claim types, shared by both viewers.

Lives on its own because viewer.py runs its Streamlit app at import time —
importing it just to borrow a constant would launch a second app and collide on
set_page_config. A plain module keeps the two views from drifting apart.
"""

TYPE_LABELS = {
    "data_semantics": "What the data means",
    "hygiene_rule": "Data hygiene",
    "implicit_constraint": "Unmodelled constraints",
    "objective_tradeoff": "What good looks like",
    "acceptance_heuristic": "How they judge an answer",
    "exception_override": "Manual overrides",
    "vocabulary": "Vocabulary",
}
