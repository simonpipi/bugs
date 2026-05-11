#!/usr/bin/env python3
import argparse
import itertools
import json
from pathlib import Path

import cv2

import cnn_captcha


DEFAULT_CACHE = "/tmp/southplus_cnn_candidate_cache.json"
DEFAULT_RULE_DELTAS = "0.20"
BASELINE_PARAMS = (1.0, 0.15, 0.40, 0.0, 0.15, 0.05, 0.08, 0.0, 0.0)


def parse_float_list(value):
    return [float(item) for item in value.split(",") if item.strip()]


def parse_args():
    parser = argparse.ArgumentParser(description="缓存 CNN 候选分类结果并回归扫描候选打分参数。")
    parser.add_argument("--samples-dir", default=str(cnn_captcha.SAMPLES_DIR))
    parser.add_argument("--labels", default=str(cnn_captcha.LABELS_CSV))
    parser.add_argument("--model", default=str(cnn_captcha.MODEL_PATH))
    parser.add_argument("--meta", default=str(cnn_captcha.META_PATH))
    parser.add_argument("--background-weights", default="1.0")
    parser.add_argument("--slot-penalties", default="0.15")
    parser.add_argument("--template-penalties", default="0.40")
    parser.add_argument("--template-local-penalties", default="0.00")
    parser.add_argument("--template-match-bonuses", default="0.15")
    parser.add_argument("--template-mismatch-penalties", default="0.05")
    parser.add_argument("--position-fallback-penalties", default="0.08")
    parser.add_argument("--geometry-weights", default="0.0")
    parser.add_argument("--geometry-score-weights", default="0.0")
    parser.add_argument("--max-per-position", type=int, default=6)
    parser.add_argument("--top", type=int, default=12)
    parser.add_argument("--cache", default=DEFAULT_CACHE, help="候选框 CNN 分类结果缓存 JSON，默认写到 /tmp")
    parser.add_argument("--rebuild-cache", action="store_true", help="忽略已有缓存，重新跑 CNN 并覆盖缓存")
    parser.add_argument("--rule-scan", action="store_true", help="只基于当前错例的前几名候选扫描单条后验调分规则")
    parser.add_argument("--rule-top-k", type=int, default=2, help="生成规则时只查看每个错槽的前 K 个候选")
    parser.add_argument("--rule-deltas", default=DEFAULT_RULE_DELTAS, help="规则调分幅度列表，逗号分隔")
    parser.add_argument("--rule-output", default="", help="可选：把规则扫描明细写入 JSON")
    parser.add_argument("--rule-shape-conditions", action="store_true", help="额外生成 width/height/y 阈值规则，速度较慢")
    parser.add_argument("--rule-check-regressions", action="store_true", help="规则评估时同时扫描基线正确样本，检查回退，速度较慢")
    return parser.parse_args()


def normalize_candidate(candidate):
    normalized = dict(candidate)
    normalized["box"] = tuple(candidate["box"])
    return normalized


def serialize_candidate(candidate):
    serialized = dict(candidate)
    serialized["box"] = list(candidate["box"])
    return serialized


def serialize_case(case):
    cache_items = []
    for box, (digit, digit_prob, background_prob, probabilities) in sorted(case["classification_cache"].items()):
        cache_items.append(
            {
                "box": list(box),
                "digit": digit,
                "digit_prob": digit_prob,
                "background_prob": background_prob,
                "probabilities": probabilities,
            }
        )
    return {
        "file": case["file"],
        "label": case["label"],
        "raw_by_position": [
            [serialize_candidate(candidate) for candidate in candidates]
            for candidates in case["raw_by_position"]
        ],
        "classification_cache": cache_items,
    }


def deserialize_case(case):
    classification_cache = {}
    for item in case["classification_cache"]:
        classification_cache[tuple(item["box"])] = (
            item["digit"],
            float(item["digit_prob"]),
            float(item["background_prob"]),
            [float(value) for value in item["probabilities"]],
        )
    return {
        "file": case["file"],
        "label": case["label"],
        "raw_by_position": [
            [normalize_candidate(candidate) for candidate in candidates]
            for candidates in case["raw_by_position"]
        ],
        "classification_cache": classification_cache,
    }


