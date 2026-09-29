"""Compare worker-prefetched samples to manual sampling across an epoch boundary."""
import pickle
import torch
from torch.utils.data import DataLoader,default_collate
from dynamic_patches import DynamicPatches
from prefetch_dynamic import EpochBatches
from train_long_student import epoch_indices


def main():
    torch.set_num_threads(2)
    data=DynamicPatches('C:/OpenNR/TrainingCache/student_v1','C:/OpenNR/TrainingCache/dynamic_guides_v1')
    assert len(pickle.dumps(data))<4096,'Dataset serializes mapped image arrays'
    batches=EpochBatches(len(data),4,1927,1931)
    loader=DataLoader(data,batch_sampler=batches,num_workers=2,pin_memory=False)
    for step,actual in zip(range(1927,1932),loader):
        ids,epoch=epoch_indices(len(data),4,step);data.set_epoch(epoch)
        expected=default_collate([data[i] for i in ids])
        for key in ('rgb','target','guides','context','eye','index'):assert torch.equal(actual[key],expected[key]),(step,key)
        assert actual['seq']==expected['seq']
    print('PASS: Windows worker serialization, epoch crossing, resume indices and exact tensors')


if __name__=='__main__':main()
