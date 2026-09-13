#include <cuda.h>
#include <memory>
namespace {
thread_local std::string bridgeError;
HMODULE driver=LoadLibraryW(L"nvcuda.dll");
template<class T>T Function(const char* name){auto f=reinterpret_cast<T>(GetProcAddress(driver,name));if(!f)throw std::runtime_error(name);return f;}
void Cuda(CUresult value,const char* name){if(value!=CUDA_SUCCESS)throw std::runtime_error(std::string(name)+" CUDA="+std::to_string(value));}
struct Imported {
    HANDLE handle=nullptr;CUexternalMemory memory=nullptr;CUmipmappedArray mip=nullptr;CUarray array=nullptr;UINT w=0,h=0;
};
struct Bridge {
    Bench bench;std::array<Eye,2> eyes;std::array<std::array<Imported,4>,2> imported;HANDLE fenceHandle=nullptr;CUexternalSemaphore semaphore=nullptr;
    ~Bridge(){
        for(auto& eye:imported)for(auto& item:eye){if(item.mip)Function<decltype(&cuMipmappedArrayDestroy)>("cuMipmappedArrayDestroy")(item.mip);if(item.memory)Function<decltype(&cuDestroyExternalMemory)>("cuDestroyExternalMemory")(item.memory);if(item.handle)CloseHandle(item.handle);}
        if(semaphore)Function<decltype(&cuDestroyExternalSemaphore)>("cuDestroyExternalSemaphore")(semaphore);if(fenceHandle)CloseHandle(fenceHandle);
    }
    void Init(const wchar_t* path){
        std::ifstream config{std::filesystem::path(path)};UINT w,h,gw,gh,count;config>>w>>h>>gw>>gh>>count;config.ignore(10000,'\n');std::string unused;for(int i=0;i<3;++i)std::getline(config,unused);
        bench.sharedResources=true;bench.Initialize();
        for(int e=0;e<2;++e){for(int j=0;j<3;++j){std::string raw;std::getline(config,raw);eyes[e].textures[j]=bench.Texture(j?gw:w,j?gh:h,j==0?DXGI_FORMAT_R8G8B8A8_UNORM:j==1?DXGI_FORMAT_R32_FLOAT:DXGI_FORMAT_R16G16_FLOAT,raw);}config>>eyes[e].mx>>eyes[e].my;config.ignore(10000,'\n');eyes[e].textures[3]=bench.Texture(w,h,DXGI_FORMAT_R8G8B8A8_UNORM);}
        if(!config)throw std::runtime_error("bridge input config");bench.Submit();bench.uploads.clear();
        for(int e=0;e<2;++e)for(int j=0;j<4;++j){
            auto& item=imported[e][j];auto* texture=eyes[e].textures[j].Get();auto desc=texture->GetDesc();item.w=static_cast<UINT>(desc.Width);item.h=desc.Height;
            Check(bench.device->CreateSharedHandle(texture,nullptr,GENERIC_ALL,nullptr,&item.handle),"resource shared handle");CUDA_EXTERNAL_MEMORY_HANDLE_DESC memory{};memory.type=CU_EXTERNAL_MEMORY_HANDLE_TYPE_D3D12_RESOURCE;memory.handle.win32.handle=item.handle;memory.size=bench.device->GetResourceAllocationInfo(0,1,&desc).SizeInBytes;memory.flags=CUDA_EXTERNAL_MEMORY_DEDICATED;
            Cuda(Function<decltype(&cuImportExternalMemory)>("cuImportExternalMemory")(&item.memory,&memory),"import D3D12 memory");CUDA_EXTERNAL_MEMORY_MIPMAPPED_ARRAY_DESC mapping{};mapping.arrayDesc.Width=item.w;mapping.arrayDesc.Height=item.h;mapping.arrayDesc.Format=j==1?CU_AD_FORMAT_FLOAT:j==2?CU_AD_FORMAT_HALF:CU_AD_FORMAT_UNSIGNED_INT8;mapping.arrayDesc.NumChannels=j==1?1:j==2?2:4;mapping.arrayDesc.Flags=CUDA_ARRAY3D_SURFACE_LDST;mapping.numLevels=1;
            Cuda(Function<decltype(&cuExternalMemoryGetMappedMipmappedArray)>("cuExternalMemoryGetMappedMipmappedArray")(&item.mip,item.memory,&mapping),"map D3D12 array");Cuda(Function<decltype(&cuMipmappedArrayGetLevel)>("cuMipmappedArrayGetLevel")(&item.array,item.mip,0),"array level");
        }
        Check(bench.device->CreateSharedHandle(bench.fence.Get(),nullptr,GENERIC_ALL,nullptr,&fenceHandle),"fence shared handle");CUDA_EXTERNAL_SEMAPHORE_HANDLE_DESC semaphoreDesc{};semaphoreDesc.type=CU_EXTERNAL_SEMAPHORE_HANDLE_TYPE_D3D12_FENCE;semaphoreDesc.handle.win32.handle=fenceHandle;Cuda(Function<decltype(&cuImportExternalSemaphore)>("cuImportExternalSemaphore")(&semaphore,&semaphoreDesc),"import D3D12 fence");
    }
    void Copy(int eye,int stage,CUdeviceptr buffer,CUstream stream,bool write){
        if(eye<0||eye>1||stage<0||stage>3)throw std::runtime_error("bridge index");auto& item=imported[eye][stage];CUDA_MEMCPY2D copy{};copy.WidthInBytes=item.w*4;copy.Height=item.h;
        if(write){copy.srcMemoryType=CU_MEMORYTYPE_DEVICE;copy.srcDevice=buffer;copy.srcPitch=item.w*4;copy.dstMemoryType=CU_MEMORYTYPE_ARRAY;copy.dstArray=item.array;}
        else{copy.srcMemoryType=CU_MEMORYTYPE_ARRAY;copy.srcArray=item.array;copy.dstMemoryType=CU_MEMORYTYPE_DEVICE;copy.dstDevice=buffer;copy.dstPitch=item.w*4;}
        Cuda(Function<decltype(&cuMemcpy2DAsync)>("cuMemcpy2DAsync_v2")(&copy,stream),"GPU texture copy");
    }
};
}
extern "C" {
__declspec(dllexport) const char* OnrError(){return bridgeError.c_str();}
__declspec(dllexport) void* OnrCreate(const wchar_t* config){try{auto result=std::make_unique<Bridge>();result->Init(config);return result.release();}catch(const std::exception& e){bridgeError=e.what();return nullptr;}}
__declspec(dllexport) void OnrDestroy(void* handle){delete static_cast<Bridge*>(handle);}
__declspec(dllexport) int OnrBegin(void* handle,CUstream stream){try{auto& b=*static_cast<Bridge*>(handle);auto value=++b.bench.serial;Check(b.bench.queue->Signal(b.bench.fence.Get(),value),"producer fence");CUDA_EXTERNAL_SEMAPHORE_WAIT_PARAMS params{};params.params.fence.value=value;Cuda(Function<decltype(&cuWaitExternalSemaphoresAsync)>("cuWaitExternalSemaphoresAsync")(&b.semaphore,&params,1,stream),"CUDA wait producer");return 1;}catch(const std::exception& e){bridgeError=e.what();return 0;}}
__declspec(dllexport) int OnrRead(void* handle,int eye,CUdeviceptr color,CUdeviceptr depth,CUdeviceptr motion,CUstream stream){try{auto& b=*static_cast<Bridge*>(handle);b.Copy(eye,0,color,stream,false);b.Copy(eye,1,depth,stream,false);b.Copy(eye,2,motion,stream,false);return 1;}catch(const std::exception& e){bridgeError=e.what();return 0;}}
__declspec(dllexport) int OnrWrite(void* handle,int eye,CUdeviceptr output,CUstream stream){try{static_cast<Bridge*>(handle)->Copy(eye,3,output,stream,true);return 1;}catch(const std::exception& e){bridgeError=e.what();return 0;}}
__declspec(dllexport) int OnrEnd(void* handle,CUstream stream){try{auto& b=*static_cast<Bridge*>(handle);CUDA_EXTERNAL_SEMAPHORE_SIGNAL_PARAMS params{};params.params.fence.value=++b.bench.serial;Cuda(Function<decltype(&cuSignalExternalSemaphoresAsync)>("cuSignalExternalSemaphoresAsync")(&b.semaphore,&params,1,stream),"CUDA signal consumer");Check(b.bench.queue->Wait(b.bench.fence.Get(),b.bench.serial),"graphics wait CUDA");Check(b.bench.queue->Signal(b.bench.fence.Get(),++b.bench.serial),"consumer completion");Check(b.bench.fence->SetEventOnCompletion(b.bench.serial,b.bench.event),"completion event");if(WaitForSingleObject(b.bench.event,30000)!=WAIT_OBJECT_0)throw std::runtime_error("interop timeout");return 1;}catch(const std::exception& e){bridgeError=e.what();return 0;}}
__declspec(dllexport) int OnrSave(void* handle,int eye,const wchar_t* output){try{if(eye<0||eye>1)throw std::runtime_error("eye index");auto& b=*static_cast<Bridge*>(handle);b.bench.Save(b.eyes[eye].textures[3].Get(),output);return 1;}catch(const std::exception& e){bridgeError=e.what();return 0;}}
}
