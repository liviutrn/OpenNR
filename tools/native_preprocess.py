"""CUDA-only conversion from native capture buffers to student inputs and back."""
import ctypes as C
import math
from pathlib import Path
import torch

class NativePreprocessor:
    def __init__(self,w=2496,h=2688,gw=1664,gh=1792):
        if min(w,h,gw,gh)<=0 or w%96 or h%96 or w%4 or h%4:raise ValueError('Current native context kernel requires positive dimensions divisible by96 and4')
        self.w,self.h,self.gw,self.gh=w,h,gw,gh
        torch.cuda.init();self._context_guard=torch.empty(1,device='cuda');library=Path(torch.__file__).parent/'lib';self.nvrtc=C.WinDLL(str(library/'nvrtc64_120_0.dll'));self.driver=C.WinDLL('nvcuda.dll')
        nv=self.nvrtc
        nv.nvrtcCreateProgram.argtypes=[C.POINTER(C.c_void_p),C.c_char_p,C.c_char_p,C.c_int,C.c_void_p,C.c_void_p]
        nv.nvrtcCompileProgram.argtypes=[C.c_void_p,C.c_int,C.POINTER(C.c_char_p)]
        for name in ('nvrtcGetProgramLogSize','nvrtcGetPTXSize'):getattr(nv,name).argtypes=[C.c_void_p,C.POINTER(C.c_size_t)]
        for name in ('nvrtcGetProgramLog','nvrtcGetPTX'):getattr(nv,name).argtypes=[C.c_void_p,C.c_void_p]
        nv.nvrtcDestroyProgram.argtypes=[C.POINTER(C.c_void_p)]
        program=C.c_void_p();self.check(nv.nvrtcCreateProgram(C.byref(program),Path(__file__).with_suffix('.cu').read_bytes(),b'native_preprocess.cu',0,None,None),'create NVRTC')
        capability=torch.cuda.get_device_capability();options=(C.c_char_p*2)(f'--gpu-architecture=compute_{capability[0]}{capability[1]}'.encode(),b'--std=c++14');code=nv.nvrtcCompileProgram(program,2,options)
        if code:
            size=C.c_size_t();nv.nvrtcGetProgramLogSize(program,C.byref(size));log=C.create_string_buffer(size.value);nv.nvrtcGetProgramLog(program,log);nv.nvrtcDestroyProgram(C.byref(program));raise RuntimeError(log.value.decode())
        size=C.c_size_t();self.check(nv.nvrtcGetPTXSize(program,C.byref(size)),'PTX size');ptx=C.create_string_buffer(size.value);self.check(nv.nvrtcGetPTX(program,ptx),'PTX');nv.nvrtcDestroyProgram(C.byref(program))
        d=self.driver;d.cuModuleLoadData.argtypes=[C.POINTER(C.c_void_p),C.c_void_p];d.cuModuleGetFunction.argtypes=[C.POINTER(C.c_void_p),C.c_void_p,C.c_char_p]
        d.cuLaunchKernel.argtypes=[C.c_void_p,C.c_uint,C.c_uint,C.c_uint,C.c_uint,C.c_uint,C.c_uint,C.c_uint,C.c_void_p,C.POINTER(C.c_void_p),C.c_void_p]
        self.module=C.c_void_p();self.check(d.cuModuleLoadData(C.byref(self.module),ptx),'module load');self.functions={}
        for name in ('unpack_rgb','prepare_guides','prepare_context','pack_output'):
            function=C.c_void_p();self.check(d.cuModuleGetFunction(C.byref(function),self.module,name.encode()),name);self.functions[name]=function
        self.rgb=torch.empty((1,3,h,w),device='cuda');self.guides=torch.empty((1,5,h//4,w//4),device='cuda');self.context=torch.empty((1,8,96,96),device='cuda');self.rgba=torch.empty((h,w,4),device='cuda',dtype=torch.uint8)
    @staticmethod
    def check(value,operation):
        if value:raise RuntimeError(f'{operation}: CUDA/NVRTC error {value}')
    def launch(self,name,n,args):
        values=[C.c_void_p(x.data_ptr()) if isinstance(x,torch.Tensor) else C.c_float(x) if isinstance(x,float) else C.c_int(x) for x in args]
        pointers=(C.c_void_p*len(values))(*[C.cast(C.pointer(x),C.c_void_p) for x in values]);self.check(self.driver.cuLaunchKernel(self.functions[name],(n+255)//256,1,1,256,1,1,0,torch.cuda.current_stream().cuda_stream,pointers,None),name)
    def __call__(self,color,depth,motion,scale):
        for value,shape,dtype in ((color,(self.h,self.w,4),torch.uint8),(depth,(self.gh,self.gw),torch.float32),(motion,(self.gh,self.gw,2),torch.float16)):
            if not value.is_cuda or value.device!=self.rgb.device or not value.is_contiguous() or tuple(value.shape)!=shape or value.dtype!=dtype:raise ValueError('Native buffer contract mismatch')
        if len(scale)!=2 or not all(math.isfinite(float(x)) for x in scale):raise ValueError('Two finite per-eye motion scales required')
        sx=float(scale[0]*self.w/self.gw/128);sy=float(scale[1]*self.h/self.gh/128)
        self.launch('unpack_rgb',self.w*self.h,[color,self.rgb,self.w,self.h])
        self.launch('prepare_guides',self.w//4*(self.h//4),[depth,motion,self.guides,self.gw,self.gh,self.w//4,self.h//4,sx,sy])
        self.launch('prepare_context',96*96,[color,depth,motion,self.context,self.w,self.h,self.gw,self.gh,sx,sy])
        return self.rgb,self.guides,self.context
    def pack(self,prediction):
        if prediction.device!=self.rgb.device or prediction.dtype!=torch.float32 or prediction.shape!=self.rgb.shape or not prediction.is_contiguous():raise ValueError('Output must match native contiguous CUDA FP32 RGB')
        self.launch('pack_output',self.w*self.h,[prediction,self.rgba,self.w,self.h]);return self.rgba