def load_meta(path):
    meta_path = Path(path).expanduser().resolve()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if cnn_captcha.CHAR_LABELS_CSV.exists():
        rows = None
        if "position_center_ranges" not in meta:
            rows = rows or cnn_captcha.read_csv(cnn_captcha.CHAR_LABELS_CSV)
            meta["position_center_ranges"] = cnn_captcha.compute_position_center_ranges(rows)
        if "slot_scan_templates" not in meta:
            rows = rows or cnn_captcha.read_csv(cnn_captcha.CHAR_LABELS_CSV)
            meta["slot_scan_templates"] = cnn_captcha.compute_slot_scan_templates(rows)
        if "slot_scan_templates_v2" not in meta:
            rows = rows or cnn_captcha.read_csv(cnn_captcha.CHAR_LABELS_CSV)
            meta["slot_scan_templates_v2"] = cnn_captcha.compute_slot_scan_templates_v2(rows)
        if "slot_scan_templates_v3" not in meta:
            rows = rows or cnn_captcha.read_csv(cnn_captcha.CHAR_LABELS_CSV)
            meta["slot_scan_templates_v3"] = cnn_captcha.compute_slot_scan_templates_v3(rows)
        if "slot_scan_templates_v4" not in meta:
            rows = rows or cnn_captcha.read_csv(cnn_captcha.CHAR_LABELS_CSV)
            meta["slot_scan_templates_v4"] = cnn_captcha.compute_slot_scan_templates_v4(rows)
        if "digit_box_stats" not in meta:
            rows = rows or cnn_captcha.read_csv(cnn_captcha.CHAR_LABELS_CSV)
            meta["digit_box_stats"] = cnn_captcha.compute_digit_box_stats(rows)
    return meta


def cache_matches(payload, args):
    expected = {
        "samples_dir": str(Path(args.samples_dir).expanduser().resolve()),
        "labels": str(Path(args.labels).expanduser().resolve()),
        "model": str(Path(args.model).expanduser().resolve()),
        "meta": str(Path(args.meta).expanduser().resolve()),
    }
    return payload.get("inputs") == expected


def read_case_cache(path, args):
    cache_path = Path(path).expanduser()
    if not cache_path.exists() or args.rebuild_cache:
        return None
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    if payload.get("version") != 1 or not cache_matches(payload, args):
        return None
    return [deserialize_case(case) for case in payload["cases"]]


def write_case_cache(path, args, cases):
    cache_path = Path(path).expanduser()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "inputs": {
            "samples_dir": str(Path(args.samples_dir).expanduser().resolve()),
            "labels": str(Path(args.labels).expanduser().resolve()),
            "model": str(Path(args.model).expanduser().resolve()),
            "meta": str(Path(args.meta).expanduser().resolve()),
        },
        "cases": [serialize_case(case) for case in cases],
    }
    cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def build_cases(args):
    samples_dir = Path(args.samples_dir).expanduser().resolve()
    model, meta = cnn_captcha.load_char_cnn(
        model_path=Path(args.model).expanduser().resolve(),
        meta_path=Path(args.meta).expanduser().resolve(),
    )

    cases = []
    for row in cnn_captcha.read_csv(Path(args.labels).expanduser().resolve()):
        label = cnn_captcha.clean_digits(row.get("label")) or cnn_captcha.clean_digits(row.get("error"))
        if len(label) != 4:
            continue
        image = cv2.imread(str(samples_dir / row["file"]))
        if image is None:
            continue

        components = cnn_captcha.component_candidates(image)
        raw_by_position = [
            cnn_captcha.slot_candidates_for_position(components, meta, position, image=image)
            for position in range(4)
        ]
        boxes = [
            tuple(candidate["box"])
            for candidates in raw_by_position
            for candidate in candidates
        ]
        classification_cache = cnn_captcha.classify_crops(model, image, boxes)
        cases.append(
            {
                "file": row["file"],
                "label": label,
                "raw_by_position": raw_by_position,
                "classification_cache": classification_cache,
            }
        )
    return cases


def load_cases(args):
    cases = read_case_cache(args.cache, args)
    if cases is None:
        cases = build_cases(args)
        write_case_cache(args.cache, args, cases)
        print(f"候选缓存: rebuilt {len(cases)} cases -> {Path(args.cache).expanduser().resolve()}")
    else:
        print(f"候选缓存: loaded {len(cases)} cases <- {Path(args.cache).expanduser().resolve()}")
    return cases, load_meta(args.meta)


