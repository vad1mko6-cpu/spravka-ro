#!/usr/bin/env python3
"""
Сборка справочника из трёх страниц форума, сохранённых вручную.

Положи в одну папку:
  Кодекс_об_административных...html   (КоАП)
  Постановление_правительства...html  (ПДД)
  Уголовный_кодекс...html             (УК РО)

Запуск:
  python build.py <папка> [--out uk_spravochnik.html]

Что делает:
  1. Разбирает три файла и строит полные листы ПДД, КоАП, УКРО.
  2. Строит таблицы «Основные нарушения» по статьям из файлов.
  3. Применяет overrides.json (ручные правки: состав строк, формулировки,
     суммы, которые нельзя взять из источника).
  4. Пишет отчёт: что изменилось и что не удалось найти.

Нужно: pip install beautifulsoup4
"""
import argparse, datetime, html, json, re
from pathlib import Path
from bs4 import BeautifulSoup

HERE = Path(__file__).parent
AMT = re.compile(r'(?:от\s+)?\d[\d\.\s]*\d?(?:\s*(?:до|-|–|—)\s*\d[\d\.\s]*\d?)?\s*(?:рублей|₽|руб\.?)')
PEN = re.compile(r'влеч|влек|наказыва|наказан', re.I)
SPLIT = re.compile(r'[,\s]*[—–-]\s*(наказыва\w*\b.*)$', re.S)
TAGS = re.compile(r'\[[^\]]*\]\s*')

# ---------- чтение ----------
def read_lines(path):
    soup = BeautifulSoup(path.read_text(encoding='utf-8', errors='ignore'), 'html.parser')
    for t in soup(['script', 'style', 'noscript']):
        t.decompose()
    body = soup.find(class_='message-body') or soup.find('article') or soup.body or soup
    lines = [l.strip() for l in body.get_text('\n', strip=True).split('\n')]
    return [l for l in lines if l and l != '\u200b']

def parse(lines):
    arts, order, cur, chap = {}, [], None, ''
    for l in lines:
        if re.match(r'^(Глава|РАЗДЕЛ)\s', l):
            chap = l; continue
        m = re.match(r'^Статья (\d+(?:\.\d+)*)\.?\s*(.*)', l)
        if m:
            cur = m.group(1)
            if cur not in arts:
                arts[cur] = {'title': m.group(2), 'body': [], 'chap': chap}; order.append(cur)
            continue
        if cur and not re.fullmatch(r'\d+\.?', l):
            arts[cur]['body'].append(l)
    return arts, order

def key(n): return [int(x) for x in n.split('.')]

# ---------- суммы и параметры ----------
def money(x):
    return re.sub(r'(\d)\.(\d{3})', r'\1 \2', x).replace('рублей', 'руб.').replace('рубля', 'руб.').replace('рубль', 'руб.')

def koap_parts(body):
    parts, cond = [], []
    for l in body:
        if len(l) < 3: continue
        if re.search(r'\bвлеч(?:ет|ёт)\b|\bвлекут\b', l):
            f = re.search(r'штраф\w* (?:в размере |в\s+двукратном размере )?(.*?рубл\w*)', l)
            fine = money(f.group(1)) if f else ''
            a = re.search(r'арест\w* на срок (.*?(?:суток|сут\.?))', l)
            arr = money(a.group(1)) if a else ''
            lish = 'лишение прав' if re.search(r'лишени\w* права', l) else ''
            pred = 'предупреждение' if re.search(r'предупрежден', l) else ''
            extra = ', '.join(x for x in [pred if not fine else ('или ' + pred if pred else ''), lish] if x)
            parts.append({'cond': ' '.join(cond).strip(' -—'), 'fine': fine, 'arrest': arr, 'extra': extra})
            cond = []
        else:
            cond.append(l)
    return parts

SHEET_KOAP_PEN = re.compile(r'\bвлеч(?:ет|ёт)\b|\bвлекут\b', re.I)  # только строки «влечет/влекут ...»

def koap_pairs_chain(body, title):
    prs, cond = [], []
    for l in body:
        if len(l) < 3: continue
        if SHEET_KOAP_PEN.search(l):
            prs.append((' '.join(cond).strip(' -—') or title, l)); cond = []
        else:
            cond.append(l)
    return prs

def uk_parts(body):
    out = []
    for l in body:
        if not re.search(r'наказыв', l): continue
        st = len(re.search(r'★+', l).group(0)) if '★' in l else 0
        sr = re.search(r'лишени\w* свободы на срок (\d+) месяц', l)
        fi = re.search(r'штрафом в размере (.*?рубл\w*)', l)
        out.append({'stars': '★' * st or '—', 'srok': f'{sr.group(1)} мес' if sr else '—',
                    'fine': money(fi.group(1)) if fi else '—'})
    return out

