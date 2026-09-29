#include <Windows.h>
#include <d3d12.h>
#include <dxgi1_6.h>
#include <wrl/client.h>
#include <array>
#include <chrono>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
#include "Runtime.h"
#include "BenchmarkContract.h"

using Microsoft::WRL::ComPtr;
void Check(HRESULT value,const char* operation) { if (FAILED(value)) throw std::runtime_error(std::string(operation)+" HRESULT="+std::to_string(value)); }
struct Eye { std::array<ComPtr<ID3D12Resource>,4> textures; float mx,my; };
struct Bench {
    bool sharedResources=false;
    ComPtr<ID3D12Device> device;ComPtr<ID3D12CommandQueue> queue;ComPtr<ID3D12CommandAllocator> allocator;
    ComPtr<ID3D12GraphicsCommandList> commands;ComPtr<ID3D12Fence> fence;HANDLE event=nullptr;UINT64 serial=0;
    std::vector<ComPtr<ID3D12Resource>> uploads;
    ~Bench() { if (event) CloseHandle(event); }
    void Initialize() {
        ComPtr<IDXGIFactory6> factory;Check(CreateDXGIFactory1(IID_PPV_ARGS(&factory)),"DXGI factory");
        for (UINT i=0;;++i) {
            ComPtr<IDXGIAdapter1> adapter;if (factory->EnumAdapterByGpuPreference(i,DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE,IID_PPV_ARGS(&adapter))==DXGI_ERROR_NOT_FOUND) break;
            DXGI_ADAPTER_DESC1 desc{};adapter->GetDesc1(&desc);if (desc.VendorId!=0x10de || desc.Flags&DXGI_ADAPTER_FLAG_SOFTWARE) continue;
            if (SUCCEEDED(D3D12CreateDevice(adapter.Get(),D3D_FEATURE_LEVEL_12_0,IID_PPV_ARGS(&device)))) { std::wcout<<L"GPU: "<<desc.Description<<std::endl;break; }
        }
        if (!device) throw std::runtime_error("NVIDIA D3D12 device unavailable");
        D3D12_COMMAND_QUEUE_DESC q{};q.Type=D3D12_COMMAND_LIST_TYPE_DIRECT;Check(device->CreateCommandQueue(&q,IID_PPV_ARGS(&queue)),"queue");
        Check(device->CreateCommandAllocator(q.Type,IID_PPV_ARGS(&allocator)),"allocator");
        Check(device->CreateCommandList(0,q.Type,allocator.Get(),nullptr,IID_PPV_ARGS(&commands)),"commands");
        Check(device->CreateFence(0,sharedResources?D3D12_FENCE_FLAG_SHARED:D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence)),"fence");event=CreateEventW(nullptr,FALSE,FALSE,nullptr);if (!event) throw std::runtime_error("fence event");
    }
    void Submit() {
        Check(commands->Close(),"close");ID3D12CommandList* lists[]={commands.Get()};queue->ExecuteCommandLists(1,lists);Check(queue->Signal(fence.Get(),++serial),"signal");
        if (fence->GetCompletedValue()<serial) { Check(fence->SetEventOnCompletion(serial,event),"fence event");if (WaitForSingleObject(event,30000)!=WAIT_OBJECT_0) throw std::runtime_error("GPU fence timeout"); }
    }
    void Reset() { Check(allocator->Reset(),"allocator reset");Check(commands->Reset(allocator.Get(),nullptr),"command reset"); }
    ComPtr<ID3D12Resource> Buffer(UINT64 size,D3D12_HEAP_TYPE heapType,D3D12_RESOURCE_STATES state) {
        D3D12_HEAP_PROPERTIES heap{};heap.Type=heapType;D3D12_RESOURCE_DESC d{};d.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;d.Width=size;d.Height=1;d.DepthOrArraySize=1;d.MipLevels=1;d.SampleDesc.Count=1;d.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        ComPtr<ID3D12Resource> r;Check(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&d,state,nullptr,IID_PPV_ARGS(&r)),"buffer");return r;
    }
    void Barrier(ID3D12Resource* r,D3D12_RESOURCE_STATES before,D3D12_RESOURCE_STATES after) {
        D3D12_RESOURCE_BARRIER b{};b.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;b.Transition={r,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,before,after};commands->ResourceBarrier(1,&b);
    }
    ComPtr<ID3D12Resource> Texture(UINT w,UINT h,DXGI_FORMAT format,const std::filesystem::path& raw={}) {
        D3D12_RESOURCE_DESC d{};d.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;d.Width=w;d.Height=h;d.DepthOrArraySize=1;d.MipLevels=1;d.Format=format;d.SampleDesc.Count=1;d.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        D3D12_HEAP_PROPERTIES heap{};heap.Type=D3D12_HEAP_TYPE_DEFAULT;ComPtr<ID3D12Resource> r;Check(device->CreateCommittedResource(&heap,sharedResources?D3D12_HEAP_FLAG_SHARED:D3D12_HEAP_FLAG_NONE,&d,D3D12_RESOURCE_STATE_COMMON,nullptr,IID_PPV_ARGS(&r)),"texture");r->SetName(raw.empty()?L"OpenNRBench::Output":raw.filename().c_str());
        if (!raw.empty()) {
            D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};UINT rows;UINT64 rowBytes,total;device->GetCopyableFootprints(&d,0,1,0,&footprint,&rows,&rowBytes,&total);
            if (std::filesystem::file_size(raw)!=rowBytes*rows) throw std::runtime_error("raw texture size mismatch");
            auto upload=Buffer(total,D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ);void* data;D3D12_RANGE read{0,0};Check(upload->Map(0,&read,&data),"upload map");std::ifstream file(raw,std::ios::binary);
            for (UINT y=0;y<rows;++y) file.read(static_cast<char*>(data)+footprint.Offset+y*footprint.Footprint.RowPitch,rowBytes);
            if (!file) throw std::runtime_error("raw texture read failed");upload->Unmap(0,nullptr);
            D3D12_TEXTURE_COPY_LOCATION dst{};dst.pResource=r.Get();dst.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            D3D12_TEXTURE_COPY_LOCATION src{};src.pResource=upload.Get();src.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;src.PlacedFootprint=footprint;
            Barrier(r.Get(),D3D12_RESOURCE_STATE_COMMON,D3D12_RESOURCE_STATE_COPY_DEST);commands->CopyTextureRegion(&dst,0,0,0,&src,nullptr);Barrier(r.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_COMMON);uploads.push_back(upload);
        }
        return r;
    }
    void Save(ID3D12Resource* texture,const std::filesystem::path& path) {
        Reset();auto d=texture->GetDesc();D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{};UINT rows;UINT64 rowBytes,total;device->GetCopyableFootprints(&d,0,1,0,&fp,&rows,&rowBytes,&total);auto readback=Buffer(total,D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);
        D3D12_TEXTURE_COPY_LOCATION src{};src.pResource=texture;src.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        D3D12_TEXTURE_COPY_LOCATION dst{};dst.pResource=readback.Get();dst.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;dst.PlacedFootprint=fp;
        Barrier(texture,D3D12_RESOURCE_STATE_COMMON,D3D12_RESOURCE_STATE_COPY_SOURCE);commands->CopyTextureRegion(&dst,0,0,0,&src,nullptr);Barrier(texture,D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_COMMON);Submit();
        void* data;D3D12_RANGE range{0,static_cast<SIZE_T>(total)};Check(readback->Map(0,&range,&data),"readback map");std::ofstream file(path,std::ios::binary);for (UINT y=0;y<rows;++y) file.write(static_cast<char*>(data)+fp.Offset+y*fp.Footprint.RowPitch,rowBytes);readback->Unmap(0,nullptr);
    }
};