def set_params(params):
    (
        background_weight,
        slot_penalty,
        template_penalty,
        template_local_penalty,
        template_match_bonus,
        template_mismatch_penalty,
        position_fallback_penalty,
        geometry_weight,
        geometry_score_weight,
    ) = params
    cnn_captcha.BACKGROUND_SCORE_WEIGHT = background_weight
    cnn_captcha.SLOT_SCAN_SOURCE_PENALTY = slot_penalty
    cnn_captcha.TEMPLATE_SCAN_SOURCE_PENALTY = template_penalty
    cnn_captcha.TEMPLATE_LOCAL_SOURCE_PENALTY = template_local_penalty
    cnn_captcha.TEMPLATE_MATCH_BONUS = template_match_bonus
    cnn_captcha.TEMPLATE_MISMATCH_PENALTY = template_mismatch_penalty
    cnn_captcha.POSITION_FALLBACK_SOURCE_PENALTY = position_fallback_penalty
    cnn_captcha.GEOMETRY_DIGIT_WEIGHT = geometry_weight
    cnn_captcha.DIGIT_GEOMETRY_SCORE_WEIGHT = geometry_score_weight


def evaluate(cases, meta, params, max_per_position):
    set_params(params)
    correct = 0
    char_correct = 0
    for case in cases:
        scored_by_position = [
            cnn_captcha.score_slot_candidates(candidates, case["classification_cache"], position, meta)
            for position, candidates in enumerate(case["raw_by_position"])
        ]
        chosen = cnn_captcha.select_best_sequence(scored_by_position, max_per_position=max_per_position)
        prediction = "".join(item["digit"] for item in chosen)
        if prediction == case["label"]:
            correct += 1
        char_correct += sum(left == right for left, right in zip(case["label"], prediction))
    return correct, char_correct


def scored_case(case, meta, params, max_per_position=10):
    set_params(params)
    scored_by_position = [
        cnn_captcha.score_slot_candidates(candidates, case["classification_cache"], position, meta)
        for position, candidates in enumerate(case["raw_by_position"])
    ]
    chosen = cnn_captcha.select_best_sequence(scored_by_position, max_per_position=max_per_position)
    prediction = "".join(item["digit"] for item in chosen)
    return scored_by_position, chosen, prediction


def candidate_signature(candidate):
    x, y, width, height = candidate["box"]
    return {
        "digit": candidate["digit"],
        "source": candidate["source"],
        "position": candidate["position"],
        "width": width,
        "height": height,
        "y": y,
        "digit_prob": candidate["digit_prob"],
        "background_prob": candidate["background_prob"],
    }


def rule_key(rule):
    return json.dumps(rule, sort_keys=True, separators=(",", ":"))


def add_rule(rules, rule):
    rules[rule_key(rule)] = rule


def threshold_floor(value, step):
    return round(int(value / step) * step, 2)


def threshold_ceil(value, step):
    return round((int(value / step) + (0 if value % step == 0 else 1)) * step, 2)


def generate_rules_from_candidate(candidate, action, include_shape=False):
    rules = {}
    sig = candidate_signature(candidate)
    base_fields = [
        {"digit": sig["digit"]},
        {"source": sig["source"]},
        {"position": sig["position"]},
        {"digit": sig["digit"], "source": sig["source"]},
        {"digit": sig["digit"], "position": sig["position"]},
        {"source": sig["source"], "position": sig["position"]},
        {"digit": sig["digit"], "source": sig["source"], "position": sig["position"]},
    ]
    for fields in base_fields:
        add_rule(rules, {"action": action, "when": fields})

    for threshold in {threshold_floor(sig["digit_prob"], 0.05), threshold_floor(sig["digit_prob"], 0.10)}:
        add_rule(rules, {"action": action, "when": {"digit": sig["digit"], "digit_prob_lte": threshold}})
        add_rule(
            rules,
            {
                "action": action,
                "when": {
                    "digit": sig["digit"],
                    "source": sig["source"],
                    "digit_prob_lte": threshold,
                },
            },
        )
    for threshold in {threshold_ceil(sig["background_prob"], 0.05), threshold_ceil(sig["background_prob"], 0.10)}:
        add_rule(rules, {"action": action, "when": {"digit": sig["digit"], "background_prob_gte": threshold}})
        add_rule(
            rules,
            {
                "action": action,
                "when": {
                    "digit": sig["digit"],
                    "source": sig["source"],
                    "background_prob_gte": threshold,
                },
            },
        )
    if include_shape:
        for key, value in [("width", sig["width"]), ("height", sig["height"]), ("y", sig["y"])]:
            add_rule(rules, {"action": action, "when": {"digit": sig["digit"], f"{key}_lte": value}})
            add_rule(rules, {"action": action, "when": {"digit": sig["digit"], f"{key}_gte": value}})
            add_rule(
                rules,
                {
                    "action": action,
                    "when": {
                        "digit": sig["digit"],
                        "source": sig["source"],
                        f"{key}_lte": value,
                    },
                },
            )
            add_rule(
                rules,
                {
                    "action": action,
                    "when": {
                        "digit": sig["digit"],
                        "source": sig["source"],
                        f"{key}_gte": value,
                    },
                },
            )
    return rules.values()