def uk_inline_pairs(body):
    prs = []
    for l in body:
        if not re.search(r'наказыв', l, re.I): continue  # только «наказывается/наказываются»
        x = TAGS.sub('', l); x = re.sub(r'^\d+\.\s*', '', x).strip()
        m = SPLIT.search(x)
        prs.append((x[:m.start()].strip(' ,—–-'), m.group(1)) if m else ('', x))
    return prs

# ---------- HTML-блоки ----------
def fmt(t): return AMT.sub(lambda m: f'<b class="sum">{m.group(0)}</b>', html.escape(t))

def pair(c, x):
    cc = f'<div class="cond">{html.escape(c)}</div>' if c else ''
    return f'<div class="pair">{cc}<div class="pen">{fmt(x)}</div></div>'

NONE = '<span class="none">Наказания нет</span>'

def text_html(title, body):
    t = f'<div class="atitle">{html.escape(title)}</div>' if title else ''
    return t + '<div class="ftxt">' + '<br>'.join(html.escape(l) for l in body if not re.fullmatch(r'\d+\.?', l)) + '</div>'

def sheet_row(num, title, body, pen):
    return f'<tr class="row"><td class="a">Ст. {html.escape(num)}</td><td>{text_html(title, body)}</td><td>{pen or NONE}</td></tr>'

def table(head, rows):
    th = ''.join(f'<th>{html.escape(h)}</th>' for h in head)
    body = ''.join('<tr>' + ''.join(f'<td>{html.escape(str(c))}</td>' for c in r) + '</tr>' for r in rows)
    return f'<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>'

# ---------- сборка данных ----------
def norm(name):
    """Имя файла без регистра, пробелов, подчёркиваний и знаков: 'Уголовный_кодекс _ Россия' -> 'уголовный кодекс россия'."""
    n = re.sub(r'\.html?$', '', name, flags=re.I)
    n = re.sub(r'[_\s]+', ' ', n).strip().lower()
    return n

def build_sources(folder):
    files = sorted(p for p in folder.glob('*.htm*') if p.is_file())
    def find(prefix):
        for p in files:
            if norm(p.name).startswith(prefix):
                return p
        return None
    koap_f = find('кодекс об административных')
    pdd_f = find('постановление правительства') or find('пдд')
    uk_f = find('уголовный кодекс')
    missing = [n for n, f in [('КоАП', koap_f), ('ПДД', pdd_f), ('УК', uk_f)] if f is None]
    if missing:
        names = '\n   '.join(p.name for p in files) or '(в папке нет html-файлов)'
        raise SystemExit(f'Не найдены файлы: {", ".join(missing)}.\nВ папке {folder} найдено:\n   {names}\n'
                         'Проверь, что в папке лежат страницы КоАП, ПДД и УК, сохранённые с форума.')
    return (parse(read_lines(koap_f)), parse(read_lines(pdd_f)), parse(read_lines(uk_f)))

def source_tables(koap, pdd, uk):
    """Полные листы и строки «Основные нарушения», все из источников."""
    kp, kpo = koap
    pd, pdo = pdd
    uk_a, uko = uk
    mapping = json.loads((HERE / 'mapping.json').read_text(encoding='utf-8'))

    sheet_koap = []
    for n in kpo:
        prs = koap_pairs_chain(kp[n]['body'], kp[n]['title'])
        pen = ''.join(pair(c, x) for c, x in prs)
        sheet_koap.append(sheet_row(n, kp[n]['title'], kp[n]['body'], pen))

    sheet_uk = []
    for n in uko:
        prs = uk_inline_pairs(uk_a[n]['body'])
        pen = ''.join(pair(c, x) for c, x in prs)
        if float(n) >= 0:
            sheet_uk.append(sheet_row(n, uk_a[n]['title'], uk_a[n]['body'], pen))

    link = {}
    for c in mapping['chapters']:
        for it in c['items']:
            link.setdefault(it['pdd'].split(' ')[0], []).extend(it['koap'])
    sheet_pdd, last = [], None
    for n in pdo:
        blocks = ''
        for kn in dict.fromkeys(link.get(n, [])):
            if kn in kp:
                blocks += (f'<div class="blk"><div class="bh">Ст. {kn} КоАП: {html.escape(kp[kn]["title"][:110])}</div>'
                           + ''.join(pair(c, x) for c, x in koap_pairs_chain(kp[kn]['body'], kp[kn]['title']))
                           + '</div>')
        sheet_pdd.append(sheet_row(n, '', pd[n]['body'], blocks))

    # строки «Основные нарушения» из источника: ключ = метка части
    src = {'pdd': {}, 'kr': {}, 'uk': {}}
    for n in kpo:
        if key('1.2') <= key(n) <= key('4.8'): continue
        parts = koap_parts(kp[n]['body'])
        for i, p in enumerate(parts, 1):
            lab = n if len(parts) == 1 else f'{n} ч.{i}'
            cells = [kp[n]['title'], p['fine'] or '—', p['arrest'] or '—', p['extra'] or '—']
            src['pdd' if n.split('.')[0] == '8' else 'kr'][lab] = cells
    for n in uko:
        if float(n) < 50: continue
        parts = uk_parts(uk_a[n]['body'])
        for i, p in enumerate(parts, 1):
            lab = n if len(parts) == 1 else f'{n} ч.{i}'
            src['uk'][lab] = [uk_a[n]['title'], p['stars'], p['srok'], p['fine']]
    return {'sheet_koap': sheet_koap, 'sheet_uk': sheet_uk, 'sheet_pdd': sheet_pdd}, src

