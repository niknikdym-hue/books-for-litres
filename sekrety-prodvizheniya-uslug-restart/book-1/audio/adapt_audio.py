"""Build a traceable audio text from the verified print edition 1.1.

Editorial prose lives in editorial_edits.py. Mechanical operations only remove
visual markup, move citations into a source ledger, and verbalize clock times.
The printed master is never changed by this command.
"""
from pathlib import Path
import re, json, hashlib, sys
from editorial_edits import EDITS, PHRASES

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / 'manuscript'
SOURCE_COMMIT = 'e94c055514acc7f2643265c03494cd5677e056d6'

NOM = 'ноль один два три четыре пять шесть семь восемь девять десять одиннадцать двенадцать тринадцать четырнадцать пятнадцать шестнадцать семнадцать восемнадцать девятнадцать'.split()
GEN = 'нуля одного двух трёх четырёх пяти шести семи восьми девяти десяти одиннадцати двенадцати тринадцати четырнадцати пятнадцати шестнадцати семнадцати восемнадцати девятнадцати'.split()
DAT = 'нулю одному двум трём четырём пяти шести семи восьми девяти десяти одиннадцати двенадцати тринадцати четырнадцати пятнадцати шестнадцати семнадцати восемнадцати девятнадцати'.split()
TENS = {'nom':{20:'двадцать',30:'тридцать',40:'сорок',50:'пятьдесят'}, 'gen':{20:'двадцати',30:'тридцати',40:'сорока',50:'пятидесяти'}, 'dat':{20:'двадцати',30:'тридцати',40:'сорока',50:'пятидесяти'}}
ORD = ['','первая','вторая','третья','четвёртая','пятая','шестая','седьмая','восьмая','девятая','десятая','одиннадцатая','двенадцатая','тринадцатая','четырнадцатая']
LINK = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')

