from decimal import Decimal
from typing import List


def find_subsets(amounts: List[Decimal], target: Decimal, max_size: int) -> List[List[int]]:
    """返回金额之和恰等于 target 的原始下标子集（大小 2..max_size）。"""
    indexed = sorted(enumerate(amounts), key=lambda x: x[1], reverse=True)
    results: List[List[int]] = []

    def dfs(start, path, total):
        if len(path) >= 2 and total == target:
            results.append(list(path))
            return
        if len(path) >= max_size or total >= target:
            return
        for i in range(start, len(indexed)):
            idx, amt = indexed[i]
            if total + amt > target:
                continue
            path.append(idx)
            dfs(i + 1, path, total + amt)
            path.pop()

    dfs(0, [], Decimal("0"))
    return results