COLS = {'pdd': ['desc', 'fine', 'arrest', 'extra'],
        'kr':  ['desc', 'fine', 'arrest', 'extra'],
        'uk':  ['desc', 'stars', 'srok', 'fine']}

def apply_overrides(src, ov):
    """ov[t] = список строк: {"label", "src"?, поля из COLS[t] только если поле изменено вручную}.
    Поля, которых нет в overrides, берутся из источника по метке src (или label).
    Строки без источника (объединённые, например «8.2 ч.1-3») требуют все поля в overrides."""
    rows, warn = {}, []
    for t in ['pdd', 'kr', 'uk']:
        cols = COLS[t]
        out = []
        for o in ov.get(t, []):
            ref = o.get('src') or o['label']
            base = src[t].get(ref)
            if base is None:
                base = [o.get(c, '—') for c in cols]
                if any(c not in o for c in cols):
                    warn.append(f'[{t}] «{o["label"]}»: нет в источнике и не заданы все поля')
            else:
                if o.get('src') is None and ref not in src[t]:
                    warn.append(f'[{t}] «{o["label"]}»: метка не найдена в источнике')
            cells = [o.get(c, base[i]) for i, c in enumerate(cols)]
            out.append([o['label']] + cells)
        rows[t] = out
    return rows, warn

def html_block(rows_head, rows):
    return table(rows_head, rows)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('folder', type=Path)
    ap.add_argument('--out', type=Path, default=Path('uk_spravochnik.html'))
    a = ap.parse_args()

    koap, pdd, uk = build_sources(a.folder)
    sheets, src = source_tables(koap, pdd, uk)
    ov = json.loads((HERE / 'overrides.json').read_text(encoding='utf-8'))
    vrows, warn = apply_overrides(src, ov)

    tpl = (HERE / 'template.html').read_text(encoding='utf-8')
    thead = '<thead><tr><th>Статья</th><th>Суть нормы / нарушения</th><th>Наказание</th></tr></thead>'
    page = (tpl.replace('{{PDD_ROWS}}', ''.join(sheets['sheet_pdd']))
               .replace('{{KOAP_ROWS}}', ''.join(sheets['sheet_koap']))
               .replace('{{UK_ROWS}}', ''.join(sheets['sheet_uk']))
               .replace('{{V_PDD}}', table(['Статья', 'Название', 'Штраф (граждане)', 'Арест', 'Прочее'], vrows['pdd']))
               .replace('{{V_KR}}', table(['Статья', 'Название', 'Штраф (граждане)', 'Арест', 'Прочее'], vrows['kr']))
               .replace('{{V_UK}}', table(['Статья', 'Название', 'Звёзды', 'Срок', 'Штраф'], vrows['uk']))
               .replace('{{THEAD}}', thead)
               .replace('{{DATE}}', datetime.date.today().isoformat()))
    a.out.write_text(page, encoding='utf-8')

    # отчёт и снимок для сравнения с прошлой сборкой
    names = {'pdd': 'КоАП-ПДД', 'kr': 'КоАП-кромеПДД', 'uk': 'УК'}
    snap_p = a.out.with_suffix('.snapshot.json')
    snap = {t: {r[0]: r[1:] for r in vrows[t]} for t in vrows}
    if snap_p.exists():
        prev = json.loads(snap_p.read_text(encoding='utf-8'))
        for t in ['pdd', 'kr', 'uk']:
            old, cur = prev.get(t, {}), snap[t]
            add = [k for k in cur if k not in old]
            rem = [k for k in old if k not in cur]
            chg = [k for k in cur if k in old and cur[k] != old[k]]
            print(f'{names[t]}: добавлено {len(add)}, удалено {len(rem)}, изменено {len(chg)}')
            for k in add: print(f'   + {k}: {" | ".join(map(str, cur[k]))}')
            for k in rem: print(f'   - {k}')
            for k in chg: print(f'   ~ {k}: было {" | ".join(map(str, old[k]))} → стало {" | ".join(map(str, cur[k]))}')
        old_s, cur_s = prev.get('sheet_counts', {}), {k: len(v) for k, v in sheets.items()}
        if old_s != cur_s: print('Листы (количество строк):', old_s, '→', cur_s)
    else:
        print('Первая сборка: отчёта об изменениях нет.')
    snap['sheet_counts'] = {k: len(v) for k, v in sheets.items()}
    snap_p.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding='utf-8')
    for w in warn:
        print('ВНИМАНИЕ:', w)
    print('Готово:', a.out, '| листы:', snap['sheet_counts'])

if __name__ == '__main__':
    main()
