"""Source integration checks; not a GPU or in-game acceptance test."""
import hashlib,json,re
from pathlib import Path
root=Path(__file__).resolve().parents[2]
src=root/'runtime/open-shaders/src/Features/Upscaling'
def read(p): return p.read_text(encoding='utf-8-sig')
contract=json.loads(read(root/'scripts/v07/source-contract.json'))
for name,expected in contract.items():
    p=root/name
    actual=hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest() if p.exists() else None
    assert actual==expected['after'], ('Postimage mismatch',name)
protected=json.loads(read(root/'scripts/v07/retained-gaze.json'))
for name,expected in protected.items():
    actual=hashlib.sha256((root/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
    assert actual==expected, ('Retained gaze/guide file changed',name)
fov=read(src/'FoveatedRender.cpp');h=read(src/'FoveatedRender.h')
integration=read(src/'NeuralRendering/Integration.cpp')
shader=read(root/'runtime/open-shaders/features/Upscaling/Shaders/Upscaling/NeuralRendering/ResultShapingCS.hlsl')
page=read(src.parent/'Upscaling.cpp');schema=read(src.parent/'RemoteControl/DevBenchBridge.cpp')
for p in (root/'runtime/open-shaders/src').rglob('*'):
    if p.suffix in ('.cpp','.h'):
        assert 'SettingsBenchmark' not in read(p), ('Retired benchmark reference',p)
        assert 'OutsideTone' not in read(p), ('Retired outside seam reference',p)
serialized=fov[fov.index('#define OPENNR_FOVEATED_SETTINGS_FIELDS'):fov.index('template <typename BasicJsonType>',fov.index('#define OPENNR_FOVEATED_SETTINGS_FIELDS'))]
fields=re.findall(r'X\((\w+)\)',serialized)
assert len(fields)==len(set(fields)), 'Duplicate serialized field'
for name in ('neuralRenderingForcedStage','neuralRenderingCropDrop','neuralRenderingDisableAboveMs','neuralRenderingEnableBelowMs'):
    assert name in fields
for name in ('neuralRenderingSinglePassLadder','neuralRenderingStyle','neuralRenderingCoverage','neuralRenderingModelResolution','neuralRenderingResolveMode','neuralRenderingMultiPass','neuralRenderingStereoAtlas','neuralRenderingTemporalReuseCadence','neuralRenderingStabilizeMode','neuralRenderingEyeTrackedDeadZonePercent','subrectBlendMode','subrectFeatherWidth','subrectFalloffCurve','subrectDitherStrength','stretchMode','dlssMode'):
    assert name not in fields, ('Retired setting serialized',name)
for token in ('tuning.style = 0;', 'tuning.modelResolveMode = 1;', 'tuning.multiPass = 0;',
              'tuning.stereoAtlas = true;', 'tuning.temporalReuseCadence = 0;', 'tuning.stabilizeMode = 0;'):
    assert token in integration, ('Runtime invariant missing',token)
assert 'SimpleFramePolicy::Select' not in fov
assert 'bool IsOutputTransitioning() const;' in read(src/'NeuralRendering/Renderer.h')
assert 'return state_->IsOutputTransitioning();' in read(src/'NeuralRendering/Renderer.cpp')
assert 'cropPolicyAvailable && !envelopeRejected && !decisionsSuspended' in fov
assert 'committedRenderCrop == adaptiveCropTargetCoverage' in fov
assert 'adaptiveActivePasses > 0 && nrRenderer.IsOutputTransitioning()' in fov
assert 'if (adaptiveUpdateFrame == frame) return;' in fov
assert shader.index('gHistoryOutput[pixel]') < shader.index('gNearBlackProtection > 0.0') < shader.index('delta * saturate(gResumeBlendAlpha)')
assert 'configureAdaptivePerformance' in page and 'configureAdaptivePerformance' in schema
assert 'cropDrop integer 10,15,20' in page and 'cropDrop integer 10,15,20' in schema
assert 'forcedStage integer 0 Auto' in page and 'forcedStage integer 0 Auto' in schema
assert 'DrawDLSSNRSharedControls();' not in page
assert 'Force stage 6 (NR off)' in fov
assert 'Force one-pass atlas' not in fov
report={'source_contract_files':len(contract),'retained_gaze_files':len(protected),
        'benchmark_removed':True,'outside_seam_removed':True,'one_controller':True,
        'permanent_atlas':True,'near_black_raw_history_order_preserved':True,
        'hardware_gpu_timing_and_headset_acceptance':False}
(root/'audit-results').mkdir(exist_ok=True)
(root/'audit-results/r7-source-audit.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
