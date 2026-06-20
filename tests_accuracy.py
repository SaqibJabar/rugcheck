import os
import analyzer

os.remove(".cache.json") if os.path.exists(".cache.json") else None

cases = [
    ("0x8076c74c5e3f5852037f31ff0093eeb8c8add8d3", "56", "SCAM"),
    ("0xdAC17F958D2ee523a2206206994597C13D831ec7", "1", "SAFE"),
    ("0x55d398326f99059f775485246999027b3197955", "56", "SAFE"),
    ("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174", "137", "SAFE"),
    ("0x95aD61b0a150d79219dCF64E1E6Cc01f0B64C4cE", "1", "SAFE"),
    ("0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984", "1", "SAFE"),
    ("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", "1", "SAFE"),
    ("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", "1", "SAFE"),
]

print("Running benchmark...")
results = []
for addr, chain, expected in cases:
    raw = analyzer.analyze_token(addr, chain)
    score = int(raw.get("risk_score", 0))
    level = raw.get("risk_level", analyzer.classify_risk(score))
    results.append((addr, chain, expected, score, level, raw.get("data_completeness"), raw.get("confidence"), raw.get("data_issues")))

print(results)
for threshold in (60, 45, 35):
    tp = fp = tn = fn = 0
    for _, _, expected, score, _, _, _, _ in results:
        detected = score >= threshold
        is_scam = expected == "SCAM"
        if is_scam and detected:
            tp += 1
        elif is_scam and not detected:
            fn += 1
        elif not is_scam and detected:
            fp += 1
        else:
            tn += 1
    recall = tp / (tp + fn) if (tp + fn) else 0
    precision = tp / (tp + fp) if (tp + fp) else 0
    print(f"threshold={threshold} tp={tp} fp={fp} fn={fn} tn={tn} recall={recall:.3f} precision={precision:.3f}")
