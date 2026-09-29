"""Stateless resumable batches for Windows dynamic-crop worker prefetch."""
import math
import numpy as np


class EpochBatches:
    def __init__(self,length,batch,start_step,end_step,seed=137):
        self.length=length;self.batch=batch;self.start=start_step;self.end=end_step;self.seed=seed

    def __len__(self):return max(0,self.end-self.start+1)

    def __iter__(self):
        per_epoch=math.ceil(self.length/self.batch);last_epoch=None;order=None
        for step in range(self.start,self.end+1):
            epoch,offset=divmod(step-1,per_epoch)
            if epoch!=last_epoch:order=np.random.default_rng(self.seed+epoch).permutation(self.length);last_epoch=epoch
            yield [(epoch,int(i)) for i in order[offset*self.batch:min((offset+1)*self.batch,self.length)]]