def small(n, case='nom'):
    assert 0 <= n < 60
    arr={'nom':NOM,'gen':GEN,'dat':DAT}[case]
    if n<20:return arr[n]
    return TENS[case][n//10*10]+(' '+arr[n%10] if n%10 else '')

def time_words(t, case='nom'):
    h,m=map(int,t.split(':'))
    assert 0<=h<=23 and 0<=m<=59
    if case=='nom':
        if m:return small(h)+' '+('ноль ' if m<10 else '')+small(m)
        end='час' if h%10==1 and h!=11 else 'часа' if h%10 in (2,3,4) and h not in (12,13,14) else 'часов'
        return small(h)+' '+end
    if case=='gen':return small(h,case)+' часов'+(' '+small(m,case)+' минут' if m else '')
    return small(h,case)+' часам'+(' '+small(m,case)+' минутам' if m else '')

def clocks(s):
    pattern=r'(?:(?P<p>на|вместо)\s+)?(?P<a>\d{1,2}:\d{2})[–—-](?P<b>\d{1,2}:\d{2})'
    def span(m):
        prefix={'на':'на интервал ','вместо':'вместо интервала ',None:''}[m['p']]
        return prefix+'с '+time_words(m['a'],'gen')+' до '+time_words(m['b'],'gen')
    s=re.sub(pattern,span,s)
    def one(m):
        prefix=m['p'] or ''
        case='gen' if prefix.strip() in ('с','до','около','после') else 'dat' if prefix.strip()=='к' else 'nom'
        return prefix+time_words(m['t'],case)
    return re.sub(r'(?P<p>\b(?:с|до|около|после|к|в|на)\s+)?(?P<t>\d{1,2}:\d{2})',one,s)

def mechanics(s, block_id):
    # All original citations are recorded separately before this function runs.
    # The one source-as-subject construction has a bespoke editorial replacement.
    s=LINK.sub('',s)
    s=re.sub(r'^>\s?', '',s,flags=re.M)
    s=s.replace('**','').replace('*','').replace('`','')
    s=re.sub(r'\s*₽', ' рублей', s)
    s=re.sub(r'\bруб\.', 'рублей',s)
    s=s.replace('4%','четыре процента').replace('10%','десять процентов')
    s=s.replace('А4','А четыре').replace('JPG','джей-пег')
    s=s.replace('Qlean','Клин').replace('JURA','Юра')
    s=clocks(s)
    s=re.sub(r'^(# Глава )([1-9]|1[0-4])\.',lambda m:m[1]+ORD[int(m[2])]+'.',s)
    s=s.replace('## Практика:', '## Практика.')
    s=re.sub(r' +([,.!?;:])',r'\1',s)
    s=re.sub(r'(?<=[.!?]) +\.', '',s)
    s=re.sub(r' {2,}',' ',s)
    return s.strip()

def main():
    out=HERE/'manuscript';out.mkdir(exist_ok=True)
    expected={x['file']:x['source_sha256'] for x in json.loads((HERE/'edition_manifest.json').read_text())['source_files']}
    records=[];citations=[];files=[];seen=set()
    for f in sorted(SOURCE.glob('*.md')):
        if f.name.startswith('99'):continue
        assert hashlib.sha256(f.read_bytes()).hexdigest()==expected[f.name],(f.name,'source changed; review editorial anchors before adapting')
        blocks=re.split(r'\n\s*\n',f.read_text().strip())
        result=[]
        for i,original in enumerate(blocks):
            key=f.name[:2]+f'-{i:03}';seen.add(key)
            for label,url in LINK.findall(original):citations.append({'source_block':key,'label':label,'url':url})
            text=EDITS.get(key,original)
            for a,b in PHRASES.get(key,[]):
                assert text.count(a)==1,(key,a,text)
                text=text.replace(a,b)
            text=mechanics(text,key)
            assert text,(key,'empty replacement')
            assert not text.startswith('|'),(key,'unadapted table')
            assert not re.search(r'[×÷≤≥]|https?://|\d{1,2}:\d{2}',text),(key,'unadapted notation')
            assert not re.search(r'\b(?:Ц|С)\b',text) or key!='05-045',(key,'unbound formula')
            result.append(text)
            records.append({'id':key,'source_file':f.name,'source_sha256':hashlib.sha256(original.encode()).hexdigest(),'audio_sha256':hashlib.sha256(text.encode()).hexdigest(),'authored_replacement':key in EDITS,'targeted_edit':key in PHRASES,'changed':text!=original,'source_chars':len(original),'audio_chars':len(text)})
        target=out/f.name;target.write_text('\n\n'.join(result)+'\n')
        files.append({'file':f.name,'source_sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'audio_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'blocks':len(blocks),'source_chars':len(f.read_text()),'audio_chars':len(target.read_text())})
    assert set(EDITS)|set(PHRASES)<=seen
    bib=(SOURCE/'99-bibliography.md').read_text()
    supplement='''\n\n## Текстовое приложение к главе седьмой\n\nТочные английские формулировки учебного примера сохранены здесь для сопоставления. В аудиоредакции их смысл разобран по-русски.\n\nРабочий перевод:\n\nAfter two meetings, I changed the order of the questions. I do not yet know whether this helped people give more precise answers: the second group was smaller than the first. Next month, I will try the new order again.\n\nОшибочно изменённая фраза:\n\nThe new order helped people give more precise answers.\n'''
    (out/'99-bibliography.md').write_text(bib.rstrip()+supplement)
    voice=['Елена Дым. Как продавать услуги.\n\nСерия «Секреты продвижения услуг». Книга первая.']
    for f in sorted(out.glob('*.md')):
        if f.name.startswith('99'):continue
        voice.append(re.sub(r'^#{1,3}\s+','',f.read_text().strip(),flags=re.M))
    (HERE/'Как-продавать-услуги_Аудиоредакция.txt').write_text('\n\n'.join(voice)+'\n')
    (HERE/'source_map.json').write_text(json.dumps({'source_commit':SOURCE_COMMIT,'source_edition':'1.1','audio_edition':'1.0','files':files,'citations':citations,'records':records},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'chapters':len(files),'source_blocks':len(records),'authored_replacements':sum(r['authored_replacement'] for r in records),'changed_blocks':sum(r['changed'] for r in records),'source_citations_preserved':len(citations),'audio_characters':sum(f['audio_chars'] for f in files),'tts_file':str(HERE/'Как-продавать-услуги_Аудиоредакция.txt')},ensure_ascii=False))

if __name__=='__main__':main()
