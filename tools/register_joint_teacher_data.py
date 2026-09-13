"""Verify prepared one/two-pass caches and write a paused, mode-aware recipe.

No optimizer, model inference, raw deletion, cache mutation or frozen-test metrics.
"""
import argparse
import json
from pathlib import Path
from datetime import datetime,timezone
from aligned_cohort import AlignedCohort
from prepare_conditioning_pilot import sha,save


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--one-pass',type=Path,required=True);p.add_argument('--two-pass',type=Path,required=True)
    p.add_argument('--one-audit',type=Path,required=True);p.add_argument('--two-audit',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    entries=[];seen_sequences={};seen_inputs={}
    for mode,root,audit_path in ((1,a.one_pass,a.one_audit),(2,a.two_pass,a.two_audit)):
        train=AlignedCohort(root,'train',expected_pass_count=mode)
        val=AlignedCohort(root,'validation',expected_pass_count=mode)
        complete=train.complete
        if sha(audit_path)!=complete['audit_sha256']:raise ValueError('Audit identity mismatch')
        membership={r['sequence_id']:r['split'] for r in train.rows}
        if set(train.sequence_ids)&set(val.sequence_ids):raise ValueError('Holdout overlap')
        for row in train.rows:
            if membership[row['sequence_id']]!=row['split']:raise ValueError('Split sequence')
        for seq,split in membership.items():
            if seq in seen_sequences:raise ValueError('Sequence duplicated across caches')
            seen_sequences[seq]=split
        audit=json.loads(audit_path.read_text())
        for seq in audit['sequences']:
            if seq['sequence'] not in membership:continue
            split=membership[seq['sequence']]
            for r in seq['records']:
                if r['stage']!='input':continue
                previous=seen_inputs.get(r['sha256'])
                if previous is not None and previous!=split:raise ValueError('Exact input duplicate crosses one/two-pass holdout boundary')
                seen_inputs[r['sha256']]=split
        entries.append(dict(teacher_pass_count=mode,root=str(root.resolve()),complete_sha256=sha(root/'complete.json'),
                            rows=len(train.rows),split=complete['split'],excluded=complete['excluded']))
        print(json.dumps(dict(teacher_pass_count=mode,verified=True,rows=len(train.rows))),flush=True)
    old_run=Path('E:/OpenNR_Training/stable_unet_broad_20260907/run.json')
    old=json.loads(old_run.read_text())
    roots=old['cohorts']+[str(a.one_pass.resolve()),str(a.two_pass.resolve())]
    plan=dict(schema='opennr-joint-teacher-training-plan-v1',state='prepared_paused',training_authorized=False,
              generated_at=datetime.now(timezone.utc).isoformat(),new_data=entries,cohorts=roots,
              cohort_labels=['prior','high_effect','renderer_pilot','fresh_session','two_pass'],
              teacher_pass_counts=[1,1,1,1,2],probabilities=[.30,.18,.12,.20,.20],seed=359,steps=1200,
              architecture='stable_unet_teacher_mode',initial_head_run=str(old_run.parent),
              cohort_complete_sha256=[sha(Path(r)/'complete.json') for r in roots],
              parent_run='E:/OpenNR_Training/aligned_retention_20260907_seed352',
              output='E:/OpenNR_Training/stable_unet_joint_teacher_20260907',
              test_used_for_tuning=False,cross_new_cache_exact_input_holdout_check='passed',
              limitations=['Chronological holdouts are not independent scene/session proof',
                           'Build/session/scene differences confound causal pass-count comparisons',
                           'Renderer features preserved but not consumed by this U-Net',
                           'No teacher-mode learning or quality benefit established; no optimization run'],
              source_sha256={name:sha(Path(__file__).with_name(name)) for name in
                             ['teacher_mode_head.py','train_spatial_tone.py','aligned_cohort.py','verify_spatial_tone.py']})
    a.output.mkdir(parents=True)
    save(a.output/'training_plan.json',plan)
    summary=['# Normal and amplified teacher data',
             '## Technical summary\n\nThe one-pass and two-pass caches are verified and registered together, with explicit teacher-mode labels. Training remains paused. This establishes data and code readiness, not that exaggerated targets are easier to learn.',
             '## Accepted data and exclusions\n\nThe prepared one-pass batch contains '+str(entries[0]['rows']//128)+' complete stereo clips; the amplified batch contains '+str(entries[1]['rows']//128)+'. Each clip has 64 frames and both eyes. The single-frame two-pass capture is preserved but excluded from temporal training. A second clip has an all-zero left-eye vertex-AO mask throughout the sequence and remains in manual review; this can be legitimate scene content and is not proof of corruption. Source data were not moved or deleted.',
             '## Scope and target definitions\n\nNormal targets are final one-pass Feature 18 outputs; amplified targets are final two-pass outputs paired with the original pre-NR input. Depth, motion and six renderer buffers are retained. Both sessions use 100% model resolution and matching observed teacher tuning, but differ in scenes and build labels. This is not a paired causal comparison.',
             '## Integrity and alignment\n\nAcceptance checks cover structural bytes, finite decoded content, native crop coverage, exact 64-frame continuity and reset, nonconstant streams, row identities and array hashes. Representative aligned sheets show corresponding geometry within each eye and strong teacher shading. Same-eye edge evidence is diagnostic, not proof of subpixel alignment. Exact input duplicates are prohibited across splits in the two new caches.',
             '## Model and experimental design\n\nThe prepared U-Net receives an explicit one-pass or two-pass request through a zero-initialized 16-channel stem offset. Tests verify initial output equivalence and mode gradients. Shared weights remain trainable, so retention is not guaranteed. The five-cohort mixture is 30% prior,18% high-effect,12% older renderer,20% fresh one-pass,20% two-pass. Each cohort retains separate validation and scores. The intended run is 1,200 updates; it has not started.',
             '## Limits and robustness\n\nLarger target changes do not automatically make pixel L1 optimization easier. Exaggeration can amplify artifacts and clipping as well as desirable appearance. The one-pass 0.011 goal must remain a separate benchmark. Chronological holdouts share a capture session and can share scenes. Frozen tests are not used for tuning. Full-renderer-channel conditioning is not implemented in this architecture.',
             '## Next step and open questions\n\nAwait explicit permission to train. Afterward, compare ordinary fitting, held-out MAE and temporal error separately for each mode, and inspect faces, highlights, shadows and material texture. To establish whether two-pass data improves normal-mode learning, use a matched no-two-pass control. The current preparation cannot answer that learning question.']
    title='Normal and amplified teacher data'
    artifact=dict(surface='report',manifest=dict(version=1,surface='report',title=title,generatedAt=plan['generated_at'],
                  sources=[dict(id='intake',label='Verified local teacher-data integration',path='docs/TWOPASS_DATA_INTEGRATION_20260907.md')],
                  blocks=[dict(id='section-'+str(i),type='markdown',body=text,**({'sourceId':'intake'} if i else {})) for i,text in enumerate(summary)]),
                  snapshot=dict(version=1,generatedAt=plan['generated_at'],status='ready',datasets={}))
    save(a.output/'artifact.json',artifact)
    print(json.dumps(dict(state='prepared_paused',training_started=False,output=str(a.output))),flush=True)


if __name__=='__main__':main()
