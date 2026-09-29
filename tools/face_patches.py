"""Two face-directed slots plus six unchanged general crops per training eye."""
import hashlib,json
from pathlib import Path
import numpy as np
import torch
from dynamic_patches import DynamicPatches

class FacePatches(DynamicPatches):
    def __init__(self,cache,guides,faces,color_io='mmap',patch_size=512):
        super().__init__(cache,guides,color_io,patch_size)
        self.face_path=Path(faces);raw=self.face_path.read_bytes()
        self.face_sha256=hashlib.sha256(raw).hexdigest();meta=json.loads(raw)
        base=json.loads((self.root/'complete.json').read_text())
        if meta['rows_sha256']!=base['rows_sha256'] or not meta['training_only'] or not meta['input_only'] or meta['selection']!='all training eyes':raise ValueError('Face sampling requires training-only input audit')
        self.faces={r['row']:r['boxes'] for r in meta['records']}
        if len(self.faces)!=len(meta['records']) or set(self.faces)!=set(self.row_ids):raise ValueError('Face row mapping mismatch')
        for ri,boxes in self.faces.items():
            w,h=self.rows[ri]['color_size']
            for box in boxes:
                x1,y1,x2,y2=box['xyxy']
                if not np.isfinite([x1,y1,x2,y2,box['confidence']]).all() or not (0<=x1<x2<=w and 0<=y1<y2<=h and .85<=box['confidence']<=1):raise ValueError('Invalid face box')

    def __getstate__(self):
        state=super().__getstate__();state['faces']=str(self.face_path);return state

    def __setstate__(self,state):
        self.__init__(state['cache'],state['guides'],state['faces'],state['color_io'],state['patch_size']);self.epoch=state['epoch']

    def box(self,index,epoch=None):
        general=super().box(index,epoch)
        boxes=self.faces[self.row_ids[index//8]]
        if index%8>=2 or not boxes:return general
        epoch=self.epoch if epoch is None else epoch
        rng=np.random.default_rng(np.random.SeedSequence([2719,epoch,index]))
        x1,y1,x2,y2=boxes[int(rng.integers(len(boxes)))]['xyxy']
        # Jitter the crop center inside the central 70% of the detected face.
        cx=rng.uniform(x1+.15*(x2-x1),x2-.15*(x2-x1))
        cy=rng.uniform(y1+.15*(y2-y1),y2-.15*(y2-y1))
        w,h=self.rows[self.row_ids[index//8]]['color_size'];size=self.patch_size;half=size/2
        x=int(np.clip(round((cx-half)/4)*4,0,w-size));y=int(np.clip(round((cy-half)/4)*4,0,h-size))
        return x,y,size,size

    def __getitem__(self,index):
        """Return the normal crop plus an input-space mask for detected faces.

        The mask is derived from the same native-resolution boxes and crop that
        produced the sample.  It is therefore deterministic, four-pixel aligned
        with the guides, and remains safe to pickle/reopen in Windows workers.
        """
        epoch=self.epoch
        if isinstance(index,tuple):
            epoch,index=index
        sample=super().__getitem__((epoch,index))
        x,y,pw,ph=sample['box']
        row_id=self.row_ids[index//8]
        mask=np.zeros((ph,pw),dtype=np.float32)
        for face in self.faces[row_id]:
            fx1,fy1,fx2,fy2=face['xyxy']
            ix1=max(x,int(np.ceil(fx1)));iy1=max(y,int(np.ceil(fy1)))
            ix2=min(x+pw,int(np.floor(fx2)));iy2=min(y+ph,int(np.floor(fy2)))
            if ix2>ix1 and iy2>iy1:
                mask[iy1-y:iy2-y,ix1-x:ix2-x]=1.
        sample['face_mask']=torch.from_numpy(mask[None])
        return sample
