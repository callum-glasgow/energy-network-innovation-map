"""Two score-curve elbows within a single, immutable top-50 ranking."""
import math

MAX_RESULTS = 50
MIN_BEND = .08
STAGES = ('first', 'second', 'all')


def curve_elbow(scores):
    """Return the number of results strictly before the first clear elbow.

    Normalize ranks and descending scores to [0, 1]. For a steep decline
    followed by a flatter tail, the elbow is a local maximum of the distance
    below the line joining the endpoints. Ignore bends under 8% of the chart
    height, and never split a tied score group. This is a geometric heuristic,
    not a calibrated relevance threshold or the full Kneedle algorithm.
    """
    if len(scores) < 3 or not all(math.isfinite(s) for s in scores):
        return None
    span = scores[0] - scores[-1]
    if span <= max(1, abs(scores[0]), abs(scores[-1])) * 1e-12:
        return None
    distances = [1 - i / (len(scores) - 1) - (s - scores[-1]) / span
                 for i, s in enumerate(scores)]
    for i in range(1, len(scores) - 1):
        if (distances[i] >= MIN_BEND and distances[i] >= distances[i-1]
                and distances[i] > distances[i+1] + 1e-12):
            # Exclude the elbow point itself, including its tied score group.
            while i > 0 and math.isclose(scores[i-1], scores[i], rel_tol=1e-12, abs_tol=1e-15):
                i -= 1
            return i or None
    return None


def elbow(scores):
    """Search keeps its immutable top-50 boundary; other curves need not share it."""
    return curve_elbow(scores[:MAX_RESULTS])


def result_window(ranked, mode='keyword', stage='first', limit=MAX_RESULTS):
    if stage not in STAGES:
        raise ValueError('Unknown result stage')
    if not 1 <= limit <= MAX_RESULTS:
        raise ValueError('Result limit must be between 1 and 50')
    # Clip BEFORE reading scores: candidates beyond 50 cannot move either elbow.
    ranked = ranked[:MAX_RESULTS]
    total = len(ranked)
    key = {'keyword': 'lexical_score', 'semantic': 'vector_similarity', 'hybrid': 'score'}[mode]
    scores = [float(r.get(key) if r.get(key) is not None else r['score']) for r in ranked]
    first = elbow(scores)
    first_end = first if first is not None else total
    second = elbow(scores[first_end:]) if first is not None else None
    second_end = first_end + second if second is not None else total
    ends = {'first': first_end, 'second': second_end, 'all': total}
    chosen = ranked[:min(limit, ends[stage])]
    pagination = {'first_end': first_end, 'second_end': second_end,
                  'elbows': ([first_end] if first is not None else []) +
                            ([second_end] if second is not None else []),
                  'cap': MAX_RESULTS, 'stage': stage, 'score_source': key,
                  'method': 'normalized-score-curve-distance-v1'}
    if not total:
        reason = 'No matches in the capped ranking.'
    elif stage == 'all':
        reason = f'Showing {len(chosen)} of {total} ranked matches; hard limit 50.'
    elif ends[stage] == total:
        reason = f'No clear {"first" if stage == "first" else "second"} elbow; showing {len(chosen)} of {total} matches, up to 50.'
    else:
        reason = f'Showing {len(chosen)} of {total} matches before the {stage} elbow; hard limit 50.'
    return chosen, reason, pagination
