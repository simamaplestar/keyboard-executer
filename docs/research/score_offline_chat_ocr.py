"""Summarize timings; score fixed chat rows only after annotation review."""
from html import escape
import json
from pathlib import Path
import re
import unicodedata

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / 'packaging/build/diagnostics/offline-ocr'

SCORE_FIELDS = ('edit_errors', 'labelled_characters', 'cer', 'exact_rows',
                'correct_routes', 'false_incoming', 'checks')


def annotation_status(labels):
    labelled = [entry for entry in labels.values() if entry['labels']]
    if not labelled:
        return 'unannotated'
    # Missing status must not silently enable scoring of historical labels.
    if any(entry.get('annotation_status') != 'reviewed' for entry in labelled):
        return 'pending_review'
    return 'reviewed'


def write_tiny_results(report, labels):
    """Present saved OCR rows without treating disputed annotations as truth."""
    title = 'PP-OCRv6 tiny + ONNX Runtime 辨識結果'
    method = ('2026-10-02 本機離線測試，Intel Core i9-13900KF，CPU 2 threads。'
              '每張圖先執行一次，再量測三次取中位數；不含 AI 回覆。')
    status = annotation_status(labels)
    review = ('標註待重新人工核對' if status == 'pending_review' else
              '標註已人工核對' if status == 'reviewed' else '尚無人工標註')
    note = ('先前人工標註經使用者指出有誤，相關錯漏、CER 與準確度排名已撤回。'
            f'{review}（annotation_status: {status}）。'
            '以下直接呈現原始 JSON 已保存的聊天列合併結果，不判定文字對錯，也不代表 100% 準確。')
    names = {'full': '完整聊天框', 'map_and_outgoing': '地圖聊天與送出密語',
             'short_whisper': '短密語', 'incoming': '收到的密語',
             'long_outgoing': '長句送出密語'}
    text = [title, method, note]
    html = ['<!doctype html><html lang="zh-Hant"><meta charset="utf-8">',
            f'<title>{escape(title)}</title>',
            '<style>body{font-family:system-ui,"Microsoft JhengHei",sans-serif;'
            'max-width:1180px;margin:30px auto;padding:0 20px;background:#f5f6f8;color:#18202c}'
            'article{background:white;border:1px solid #dce1e8;border-radius:10px;padding:20px;margin:24px 0}'
            'img{max-width:100%;height:auto;border:1px solid #ccc}'
            'pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#101820;color:#edf3fc;'
            'padding:16px;border-radius:6px;line-height:1.7}.note{color:#48556c;line-height:1.7}</style>',
            f'<h1>{escape(title)}</h1><p>{escape(method)}</p><p class="note">{escape(note)}</p>',
            '<p><a href="v6-tiny-ort.json">完整原始 JSON（含每個 OCR 框、confidence）</a></p>']
    for image in report['images']:
        name = names.get(image['name'], image['name'])
        filename = labels[image['name']]['filename']
        raw = '\n'.join(row['raw'] for row in image['parsed'])
        seconds = f"{image['median_seconds']:.3f}"
        text.extend(['', f'{name} ({filename}): {seconds} 秒', raw])
        html.append(f'<article><h2>{escape(name)} <small>{seconds} 秒</small></h2>'
                    f'<p><a href="images/{escape(filename)}">開啟原圖</a></p>'
                    f'<img src="images/{escape(filename)}" alt="{escape(name)}原圖">'
                    f'<h3>依畫面列合併的辨識文字</h3><pre>{escape(raw)}</pre></article>')
    html.append('</html>')
    (WORK/'v6-tiny-results.txt').write_text('\n'.join(text) + '\n', encoding='utf-8')
    (WORK/'v6-tiny-results.html').write_text('\n'.join(html) + '\n', encoding='utf-8')


def normalized(text):
    text = ''.join(unicodedata.normalize('NFKC', text).split())
    return re.sub(r'\[CH[.-](\d+)\]', r'[CH-\1]', text, flags=re.IGNORECASE)


def distance(a, b):
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(current[-1]+1, previous[j]+1, previous[j-1]+(x != y)))
        previous = current
    return previous[-1]


def summarize():
    labels = {x['name']: x for x in json.loads((WORK/'inputs.json').read_text(encoding='utf-8'))}
    status = annotation_status(labels)
    candidates = []
    for name in ('paddle', 'v5-mobile-ort', 'v5-mobile-ov', 'v5-server-ort',
                 'v6-tiny-ort', 'v6-small-ort', 'v6-small-ov'):
        path = WORK / f'{name}.json'
        if not path.exists():
            continue
        report = json.loads(path.read_text(encoding='utf-8'))
        if len(report['images']) != len(labels):
            continue
        summary = {'candidate': name,
                   'timings': {x['name']: x['median_seconds'] for x in report['images']},
                   'max_warm_seconds': {x['name']: x['max_seconds'] for x in report['images']},
                   'load_seconds': report['load_seconds'],
                   'max_rss_mb': max(x['rss_mb'] for x in report['images']),
                   'stable_results': all(x['stable_results'] for x in report['images']),
                   'annotation_status': status,
                   'accuracy_status': 'available' if status == 'reviewed' else 'unavailable',
                   **dict.fromkeys(SCORE_FIELDS)}
        if name == 'v6-tiny-ort':
            write_tiny_results(report, labels)
        if status != 'reviewed':
            candidates.append(summary)
            continue
        checks, false_positives = [], []
        for image in report['images']:
            expected = labels[image['name']]['labels']
            parsed = image['parsed']
            for label in expected:
                left, right = label['band']
                rows = [row for row in parsed if left <= (row['top']+row['bottom'])/2 < right]
                actual = ''.join(row['raw'] for row in rows)
                a, b = normalized(label['raw']), normalized(actual)
                matching = [row for row in rows if row['channel'] == label['channel']
                            and row['incoming'] == label['incoming']
                            and ((row['sender'] == label['sender'] and row['eligible'])
                                 if label['incoming'] else row['recipient'] == label['sender'])]
                checks.append({'image': image['name'], 'expected': label['raw'], 'actual': actual,
                               'edit_errors': distance(a, b), 'characters': len(a),
                               'exact_row': a == b, 'correct_identity_and_direction': bool(matching)})
            for row in parsed:
                if row['eligible'] and not any(
                    label['incoming'] and label['sender'] == row['sender']
                    and label['channel'] == row['channel']
                    and label['band'][0] <= (row['top']+row['bottom'])/2 < label['band'][1]
                    for label in expected
                ):
                    false_positives.append({'image': image['name'], 'sender': row['sender']})
        errors = sum(x['edit_errors'] for x in checks)
        characters = sum(x['characters'] for x in checks)
        summary.update({'edit_errors': errors, 'labelled_characters': characters,
                        'cer': errors/characters if characters else None,
                        'exact_rows': sum(x['exact_row'] for x in checks),
                        'correct_routes': sum(x['correct_identity_and_direction'] for x in checks),
                        'false_incoming': false_positives, 'checks': checks})
        candidates.append(summary)
    (WORK/'summary.json').write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding='utf-8')
    for c in candidates:
        print(json.dumps({k:v for k,v in c.items() if k not in ('checks','max_warm_seconds')},ensure_ascii=False))


if __name__ == '__main__':
    summarize()
