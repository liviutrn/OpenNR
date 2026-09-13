"""Signed code-value luma and RGB errors; not physical luminance or skin labels."""
import torch


def tone_metrics(pred,target,source):
    weights=pred.new_tensor([.2126,.7152,.0722])[None,:,None,None]
    py=(pred*weights).sum(1);ty=(target*weights).sum(1);sy=(source*weights).sum(1)
    lo=torch.quantile(ty.flatten(1),.2,dim=1)[:,None,None]
    hi=torch.quantile(ty.flatten(1),.8,dim=1)[:,None,None]
    masks={'all':torch.ones_like(ty,dtype=torch.bool),'teacher_dark_quintile':ty<=lo,
           'teacher_bright_quintile':ty>=hi,'teacher_brightens':ty-sy>.02,'teacher_darkens':ty-sy<-.02}
    result={}
    for name,mask in masks.items():
        count=int(mask.sum())
        if not count:result[name]={'pixels':0};continue
        rgb=(pred-target).permute(0,2,3,1)[mask]
        d=(py-ty)[mask]
        result[name]={'pixels':count,'signed_luma_error':float(d.mean()),'luma_mae':float(d.abs().mean()),
                      'signed_rgb_error':rgb.mean(0).cpu().tolist(),'rgb_mae':float(rgb.abs().mean()),
                      'teacher_minus_input_luma':float((ty-sy)[mask].mean())}
    return result


def self_test():
    source=torch.zeros(1,3,2,5)
    target=torch.linspace(0,1,10).reshape(1,1,2,5).repeat(1,3,1,1)
    pred=.5*target+.25
    r=tone_metrics(pred,target,source)
    assert r['teacher_dark_quintile']['signed_luma_error']>0
    assert r['teacher_bright_quintile']['signed_luma_error']<0
    assert r['teacher_darkens']['pixels']==0
    identical=tone_metrics(target,target,source)
    assert identical['all']['rgb_mae']==0
    assert r['all']['pixels']==10


if __name__=='__main__':
    self_test();print('PASS: signed tone errors, masks, zero-error identity')
