"""Add the dated findings to the existing full portable report; preserve history."""
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from prepare_conditioning_pilot import save

root=Path('out/joint_teacher_data_20260907')
path=root/'artifact.json'
original=json.loads(path.read_text())
backup=root/'artifact_before_findings_20260908.json'
if not backup.exists():save(backup,original)
artifact=copy.deepcopy(original)
blocks=artifact['manifest']['blocks']
blocks[:]=[b for b in blocks if not b['id'].startswith('findings-20260908-')]
source={'id':'findings-20260908','label':'OpenNR verified endpoint and matched conditioning findings',
        'path':'docs/OPENNR_LATEST_FINDINGS_20260908.md'}
sources=artifact['manifest']['sources']
sources[:]=[s for s in sources if s['id']!=source['id']]
sources.append(source)
text=Path(source['path']).read_text(encoding='utf-8')
sections=text.split('\n## ')[1:]
new=[]
for i,section in enumerate(sections):
    if section.startswith('Evidence pointers'):continue
    new.append({'id':f'findings-20260908-{i}','type':'markdown','body':'## '+section.strip(),'sourceId':source['id']})
new.insert(0,{'id':'findings-20260908-snapshot','type':'markdown',
              'body':'September 8, 2026 snapshot: new conditioning validation through update 400. Later optimizer updates are not represented here.'})
new.append({'id':'findings-20260908-history','type':'markdown',
            'body':'## Historical intake and initial experiment\n\nThe following sections preserve the original intake and 1,200-update launch report. Their launch-state and next-step wording is historical; the findings above supersede it.'})
blocks[1:1]=new
now=datetime.now(timezone.utc).isoformat()
artifact['manifest']['generatedAt']=now
artifact['snapshot']['generatedAt']=now
# Preserve every unrelated block, chart, dataset and source.
old_blocks=[b for b in original['manifest']['blocks'] if not b['id'].startswith('findings-20260908-')]
assert [b for b in blocks if not b['id'].startswith('findings-20260908-')]==old_blocks
assert artifact['manifest']['charts']==original['manifest']['charts']
assert artifact['snapshot']['datasets']==original['snapshot']['datasets']
save(path,artifact)
save(root/'findings_report_notes_20260908.json',{
    'audience':'technical','delivery':'existing portable HTML report refresh',
    'structure':'summary; definitions before findings; endpoint; paired result; design; limitations and decisions; open questions; historical intake retained',
    'visual_contract':'Existing six-category split bar and source data preserved. New five-cohort comparison is an exact-lookup table: sub-0.000008 differences should not be visually exaggerated. No trend chart with only one post-baseline arm checkpoint.',
    'scope':'Documentation/report update only; no active training code modified',
    'history_preservation_checked':True})
print('Updated full artifact; original blocks/charts/datasets preserved.')
