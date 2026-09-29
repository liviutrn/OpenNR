"""Training-only hard-sequence manifest from a completed full causal fit report."""
import argparse
import hashlib
import json
import math
from pathlib import Path


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def rank_cohort(cohort, fraction=.2):
    metrics=cohort['train']
    scores=metrics['sequence_mae']
    members=cohort['training_sequences']
    if metrics['split']!='train' or len(members)!=len(set(members)) or set(scores)!=set(members):
        raise ValueError('Training membership mismatch')
    if set(members)&set(cohort['validation']['sequence_mae']):
        raise ValueError('Training/validation overlap')
    if not scores or not all(math.isfinite(v) and v>=0 for v in scores.values()):
        raise ValueError('Invalid training errors')
    ordered=sorted(scores,key=lambda key:(-scores[key],key))
    count=max(1,math.ceil(len(ordered)*fraction))
    hard=ordered[:count]
    return {'sequence_count':len(ordered),'hard_count':count,'hard_sequence_ids':hard,
            'ranked_training_mae':[{'sequence_id':key,'mae':scores[key]} for key in ordered],
            'hard_mean_mae':sum(scores[key] for key in hard)/count,
            'all_sequence_mean_mae':sum(scores.values())/len(scores),
            'hard_error_share':sum(scores[key] for key in hard)/sum(scores.values()) if sum(scores.values()) else 0,
            'overlay_complete_sha256':cohort['overlay_complete_sha256']}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--fit-report',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError(args.output)
    if json.loads(args.fit_report.with_name('status.json').read_text())['state']!='complete':raise ValueError('Incomplete fit')
    source=json.loads(args.fit_report.read_text())
    if source['test_used'] or digest(source['checkpoint'])!=source['sha256']:raise ValueError('Checkpoint/provenance mismatch')
    result={'schema':'opennr-hard-training-sequences-v1','fit_report':str(args.fit_report),
            'fit_report_sha256':digest(args.fit_report),'checkpoint':source['checkpoint'],
            'checkpoint_sha256':source['sha256'],'step':source['step'],'test_used':False,
            'ranking_scope':'whole training sequences, not individual crops or face annotations',
            'fraction':.2,'proposed_sampling':'within each cohort: 50% uniform all sequences, 50% uniform hard set; eyes and window starts uniform',
            'cohorts':{key:rank_cohort(value) for key,value in source['cohorts'].items()}}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    for key,value in result['cohorts'].items():
        print(json.dumps({'cohort':key,**{k:value[k] for k in ('sequence_count','hard_count','hard_mean_mae','all_sequence_mean_mae','hard_error_share')}}))


if __name__=='__main__':main()