def rule_matches(rule, candidate):
    when = rule["when"]
    x, y, width, height = candidate["box"]
    values = {
        "digit": candidate["digit"],
        "source": candidate["source"],
        "position": candidate["position"],
        "width": width,
        "height": height,
        "y": y,
        "digit_prob": candidate["digit_prob"],
        "background_prob": candidate["background_prob"],
    }
    for key, expected in when.items():
        if key.endswith("_lte"):
            if values[key[:-4]] > expected:
                return False
        elif key.endswith("_gte"):
            if values[key[:-4]] < expected:
                return False
        elif values[key] != expected:
            return False
    return True


def adjusted_candidates(scored_by_position, rule, delta, top_k, search_limit):
    sign = -1 if rule["action"] == "penalty" else 1
    adjusted = []
    for items in scored_by_position:
        position_items = []
        for index, item in enumerate(items[:search_limit]):
            copied = dict(item)
            if index < top_k and rule_matches(rule, copied):
                copied["score"] = copied["score"] + sign * delta
            position_items.append(copied)
        adjusted.append(sorted(position_items, key=lambda item: item["score"], reverse=True))
    return adjusted


def case_rule_matches(case, rule, top_k):
    for items in case["scored_by_position"]:
        if any(rule_matches(rule, item) for item in items[:top_k]):
            return True
    return False


def evaluate_rule(prepared_cases, rule, delta, top_k, search_limit, baseline_correct, baseline_char):
    correct = baseline_correct
    char_correct = baseline_char
    improved = []
    regressed = []
    changed = 0
    for case in prepared_cases:
        if not case_rule_matches(case, rule, top_k):
            continue
        adjusted = adjusted_candidates(case["scored_by_position"], rule, delta, top_k, search_limit)
        chosen = cnn_captcha.select_best_sequence(adjusted, max_per_position=search_limit)
        prediction = "".join(item["digit"] for item in chosen)
        was_ok = case["baseline_prediction"] == case["label"]
        is_ok = prediction == case["label"]
        if is_ok != was_ok:
            correct += 1 if is_ok else -1
        char_correct += (
            sum(left == right for left, right in zip(case["label"], prediction))
            - case["baseline_char_correct"]
        )
        if prediction != case["baseline_prediction"]:
            changed += 1
        if is_ok and not was_ok and len(improved) < 8:
            improved.append(
                {
                    "file": case["file"],
                    "label": case["label"],
                    "from": case["baseline_prediction"],
                    "to": prediction,
                }
            )
        elif was_ok and not is_ok and len(regressed) < 8:
            regressed.append(
                {
                    "file": case["file"],
                    "label": case["label"],
                    "from": case["baseline_prediction"],
                    "to": prediction,
                }
            )
    return {
        "correct": correct,
        "char_correct": char_correct,
        "changed": changed,
        "improved_examples": improved,
        "regressed_examples": regressed,
    }


def prepare_rule_cases(cases, meta, params, max_per_position):
    prepared = []
    for case in cases:
        scored_by_position, chosen, prediction = scored_case(case, meta, params, max_per_position=max_per_position)
        prepared.append(
            {
                "file": case["file"],
                "label": case["label"],
                "baseline_prediction": prediction,
                "baseline_char_correct": sum(left == right for left, right in zip(case["label"], prediction)),
                "scored_by_position": scored_by_position,
                "chosen": chosen,
            }
        )
    return prepared


def collect_candidate_rules(prepared_cases, top_k, include_shape=False):
    rules = {}
    for case in prepared_cases:
        if case["baseline_prediction"] == case["label"]:
            continue
        for position, expected_digit in enumerate(case["label"]):
            chosen_digit = case["chosen"][position]["digit"] if position < len(case["chosen"]) else ""
            if chosen_digit == expected_digit:
                continue
            add_many = list(generate_rules_from_candidate(case["chosen"][position], "penalty", include_shape=include_shape))
            for candidate in case["scored_by_position"][position][:top_k]:
                if candidate["digit"] == expected_digit:
                    add_many.extend(generate_rules_from_candidate(candidate, "bonus", include_shape=include_shape))
            for rule in add_many:
                rules[rule_key(rule)] = rule
    return list(rules.values())


