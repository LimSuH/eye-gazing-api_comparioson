"""Common, dependency-free scoring for desktop and browser recordings.

At each 20 Hz evaluation tick we take the latest output only if it is valid and
at most 150 ms old. Missing/stalled streams therefore reduce coverage instead
of looking artificially accurate. Error is NEVER clipped to screen boundaries.
"""

import bisect
import csv
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .protocol import (COLLECT_MS, GRID_MS, MAX_AGE_MS, PROTOCOL_ID, SETTLE_MS,
                       VALIDATION_POINTS)


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def percentile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    i = (len(values) - 1) * fraction
    a, b = math.floor(i), math.ceil(i)
    return values[a] + (values[b] - values[a]) * (i - a)


def mean(values):
    return statistics.fmean(values) if values else None


def score(metadata, rows):
    width, height = metadata["width"], metadata["height"]
    if not (finite_number(width) and finite_number(height) and width > 0 and height > 0):
        raise ValueError("Invalid viewport size")
    targets = metadata.get("validation_points", VALIDATION_POINTS)
    settle = metadata.get("settle_ms", SETTLE_MS)
    collect = metadata.get("collect_ms", COLLECT_MS)
    grid = metadata.get("grid_ms", GRID_MS)
    max_age = metadata.get("max_age_ms", MAX_AGE_MS)
    diagonal = math.hypot(width, height)
    by_target = [[] for _ in targets]
    for row in rows:
        idx = row.get("target_id")
        if isinstance(idx, int) and 0 <= idx < len(targets) and finite_number(row.get("t_ms")):
            by_target[idx].append(row)
    target_stats, all_errors = [], []
    valid_total = ticks_total = emitted = 0
    for idx, target in enumerate(targets):
        events = sorted(by_target[idx], key=lambda r: r["t_ms"])
        times = [r["t_ms"] for r in events]
        gx, gy = target[0] * width, target[1] * height
        errors, xs, ys = [], [], []
        ticks = list(range(settle, settle + collect, grid))
        count_outside = 0
        for tick in ticks:
            pos = bisect.bisect_right(times, tick) - 1
            if pos < 0:
                continue
            row = events[pos]
            x, y = row.get("x"), row.get("y")
            if (row.get("valid") is not True or tick - row["t_ms"] > max_age
                    or not finite_number(x) or not finite_number(y)):
                continue
            errors.append(math.hypot(x - gx, y - gy))
            xs.append(x)
            ys.append(y)
            count_outside += not (0 <= x < width and 0 <= y < height)
        jitter = None
        if xs:
            mx, my = statistics.fmean(xs), statistics.fmean(ys)
            jitter = math.sqrt(statistics.fmean([(x-mx)**2 + (y-my)**2 for x, y in zip(xs, ys)]))
        unique_valid = sum(r.get("valid") is True and finite_number(r.get("x"))
                           and finite_number(r.get("y")) and settle <= r["t_ms"] < settle+collect
                           for r in events)
        emitted += unique_valid
        target_stats.append(dict(target_id=idx, target_x=gx, target_y=gy,
                                 mean_error_px=mean(errors), median_error_px=percentile(errors, .5),
                                 p90_error_px=percentile(errors, .9), jitter_rms_px=jitter,
                                 availability_pct=100*len(errors)/len(ticks),
                                 valid_grid_samples=len(errors), total_grid_samples=len(ticks),
                                 outside_samples=count_outside, valid_outputs=unique_valid))
        all_errors.extend(errors)
        valid_total += len(errors)
        ticks_total += len(ticks)
    # Equal target weighting prevents a tracker doing well at just one target
    # from dominating the overall error through a higher sampling rate there.
    target_means = [x["mean_error_px"] for x in target_stats if x["mean_error_px"] is not None]
    equal_mean = mean(target_means)
    summary = dict(protocol_id=metadata.get("protocol_id", PROTOCOL_ID),
                   backend=metadata["backend"], condition=metadata.get("condition", "baseline"),
                   width=width, height=height, targets_with_data=len(target_means),
                   total_targets=len(targets), mean_error_px=equal_mean,
                   mean_error_diagonal_pct=None if equal_mean is None else 100*equal_mean/diagonal,
                   median_error_px=percentile(all_errors, .5), p90_error_px=percentile(all_errors, .9),
                   availability_pct=100*valid_total/ticks_total,
                   valid_output_hz=emitted/(len(targets)*collect/1000),
                   mean_jitter_rms_px=mean([t["jitter_rms_px"] for t in target_stats
                                           if t["jitter_rms_px"] is not None]),
                   completed=metadata.get("completed", False),
                   warning="Compare error together with availability and missing targets; not a clinical validation.")
    return summary, target_stats


def write_csv(path, rows, fields):
    with Path(path).open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def save_session(root, metadata, rows):
    """Create a unique result directory; never replace an earlier experiment."""
    metadata = dict(metadata)
    metadata.setdefault("created_utc", datetime.now(timezone.utc).isoformat())
    summary, target_stats = score(metadata, rows)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    backend = metadata["backend"]
    if backend not in {"eyetrax", "gazefollower", "eyegestures", "webgazer", "synthetic"}:
        raise ValueError("Unknown backend")
    dest = Path(root) / f"{stamp}_{backend}_{uuid4().hex[:6]}"
    dest.mkdir(parents=True)
    (dest/"summary.json").write_text(json.dumps({"metadata": metadata, "summary": summary},
                                                indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    write_csv(dest/"raw.csv", rows, ["target_id", "t_ms", "x", "y", "valid", "inference_ms", "reason"])
    write_csv(dest/"targets.csv", target_stats, list(target_stats[0]))
    return dest, summary
