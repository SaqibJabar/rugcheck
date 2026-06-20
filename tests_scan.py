import requests
import time

API = "http://127.0.0.1:8000/api/analyze"

# Test set: contract, chain, expected label (SCAM or SAFE)
tests = [
    ("0x8076c74c5e3f5852037f31ff0093eeb8c8add8d3", "56", "SCAM"),  # SafeMoon (BSC)
    ("0xdAC17F958D2ee523a2206206994597C13D831ec7", "1", "SAFE"),  # USDT ETH
    ("0x55d398326f99059f775485246999027b3197955", "56", "SAFE"), # USDT BSC
    ("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174", "137", "SAFE"), # USDC Polygon
    ("0x95aD61b0a150d79219dCF64E1E6Cc01f0B64C4cE", "1", "SAFE"), # SHIB
    ("0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984", "1", "SAFE"), # UNI
]

results = []
for addr, chain, expected in tests:
    payload = {"contract_address": addr, "chain_id": chain}
    try:
        r = requests.post(API, json=payload, timeout=20)
        data = r.json()
        raw = data.get('raw_data', {})
        ai = data.get('ai_report', {})
        score = ai.get('risk_score', raw.get('risk_score'))
        level = ai.get('risk_level', raw.get('risk_level'))
        results.append((addr, chain, expected, int(score), level, raw.get('data_issues'), raw.get('large_transfer_detected')))
    except Exception as e:
        results.append((addr, chain, expected, None, None, str(e), None))
    time.sleep(0.6)

# Print detailed results
print("Detailed results:")
for r in results:
    print(r)

# Evaluate detection at thresholds
print("\nSummary:")
for thresh in (60, 35):
    tp = fp = tn = fn = 0
    for _, _, expected, score, _, _, _ in results:
        if score is None:
            continue
        detected = score >= thresh
        is_scam = expected == 'SCAM'
        if is_scam and detected:
            tp += 1
        elif is_scam and not detected:
            fn += 1
        elif not is_scam and detected:
            fp += 1
        else:
            tn += 1
    total = tp + fn
    recall = tp / total if total else None
    precision = tp / (tp + fp) if (tp + fp) else None
    print(f"Threshold >={thresh}: TP={tp}, FN={fn}, FP={fp}, TN={tn}, Recall={recall}, Precision={precision}")

# Simple rating
# Use threshold 60 for strong detection
strong_tp = sum(1 for r in results if r[2]=='SCAM' and r[3] and r[3] >= 60)
strong_total = sum(1 for r in results if r[2]=='SCAM')
print('\nStrong detection rate (>=60):', f"{strong_tp}/{strong_total}")

# Print note
print('\nNote: This is a small sample; expand test vectors for robust metrics.')