def format_rule(rule, delta):
    direction = "-" if rule["action"] == "penalty" else "+"
    conditions = []
    for key, value in rule["when"].items():
        if key.endswith("_lte"):
            conditions.append(f"{key[:-4]}<={value}")
        elif key.endswith("_gte"):
            conditions.append(f"{key[:-4]}>={value}")
        else:
            conditions.append(f"{key}={value}")
    return f"{direction}{delta:.2f} when " + ",".join(conditions)


def run_rule_scan(cases, meta, args):
    prepared_cases = prepare_rule_cases(cases, meta, BASELINE_PARAMS, args.max_per_position)
    total = len(prepared_cases)
    baseline_correct = sum(1 for case in prepared_cases if case["baseline_prediction"] == case["label"])
    baseline_char = sum(
        sum(left == right for left, right in zip(case["label"], case["baseline_prediction"]))
        for case in prepared_cases
    )
    rules = collect_candidate_rules(prepared_cases, args.rule_top_k, include_shape=args.rule_shape_conditions)
    deltas = parse_float_list(args.rule_deltas)
    evaluation_cases = (
        prepared_cases
        if args.rule_check_regressions
        else [case for case in prepared_cases if case["baseline_prediction"] != case["label"]]
    )

    results = []
    for rule in rules:
        for delta in deltas:
            metrics = evaluate_rule(
                evaluation_cases,
                rule,
                delta,
                args.rule_top_k,
                args.max_per_position,
                baseline_correct,
                baseline_char,
            )
            gain = metrics["correct"] - baseline_correct
            char_gain = metrics["char_correct"] - baseline_char
            improved = len(metrics["improved_examples"])
            regressed = len(metrics["regressed_examples"])
            if gain > 0 or improved or regressed:
                results.append(
                    {
                        "gain": gain,
                        "char_gain": char_gain,
                        "improved": improved,
                        "regressed": regressed,
                        "delta": delta,
                        "rule": rule,
                        **metrics,
                    }
                )

    results.sort(
        key=lambda item: (
            item["gain"],
            item["char_gain"],
            item["improved"] - item["regressed"],
            -item["changed"],
        ),
        reverse=True,
    )

    print(
        f"baseline sequence={baseline_correct}/{total}={baseline_correct / total:.2%} "
        f"character={baseline_char}/{total * 4}={baseline_char / (total * 4):.2%}"
    )
    scope = "all" if args.rule_check_regressions else "baseline_mismatches"
    print(f"rules={len(rules)} deltas={len(deltas)} top_k={args.rule_top_k} scope={scope}")
    for item in results[: args.top]:
        print(
            f"gain={item['gain']:+d} char={item['char_gain']:+d} changed={item['changed']} "
            f"sequence={item['correct']}/{total}={item['correct'] / total:.2%} "
            f"{format_rule(item['rule'], item['delta'])}"
        )
        if item["improved_examples"]:
            print(f"  improved: {item['improved_examples'][:3]}")
        if item["regressed_examples"]:
            print(f"  regressed: {item['regressed_examples'][:3]}")

    if args.rule_output:
        output_path = Path(args.rule_output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"规则明细: {output_path}")


def main():
    args = parse_args()
    cases, meta = load_cases(args)
    if args.rule_scan:
        run_rule_scan(cases, meta, args)
        return 0

    grids = [
        parse_float_list(args.background_weights),
        parse_float_list(args.slot_penalties),
        parse_float_list(args.template_penalties),
        parse_float_list(args.template_local_penalties),
        parse_float_list(args.template_match_bonuses),
        parse_float_list(args.template_mismatch_penalties),
        parse_float_list(args.position_fallback_penalties),
        parse_float_list(args.geometry_weights),
        parse_float_list(args.geometry_score_weights),
    ]

    total = len(cases)
    results = []
    for params in itertools.product(*grids):
        correct, char_correct = evaluate(cases, meta, params, max_per_position=args.max_per_position)
        results.append((correct, char_correct, params))

    results.sort(reverse=True, key=lambda item: (item[0], item[1]))
    field_names = [
        "background",
        "slot",
        "template",
        "template_local",
        "template_match",
        "template_mismatch",
        "position_fallback",
        "geometry",
        "geometry_score",
    ]
    for correct, char_correct, params in results[: args.top]:
        values = " ".join(f"{name}={value:.2f}" for name, value in zip(field_names, params))
        print(
            f"sequence={correct}/{total}={correct / total:.2%} "
            f"character={char_correct}/{total * 4}={char_correct / (total * 4):.2%} "
            f"{values}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
