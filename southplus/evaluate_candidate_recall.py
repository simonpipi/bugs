#!/usr/bin/env python3
import argparse
from collections import Counter
from pathlib import Path

import cv2

from cnn_captcha import (
    CHAR_LABELS_CSV,
    META_PATH,
    MODEL_PATH,
    SAMPLES_DIR,
    box_iou,
    box_tuple,
    classify_crops,
    component_candidates,
    load_char_cnn,
    read_csv,
    score_slot_candidates,
    slot_candidates_for_position,
)


def parse_args():
    parser = argparse.ArgumentParser(description="诊断 CNN 槽位候选框召回和打分排名。")
    parser.add_argument("--samples-dir", default=str(SAMPLES_DIR))
    parser.add_argument("--char-labels", default=str(CHAR_LABELS_CSV))
    parser.add_argument("--model", default=str(MODEL_PATH))
    parser.add_argument("--meta", default=str(META_PATH))
    parser.add_argument("--iou", type=float, default=0.45)
    return parser.parse_args()


def main():
    args = parse_args()
    samples_dir = Path(args.samples_dir).expanduser().resolve()
    model, meta = load_char_cnn(
        model_path=Path(args.model).expanduser().resolve(),
        meta_path=Path(args.meta).expanduser().resolve(),
    )

    total = 0
    raw_recall = 0
    ranked_recall = Counter()
    best_source = Counter()
    chosen_source = Counter()
    miss_examples = []
    rank_examples = []

    for row in read_csv(Path(args.char_labels).expanduser().resolve()):
        file_name = row["file"]
        position = int(row["pos"])
        expected_box = box_tuple(row)
        image = cv2.imread(str(samples_dir / file_name))
        if image is None:
            continue

        components = component_candidates(image)
        raw_candidates = slot_candidates_for_position(components, meta, position)
        boxes = [tuple(candidate["box"]) for candidate in raw_candidates]
        cache = classify_crops(model, image, boxes)
        scored = score_slot_candidates(raw_candidates, cache, position, meta)
        total += 1

        raw_hits = [
            candidate
            for candidate in raw_candidates
            if box_iou(candidate["box"], expected_box) >= args.iou
        ]
        if raw_hits:
            raw_recall += 1
            best = max(raw_hits, key=lambda candidate: box_iou(candidate["box"], expected_box))
            best_source[best["source"]] += 1
        elif len(miss_examples) < 12:
            nearest = max(raw_candidates, key=lambda candidate: box_iou(candidate["box"], expected_box))
            miss_examples.append(
                {
                    "file": file_name,
                    "pos": position,
                    "digit": row["digit"],
                    "expected": expected_box,
                    "nearest_iou": round(box_iou(nearest["box"], expected_box), 2),
                    "nearest_source": nearest["source"],
                    "nearest_box": nearest["box"],
                }
            )

        hit_rank = None
        for index, candidate in enumerate(scored, 1):
            if box_iou(candidate["box"], expected_box) >= args.iou:
                hit_rank = index
                chosen_source[candidate["source"]] += 1
                break
        if hit_rank is not None:
            for limit in [1, 3, 5, 10]:
                if hit_rank <= limit:
                    ranked_recall[limit] += 1
            if hit_rank > 3 and len(rank_examples) < 12:
                rank_examples.append(
                    {
                        "file": file_name,
                        "pos": position,
                        "digit": row["digit"],
                        "rank": hit_rank,
                        "top": {
                            "digit": scored[0]["digit"],
                            "source": scored[0]["source"],
                            "score": round(scored[0]["score"], 3),
                            "box": scored[0]["box"],
                            "iou": round(box_iou(scored[0]["box"], expected_box), 2),
                        },
                    }
                )

    print(f"slots: {total}")
    print(f"raw_candidate_recall@{args.iou}: {raw_recall}/{total} = {raw_recall / total:.2%}")
    for limit in [1, 3, 5, 10]:
        print(f"ranked_recall@{limit}: {ranked_recall[limit]}/{total} = {ranked_recall[limit] / total:.2%}")
    print("best_raw_hit_sources:")
    for source, count in best_source.most_common():
        print(f"  {source}: {count}")
    print("first_ranked_hit_sources:")
    for source, count in chosen_source.most_common():
        print(f"  {source}: {count}")
    print("raw_miss_examples:")
    for item in miss_examples:
        print(f"  {item}")
    print("late_rank_examples:")
    for item in rank_examples:
        print(f"  {item}")


if __name__ == "__main__":
    raise SystemExit(main())
