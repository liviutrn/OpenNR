#define NOMINMAX
#include <d3d11.h>
#include <d3dcompiler.h>
#include <wrl/client.h>
#include <algorithm>
#include <array>
#include <bit>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <vector>
using Microsoft::WRL::ComPtr;
void Check(HRESULT hr) { if(FAILED(hr)) throw std::runtime_error("D3D11 operation failed"); }
struct Texture { ComPtr<ID3D11Texture2D> resource;ComPtr<ID3D11ShaderResourceView> srv;ComPtr<ID3D11UnorderedAccessView> uav; };
Texture Make(ID3D11Device* device,UINT w,UINT h,DXGI_FORMAT format) {
    Texture t;D3D11_TEXTURE2D_DESC d{};d.Width=w;d.Height=h;d.ArraySize=d.MipLevels=1;
    d.Format=format;d.SampleDesc.Count=1;d.BindFlags=D3D11_BIND_SHADER_RESOURCE|D3D11_BIND_UNORDERED_ACCESS;
    Check(device->CreateTexture2D(&d,nullptr,t.resource.GetAddressOf()));
    Check(device->CreateShaderResourceView(t.resource.Get(),nullptr,t.srv.GetAddressOf()));
    Check(device->CreateUnorderedAccessView(t.resource.Get(),nullptr,t.uav.GetAddressOf()));return t;
}
ComPtr<ID3D11ComputeShader> Compile(ID3D11Device* device,const wchar_t* path) {
    ComPtr<ID3DBlob> blob,error;auto hr=D3DCompileFromFile(path,nullptr,D3D_COMPILE_STANDARD_FILE_INCLUDE,"main","cs_5_0",D3DCOMPILE_WARNINGS_ARE_ERRORS,0,blob.GetAddressOf(),error.GetAddressOf());
    if(FAILED(hr)&&error) std::cerr<<static_cast<const char*>(error->GetBufferPointer());Check(hr);
    ComPtr<ID3D11ComputeShader> s;Check(device->CreateComputeShader(blob->GetBufferPointer(),blob->GetBufferSize(),nullptr,s.GetAddressOf()));return s;
}
ComPtr<ID3D11Buffer> Buffer(ID3D11Device* device,UINT bytes) {
    D3D11_BUFFER_DESC d{};d.ByteWidth=bytes;d.BindFlags=D3D11_BIND_CONSTANT_BUFFER;
    ComPtr<ID3D11Buffer> b;Check(device->CreateBuffer(&d,nullptr,b.GetAddressOf()));return b;
}
void Dispatch(ID3D11DeviceContext* context,ID3D11ComputeShader* shader,ID3D11Buffer* cb,
    const std::array<ID3D11ShaderResourceView*,6>& sources,const std::array<ID3D11UnorderedAccessView*,3>& targets,UINT w,UINT h) {
    context->CSSetShader(shader,nullptr,0);context->CSSetConstantBuffers(0,1,&cb);
    context->CSSetShaderResources(0,6,sources.data());context->CSSetUnorderedAccessViews(0,3,targets.data(),nullptr);
    context->Dispatch((w+7)/8,(h+7)/8,1);
    ID3D11ShaderResourceView* ns[6]{};ID3D11UnorderedAccessView* nt[3]{};
    context->CSSetShaderResources(0,6,ns);context->CSSetUnorderedAccessViews(0,3,nt,nullptr);
}
std::vector<std::uint8_t> Read(ID3D11Device* device,ID3D11DeviceContext* context,const Texture& texture,UINT components) {
    D3D11_TEXTURE2D_DESC d{};texture.resource->GetDesc(&d);d.BindFlags=0;d.Usage=D3D11_USAGE_STAGING;d.CPUAccessFlags=D3D11_CPU_ACCESS_READ;
    ComPtr<ID3D11Texture2D> staging;Check(device->CreateTexture2D(&d,nullptr,staging.GetAddressOf()));context->CopyResource(staging.Get(),texture.resource.Get());
    D3D11_MAPPED_SUBRESOURCE map{};Check(context->Map(staging.Get(),0,D3D11_MAP_READ,0,&map));
    const std::size_t row=static_cast<std::size_t>(d.Width)*components*sizeof(float);std::vector<std::uint8_t> bytes(row*d.Height);
    for(UINT y=0;y<d.Height;++y) std::memcpy(bytes.data()+y*row,static_cast<const std::uint8_t*>(map.pData)+y*map.RowPitch,row);
    context->Unmap(staging.Get(),0);return bytes;
}
struct Constants {
    std::array<UINT,4> current{},previous{},layout{};
    std::array<float,4> leftOrigin{},rightOrigin{},motionScale{};
    std::array<UINT,4> flags{};
    std::array<float,4> modelPitch{},leftPhase{},rightPhase{};
};
static_assert(sizeof(Constants)==160);
int main() {
    ComPtr<ID3D11Device> device;ComPtr<ID3D11DeviceContext> context;
    const D3D_FEATURE_LEVEL wanted=D3D_FEATURE_LEVEL_11_0;D3D_FEATURE_LEVEL actual{};
    Check(D3D11CreateDevice(nullptr,D3D_DRIVER_TYPE_WARP,nullptr,0,&wanted,1,D3D11_SDK_VERSION,device.GetAddressOf(),&actual,context.GetAddressOf()));
    auto fused=Compile(device.Get(),L"runtime/open-shaders/features/Upscaling/Shaders/Upscaling/NeuralRendering/LadderAtlasGuidesCS.hlsl");
    auto guides=Compile(device.Get(),L"scripts/v10/reference-guides.hlsl"),color=Compile(device.Get(),L"scripts/v10/reference-color.hlsl");
    auto cb=Buffer(device.Get(),160),colorCB=Buffer(device.Get(),32);
    constexpr UINT span=64;
    auto leftColor=Make(device.Get(),span,span,DXGI_FORMAT_R32G32B32A32_FLOAT),rightColor=Make(device.Get(),span,span,DXGI_FORMAT_R32G32B32A32_FLOAT);
    auto leftMotion=Make(device.Get(),span,span,DXGI_FORMAT_R32G32_FLOAT),rightMotion=Make(device.Get(),span,span,DXGI_FORMAT_R32G32_FLOAT);
    auto leftDepth=Make(device.Get(),span,span,DXGI_FORMAT_R32_FLOAT),rightDepth=Make(device.Get(),span,span,DXGI_FORMAT_R32_FLOAT);
    for(UINT eye=0;eye<2;++eye) {
        std::vector<std::array<float,4>> colors(span*span);std::vector<std::array<float,2>> motion(span*span);std::vector<float> depth(span*span);
        for(UINT y=0;y<span;++y) for(UINT x=0;x<span;++x) {
            const auto index=y*span+x;
            colors[index]={float(x+eye*1000),float(y),float(x+y),1.f};depth[index]=float(x+y+eye*100+1);
            motion[index]={float(int(x%7)-3)/32.f,float(int(y%5)-2)/32.f};
            if(x%11==0) motion[index][0]=std::bit_cast<float>(UINT{0x00800000});
            if(x%13==0) motion[index][1]=std::bit_cast<float>(UINT{0x7fc12345});
        }
        context->UpdateSubresource((eye?rightColor:leftColor).resource.Get(),0,nullptr,colors.data(),span*16,0);
        context->UpdateSubresource((eye?rightMotion:leftMotion).resource.Get(),0,nullptr,motion.data(),span*8,0);
        context->UpdateSubresource((eye?rightDepth:leftDepth).resource.Get(),0,nullptr,depth.data(),span*4,0);
    }
    UINT cases=0;
    for(UINT w:{17u,31u}) for(UINT h:{11u,19u}) for(UINT guard:{1u,8u,9u}) for(UINT ratio:{1u,2u}) for(UINT change=0;change<4;++change) {
        const UINT gw=w/ratio,gh=h/ratio,gg=std::max(1u,guard/ratio);
        auto refColor=Make(device.Get(),w*2+guard+3,h+2,DXGI_FORMAT_R32G32B32A32_FLOAT),outColor=Make(device.Get(),w*2+guard+3,h+2,DXGI_FORMAT_R32G32B32A32_FLOAT);
        auto refMotion=Make(device.Get(),gw*2+gg+3,gh+2,DXGI_FORMAT_R32G32_FLOAT),outMotion=Make(device.Get(),gw*2+gg+3,gh+2,DXGI_FORMAT_R32G32_FLOAT);
        auto refDepth=Make(device.Get(),gw*2+gg+3,gh+2,DXGI_FORMAT_R32_FLOAT),outDepth=Make(device.Get(),gw*2+gg+3,gh+2,DXGI_FORMAT_R32_FLOAT);
        const float clear[4]{-999,-999,-999,-999};
        for(auto* t:{&refColor,&outColor,&refMotion,&outMotion,&refDepth,&outDepth}) context->ClearUnorderedAccessViewFloat(t->uav.Get(),clear);
        Constants c{};c.current={w,h,gw,gh};c.previous={w,h,w,h};c.layout={w,h,guard,guard};
        c.modelPitch={1,1,1,1};c.motionScale={float(w),float(h),float(w),float(h)};c.flags={1,gg,h,0};
        if(change==1) { c.leftOrigin={11,7,8,6};c.rightOrigin={4,2,9,6};c.leftPhase={.25f,-.25f,-.25f,.25f}; }
        if(change==2) { c.previous={w+6,h+4,w+6,h+4};c.layout[3]=guard+2; }
        if(change==3) c.flags[0]=0;
        context->UpdateSubresource(cb.Get(),0,nullptr,&c,0,0);
        const std::array<UINT,8> pc{w,h,guard,0,0,w*2+guard,h,0};context->UpdateSubresource(colorCB.Get(),0,nullptr,pc.data(),0,0);
        Dispatch(context.Get(),color.Get(),colorCB.Get(),{leftColor.srv.Get(),rightColor.srv.Get(),nullptr,nullptr,nullptr,nullptr},{refColor.uav.Get(),nullptr,nullptr},w*2+guard,h);
        const std::array<ID3D11ShaderResourceView*,6> sources{leftMotion.srv.Get(),rightMotion.srv.Get(),leftDepth.srv.Get(),rightDepth.srv.Get(),leftColor.srv.Get(),rightColor.srv.Get()};
        Dispatch(context.Get(),guides.Get(),cb.Get(),sources,{refMotion.uav.Get(),refDepth.uav.Get(),nullptr},gw*2+gg,gh);
        Dispatch(context.Get(),fused.Get(),cb.Get(),sources,{outMotion.uav.Get(),outDepth.uav.Get(),outColor.uav.Get()},std::max(w*2+guard,gw*2+gg),std::max(h,gh));
        if(Read(device.Get(),context.Get(),refColor,4)!=Read(device.Get(),context.Get(),outColor,4) ||
           Read(device.Get(),context.Get(),refMotion,2)!=Read(device.Get(),context.Get(),outMotion,2) ||
           Read(device.Get(),context.Get(),refDepth,1)!=Read(device.Get(),context.Get(),outDepth,1)) throw std::runtime_error("Fused atlas differs from r7 shaders");
        ++cases;
    }
    std::cout<<"Fused atlas matched r7 color/depth/motion bit-for-bit in "<<cases<<" cases, including guards, unequal extents, gaze, crop changes, invalid guides and padding.\n";
}
