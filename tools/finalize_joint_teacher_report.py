"""Narrow correction of the full report: add verified split chart and launch state."""
import json
import sqlite3
from datetime import datetime,timezone
from pathlib import Path
from prepare_conditioning_pilot import save

root=Path('out/joint_teacher_data_20260907')
artifact=json.loads((root/'artifact.json').read_text())
plan=json.loads((root/'training_plan.json').read_text())
rows=[]
for entry in plan['new_data']:
    for split in ('train','validation','test'):
        count=len(entry['split'][split])
        rows.append(dict(category=f"{entry['teacher_pass_count']}x {split}",teacher_pass_count=entry['teacher_pass_count'],
                         split=split,sequences=count,stereo_frames=count*64,eye_examples=count*128,
                         accepted_mode_total=entry['rows']//128))
artifact['snapshot']['datasets']['splits']=rows
db=sqlite3.connect(':memory:')
db.row_factory=sqlite3.Row
db.execute('CREATE TABLE registry(document TEXT)')
db.execute('INSERT INTO registry VALUES (?)',(json.dumps(plan),))
query="""WITH modes AS (
 SELECT json_extract(m.value,'$.teacher_pass_count') AS mode,
 json_extract(m.value,'$.split') AS splits,
 json_extract(m.value,'$.rows') AS eye_rows
 FROM registry, json_each(registry.document,'$.new_data') AS m
), names AS (SELECT 'train' AS split,1 AS ordinal UNION ALL SELECT 'validation',2 UNION ALL SELECT 'test',3),
 counts AS (SELECT mode,split,ordinal,eye_rows,json_array_length(json_extract(splits,'$.'||split)) AS sequences FROM modes CROSS JOIN names)
SELECT mode||'x '||split AS category,mode AS teacher_pass_count,split,sequences,
sequences*64 AS stereo_frames,sequences*128 AS eye_examples,eye_rows/128 AS accepted_mode_total
FROM counts ORDER BY mode,ordinal"""
sql_rows=[dict(r) for r in db.execute(query)]
if sql_rows!=rows:raise ValueError('SQL count replay differs from registry membership count')
artifact['snapshot']['datasets']['splits']=sql_rows
artifact['manifest']['charts']=[dict(id='split_counts',title='New sequence counts by teacher mode and split',
    subtitle='Complete 64-frame clips only; two two-pass captures excluded or awaiting review',type='bar',dataset='splits',sourceId='intake',
    encodings=dict(x=dict(field='category',type='ordinal',label='Teacher mode and split'),
                   y=dict(field='sequences',type='quantitative',label='Sequences',format='number')))]
chart=artifact['manifest']['charts'][0]
chart.pop('sourceId')
chart['source']=dict(label='Verified joint registry split membership',path='out/joint_teacher_data_20260907/training_plan.json',
    query=dict(language='python',engine='Python',tables_used=['training_plan.json.new_data'],
               description='Count immutable sequence membership by teacher pass count and split; no model metrics or frozen-test inference.',
               sql="import json\nfrom pathlib import Path\nplan=json.loads(Path('out/joint_teacher_data_20260907/training_plan.json').read_text())\nrows=[]\nfor entry in plan['new_data']:\n    for split in ('train','validation','test'):\n        count=len(entry['split'][split])\n        rows.append(dict(category=f\"{entry['teacher_pass_count']}x {split}\",teacher_pass_count=entry['teacher_pass_count'],split=split,sequences=count,stereo_frames=count*64,eye_examples=count*128,accepted_mode_total=entry['rows']//128))\nprint(rows)"))
blocks=artifact['manifest']['blocks']
chart['source']['query']=dict(sql=query,language='sql',engine='SQLite',tables_used=['registry'],
    description='SQLite registry.document contains the exact training_plan.json object; counts use immutable sequence membership, not model metrics.')
if not any(b['id']=='split-chart' for b in blocks):
    blocks.insert(3,dict(id='split-chart',type='chart',chartId='split_counts'))
for b in blocks:
    if b['id']=='section-1':b['body']=b['body'].replace('Training remains paused.','The user subsequently authorized training, and the joint job has launched into initial baseline evaluation; optimizer updates are not yet confirmed.')
    if b['id']=='section-2' and 'The chart below' not in b['body']:b['body']+=' The chart below shows the preserved one-pass split of 16/5/6 and the separate two-pass split of 6/2/2 (train/validation/test). Small two-pass validation coverage limits generalization conclusions.'
    if b['id']=='section-5':b['body']=b['body'].replace('it has not started.','the process has launched, with baseline replay preceding optimizer updates.')
    if b['id']=='section-7':b['body']=b['body'].replace('Await explicit permission to train. Afterward,','Training authorization has now been given. After baseline replay and optimization,')
status_path=Path(plan['output'])/'status.json'
if status_path.exists():
    live=json.loads(status_path.read_text())
    if live.get('step',0)>0:
        for b in blocks:
            if b['id']=='section-1':
                b['body']='## Technical summary\n\nBoth new caches are verified and registered with explicit teacher-mode labels. The user authorized training after preparation, and the joint job has reached update '+str(live['step'])+'. This establishes actual optimization, not improved held-out quality or that exaggerated targets are easier to learn. Goal MAE0.011 remains unmet.'
    note=' The chart below shows the preserved one-pass split of 16/5/6 and the separate two-pass split of 6/2/2 (train/validation/test). Small two-pass validation coverage limits generalization conclusions.'
    for b in blocks:
        if b['id']=='section-2':b['body']=b['body'].replace(note,'')+note
    now=datetime.now(timezone.utc).isoformat()
    artifact['manifest']['generatedAt']=now;artifact['snapshot']['generatedAt']=now
save(root/'artifact.json',artifact)
save(root/'chart_notes.json',dict(question='How are accepted new sequences split by teacher mode?',
    takeaway='One-pass16/5/6 and two-pass6/2/2 remain separate; amplified validation has only2sequences.',
    family='comparison',variant='single-series categorical bar',rows=6,grain='teacher mode x split',
    surface='portable HTML canonical artifact',palette='shared reader single-root default; direct category labels; no redundant legend',
    qa='packaged report verifier; zero-baseline absolute counts',source='training_plan.json new_data split membership',
    report_sections='Title,technical summary,findings,scope,integrity,model design,limits,next questions; visual evidence also in linked raw-audit galleries'))
