"""Small demo runner for the NLP engine."""

from __future__ import annotations

import argparse

from .intent_engine import IntentEngine, load_default_training_examples


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a quick NLP demo")
    parser.add_argument("query", nargs="?", default="Tôi muốn thực đơn 2500 calo để tăng cơ, không có hải sản")
    args = parser.parse_args()

    engine = IntentEngine()
    engine.train(load_default_training_examples())
    result = engine.predict(args.query)

    print(result.to_dict())


if __name__ == "__main__":
    main()