#ifndef OPENNR_BENCH_LIBRARY
int wmain(int argc,wchar_t** argv) {
    try {
        if (argc!=2) throw std::runtime_error("Usage: teacher_bench.exe inputs.txt");
        std::ifstream config{std::filesystem::path(argv[1])};
        std::string header;
        std::getline(config, header);
        std::istringstream headerStream(header);
        std::vector<UINT> dimensions;
        UINT dimension = 0;
        while (headerStream >> dimension)
            dimensions.push_back(dimension);
        UINT colorWidth = 0, colorHeight = 0, inputWidth = 0, inputHeight = 0, outputWidth = 0, outputHeight = 0, guideWidth = 0, guideHeight = 0, count = 0;
        if (dimensions.size() == 5) {
            // Original contract: physical color, logical input, and output have
            // the same dimensions.
            colorWidth = inputWidth = outputWidth = dimensions[0];
            colorHeight = inputHeight = outputHeight = dimensions[1];
            guideWidth = dimensions[2];
            guideHeight = dimensions[3];
            count = dimensions[4];
        } else if (dimensions.size() == 7) {
            // Reduced-model shorthand: physical color and logical input/output
            // are the network dimensions, while guides retain their native
            // Feature 18 dimensions.
            colorWidth = inputWidth = dimensions[0];
            colorHeight = inputHeight = dimensions[1];
            outputWidth = dimensions[2];
            outputHeight = dimensions[3];
            guideWidth = dimensions[4];
            guideHeight = dimensions[5];
            count = dimensions[6];
        } else if (dimensions.size() == 9) {
            // Full renderer contract: the physical color texture can be a
            // reduced model surface while NGX receives a separate logical
            // input size (the Skyrim renderer supplies guide dimensions here).
            colorWidth = dimensions[0];
            colorHeight = dimensions[1];
            inputWidth = dimensions[2];
            inputHeight = dimensions[3];
            outputWidth = dimensions[4];
            outputHeight = dimensions[5];
            guideWidth = dimensions[6];
            guideHeight = dimensions[7];
            count = dimensions[8];
        } else {
            throw std::runtime_error("expected 5, 7, or 9 fields (physical color, logical input, output, guide, count)");
        }
        std::string output,dll,corePath;
        std::getline(config,output);
        std::getline(config,dll);
        std::getline(config,corePath);
        output=CheckedBenchmarkOutput(output).string();
        std::filesystem::create_directories(output);
        Bench bench;bench.Initialize();std::array<Eye,2> eyes;
        for (auto& eye:eyes) {
            for (int j=0;j<3;++j) {
                std::string path;
                std::getline(config,path);
                eye.textures[j]=bench.Texture(j==0?colorWidth:guideWidth,j==0?colorHeight:guideHeight,
                    j==0?DXGI_FORMAT_R8G8B8A8_UNORM:(j==1?DXGI_FORMAT_R32_FLOAT:DXGI_FORMAT_R16G16_FLOAT),path);
            }
            config>>eye.mx>>eye.my;config.ignore(10000,'\n');eye.textures[3]=bench.Texture(outputWidth,outputHeight,DXGI_FORMAT_R8G8B8A8_UNORM);
        }
        if (!config) throw std::runtime_error("invalid input configuration");bench.Submit();bench.uploads.clear();
        HMODULE core=LoadLibraryExW(std::filesystem::path(corePath).c_str(),nullptr,LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
        if (!core || !GetProcAddress(core,"NVSDK_NGX_D3D12_AllocateParameters")) throw std::runtime_error("Driver NGX parameter API unavailable");
        auto& runtime=NeuralRendering::Runtime::Instance();
        if (!runtime.Probe(dll) || !runtime.Initialize(bench.device.Get(),std::filesystem::path(output)/"ngx")) throw std::runtime_error(runtime.Detail());
        std::cout<<"Runtime "<<runtime.Version()<<" initialized"<<std::endl;
        D3D12_QUERY_HEAP_DESC q{};q.Type=D3D12_QUERY_HEAP_TYPE_TIMESTAMP;q.Count=4;ComPtr<ID3D12QueryHeap> queries;Check(bench.device->CreateQueryHeap(&q,IID_PPV_ARGS(&queries)),"timestamp heap");auto result=bench.Buffer(4*sizeof(UINT64),D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);UINT64 frequency;Check(bench.queue->GetTimestampFrequency(&frequency),"timestamp frequency");
        std::ofstream csv(std::filesystem::path(output)/"timings.csv");csv<<"iteration,warm,left_gpu_ms,right_gpu_ms,pair_gpu_ms,pair_wall_ms\n";NeuralRendering::Tuning tuning;
        for (UINT iteration=0;iteration<count+20;++iteration) {
            auto start=std::chrono::steady_clock::now();bench.Reset();
            for (UINT eyeIndex=0;eyeIndex<2;++eyeIndex) {
                auto& eye=eyes[eyeIndex];for (int j=0;j<4;++j) bench.Barrier(eye.textures[j].Get(),D3D12_RESOURCE_STATE_COMMON,j==3?D3D12_RESOURCE_STATE_UNORDERED_ACCESS:D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
                bench.commands->EndQuery(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,eyeIndex*2);
                if (!runtime.Execute(bench.commands.Get(),eyeIndex,eye.textures[0].Get(),eye.textures[1].Get(),eye.textures[2].Get(),eye.textures[3].Get(),MakeBenchmarkGuide(inputWidth,inputHeight,outputWidth,outputHeight,guideWidth,guideHeight,eye.mx,eye.my),tuning,iteration==0)) throw std::runtime_error(runtime.Detail());
                bench.commands->EndQuery(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,eyeIndex*2+1);
                for (int j=0;j<4;++j) bench.Barrier(eye.textures[j].Get(),j==3?D3D12_RESOURCE_STATE_UNORDERED_ACCESS:D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_COMMON);
            }
            bench.commands->ResolveQueryData(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0,4,result.Get(),0);bench.Submit();double wall=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();
            UINT64* t;D3D12_RANGE range{0,4*sizeof(UINT64)};Check(result->Map(0,&range,reinterpret_cast<void**>(&t)),"timestamp map");double left=1000.*(t[1]-t[0])/frequency,right=1000.*(t[3]-t[2])/frequency,pair=1000.*(t[3]-t[0])/frequency;result->Unmap(0,nullptr);
            csv<<iteration<<','<<(iteration>=20)<<','<<left<<','<<right<<','<<pair<<','<<wall<<'\n';csv.flush();if (iteration%10==0) std::cout<<"iteration "<<iteration<<" pair GPU "<<pair<<" wall "<<wall<<std::endl;
        }
        for (UINT i=0;i<2;++i) bench.Save(eyes[i].textures[3].Get(),std::filesystem::path(output)/("teacher_eye"+std::to_string(i)+".rgba"));
        std::ofstream meta(std::filesystem::path(output)/"runtime.txt");meta<<runtime.Version()<<"\n"<<runtime.SuccessfulFrames()<<"\n"<<frequency<<"\n";runtime.Shutdown();return 0;
    } catch (const std::exception& e) { std::cerr<<"FAILED: "<<e.what()<<std::endl;return 1; }
}
#else
#include "interop_exports.h"
#endif
