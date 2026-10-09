#define NOMINMAX
#include <d3d11.h>
#include <d3dcompiler.h>
#include <d3d11shader.h>
#include <wrl/client.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <iostream>
#include <stdexcept>
#include <vector>
#include "../../runtime/open-shaders/src/Features/Upscaling/NeuralRendering/FeatherGeometry.h"
using Microsoft::WRL::ComPtr;
using namespace NeuralRendering::FeatherGeometry;
void Check(HRESULT r) { if(FAILED(r)) throw std::runtime_error("WARP API failure"); }
void Require(bool v,const char* text) { if(!v) throw std::runtime_error(text); }
struct Texture { ComPtr<ID3D11Texture2D> texture;ComPtr<ID3D11ShaderResourceView> srv;ComPtr<ID3D11UnorderedAccessView> uav;UINT w,h,channels; };
Texture Make(ID3D11Device* device,UINT w,UINT h,UINT channels=4) {
    Texture t;t.w=w;t.h=h;t.channels=channels;D3D11_TEXTURE2D_DESC d{};
    d.Width=w;d.Height=h;d.MipLevels=1;d.ArraySize=1;d.SampleDesc.Count=1;
    d.Format=channels==4?DXGI_FORMAT_R32G32B32A32_FLOAT:channels==2?DXGI_FORMAT_R32G32_FLOAT:DXGI_FORMAT_R32_FLOAT;
    d.BindFlags=D3D11_BIND_SHADER_RESOURCE|D3D11_BIND_UNORDERED_ACCESS;
    Check(device->CreateTexture2D(&d,nullptr,t.texture.GetAddressOf()));
    Check(device->CreateShaderResourceView(t.texture.Get(),nullptr,t.srv.GetAddressOf()));
    Check(device->CreateUnorderedAccessView(t.texture.Get(),nullptr,t.uav.GetAddressOf()));return t;
}
void Upload(ID3D11DeviceContext* c,const Texture& t,const std::vector<float>& values) {c->UpdateSubresource(t.texture.Get(),0,nullptr,values.data(),t.w*t.channels*4,0);}
std::vector<float> Read(ID3D11Device* d,ID3D11DeviceContext* c,const Texture& t) {
    D3D11_TEXTURE2D_DESC desc{};t.texture->GetDesc(&desc);desc.Usage=D3D11_USAGE_STAGING;desc.BindFlags=0;desc.CPUAccessFlags=D3D11_CPU_ACCESS_READ;
    ComPtr<ID3D11Texture2D> copy;Check(d->CreateTexture2D(&desc,nullptr,copy.GetAddressOf()));c->CopyResource(copy.Get(),t.texture.Get());
    D3D11_MAPPED_SUBRESOURCE mapped{};Check(c->Map(copy.Get(),0,D3D11_MAP_READ,0,&mapped));
    std::vector<float> result(t.w*t.h*t.channels);
    for(UINT y=0;y<t.h;++y) std::copy_n(reinterpret_cast<const float*>(static_cast<const char*>(mapped.pData)+y*mapped.RowPitch),t.w*t.channels,result.data()+y*t.w*t.channels);
    c->Unmap(copy.Get(),0);return result;
}
ComPtr<ID3D11ComputeShader> Compile(ID3D11Device* device,const wchar_t* file,const char* cb,UINT size) {
    ComPtr<ID3DBlob> blob,error;auto r=D3DCompileFromFile(file,nullptr,D3D_COMPILE_STANDARD_FILE_INCLUDE,"main","cs_5_0",D3DCOMPILE_WARNINGS_ARE_ERRORS,0,blob.GetAddressOf(),error.GetAddressOf());
    if(FAILED(r)&&error) std::cerr<<static_cast<const char*>(error->GetBufferPointer());Check(r);
    ComPtr<ID3D11ShaderReflection> reflection;Check(D3DReflect(blob->GetBufferPointer(),blob->GetBufferSize(),IID_PPV_ARGS(reflection.GetAddressOf())));
    D3D11_SHADER_BUFFER_DESC desc{};Check(reflection->GetConstantBufferByName(cb)->GetDesc(&desc));Require(desc.Size==size,"Shader/C++ constant size mismatch");
    ComPtr<ID3D11ComputeShader> shader;Check(device->CreateComputeShader(blob->GetBufferPointer(),blob->GetBufferSize(),nullptr,shader.GetAddressOf()));return shader;
}
ComPtr<ID3D11Buffer> Buffer(ID3D11Device* d,UINT size) {D3D11_BUFFER_DESC desc{};desc.ByteWidth=size;desc.BindFlags=D3D11_BIND_CONSTANT_BUFFER;ComPtr<ID3D11Buffer> b;Check(d->CreateBuffer(&desc,nullptr,b.GetAddressOf()));return b;}
ComPtr<ID3D11ShaderResourceView> LUT(ID3D11Device* d,float compression,float power) {
    std::array<float,4097> values{};Axis a;a.compression=compression;a.power=power;const float divisor=1+(compression-1)/(power+1);
    for(unsigned i=0;i<values.size();++i) values[i]=ExteriorToModel(float(i)/4096,1,a)*divisor;
    D3D11_TEXTURE1D_DESC desc{};desc.Width=4097;desc.MipLevels=1;desc.ArraySize=1;desc.Format=DXGI_FORMAT_R32_FLOAT;desc.Usage=D3D11_USAGE_IMMUTABLE;desc.BindFlags=D3D11_BIND_SHADER_RESOURCE;
    D3D11_SUBRESOURCE_DATA data{values.data(),0,0};ComPtr<ID3D11Texture1D> texture;ComPtr<ID3D11ShaderResourceView> view;
    Check(d->CreateTexture1D(&desc,&data,texture.GetAddressOf()));Check(d->CreateShaderResourceView(texture.Get(),nullptr,view.GetAddressOf()));return view;
}
void Unbind(ID3D11DeviceContext* c) {ID3D11ShaderResourceView* s[5]{};ID3D11UnorderedAccessView* u[2]{};c->CSSetShaderResources(0,5,s);c->CSSetUnorderedAccessViews(0,2,u,nullptr);}
struct ModelConstants {std::array<UINT,4> size;Mapping mapping;std::array<float,4> options;};
struct GuideConstants {std::array<UINT,4> current,previous,layout;std::array<float,4> left,right,scale;std::array<UINT,4> flags;std::array<float,4> pitch,leftPhase,rightPhase;std::array<Mapping,4> mappings;};
static_assert(sizeof(ModelConstants)==96);static_assert(sizeof(GuideConstants)==416);
float Smooth(float a,float b,float value) {float t=std::clamp((value-a)/(b-a),0.f,1.f);return t*t*(3-2*t);}
int main() {
    ComPtr<ID3D11Device> d;ComPtr<ID3D11DeviceContext> c;D3D_FEATURE_LEVEL actual{};const D3D_FEATURE_LEVEL level=D3D_FEATURE_LEVEL_11_0;
    Check(D3D11CreateDevice(nullptr,D3D_DRIVER_TYPE_WARP,nullptr,0,&level,1,D3D11_SDK_VERSION,d.GetAddressOf(),&actual,c.GetAddressOf()));
    auto modelShader=Compile(d.Get(),L"runtime/open-shaders/features/Upscaling/Shaders/Upscaling/NeuralRendering/FeatherModelCS.hlsl","FeatherModel",96);
    auto guidesShader=Compile(d.Get(),L"runtime/open-shaders/features/Upscaling/Shaders/Upscaling/NeuralRendering/FeatherGuidesCS.hlsl","FeatherGuides",416);
    D3D11_SAMPLER_DESC sd{};sd.Filter=D3D11_FILTER_MIN_MAG_MIP_LINEAR;sd.AddressU=sd.AddressV=sd.AddressW=D3D11_TEXTURE_ADDRESS_CLAMP;sd.MaxLOD=D3D11_FLOAT32_MAX;
    ComPtr<ID3D11SamplerState> sampler;Check(d->CreateSamplerState(&sd,sampler.GetAddressOf()));ID3D11SamplerState* sp=sampler.Get();c->CSSetSamplers(0,1,&sp);
    auto mb=Buffer(d.Get(),96),gb=Buffer(d.Get(),416);unsigned cases=0;
    for(float compression:{1.f,3.f,10.f,20.f}) for(float power:{1.f,2.f,4.f}) for(float resolution:{100.f,85.f,70.f}) {
        Mapping map{MakeAxis(12,52,64,17,100/resolution,compression,power),MakeAxis(10,38,48,31,100/resolution,compression,power)};
        const UINT mw=static_cast<UINT>(map.x.packedExtent),mh=static_cast<UINT>(map.y.packedExtent);
        auto original=Make(d.Get(),64,48),proxy=Make(d.Get(),mw,mh),nr=Make(d.Get(),mw,mh),out=Make(d.Get(),64,48);auto lut=LUT(d.Get(),compression,power);
        std::vector<float> source(64*48*4);
        for(UINT y=0;y<48;++y) for(UINT x=0;x<64;++x) {const UINT i=(y*64+x)*4;source[i]=.1f+.002f*float(x);source[i+1]=.2f+.001f*float(y);source[i+2]=(x+y)%2?.3f:.15f;source[i+3]=.37f;}
        Upload(c.Get(),original,source);
        ModelConstants mc{{mw,mh,64,48},map,{0,1,.25f,0}};c->UpdateSubresource(mb.Get(),0,nullptr,&mc,0,0);ID3D11Buffer* cb=mb.Get();c->CSSetConstantBuffers(0,1,&cb);
        ID3D11ShaderResourceView* inputs[]{original.srv.Get(),nullptr,nullptr,lut.Get()};c->CSSetShaderResources(0,4,inputs);
        ID3D11UnorderedAccessView* target=proxy.uav.Get();c->CSSetUnorderedAccessViews(0,1,&target,nullptr);c->CSSetShader(modelShader.Get(),nullptr,0);c->Dispatch((mw+7)/8,(mh+7)/8,1);Unbind(c.Get());
        auto packed=Read(d.Get(),c.Get(),proxy);
        for(float v:packed) Require(std::isfinite(v),"Nonfinite compressed pixel");
        if(resolution==100) for(UINT y=0;y<mh;++y) for(UINT x=0;x<mw;++x) {
            const float px=ToPhysical(float(x)+.5f,map.x),py=ToPhysical(float(y)+.5f,map.y);
            if(px>map.x.begin+1&&px<map.x.end-1&&py>map.y.begin+1&&py<map.y.end-1) {
                const UINT src=(static_cast<UINT>(py)*64+static_cast<UINT>(px))*4,dst=(y*mw+x)*4;
                for(UINT ch=0;ch<4;++ch) Require(std::abs(packed[dst+ch]-source[src+ch])<1e-5f,"Full-quality centre changed");
            }
        }
        for(float delta:{0.f,.03f,-.03f}) for(float strength:{0.f,1.f,2.f}) {
            auto rendered=packed;for(UINT i=0;i<rendered.size();++i) if(i%4!=3) rendered[i]+=delta;Upload(c.Get(),nr,rendered);
            mc.size={64,48,mw,mh};const float calibration=resolution==85?.84f:resolution==70?.72f:1.f;mc.options={calibration,strength,.25f,0};c->UpdateSubresource(mb.Get(),0,nullptr,&mc,0,0);
            ID3D11ShaderResourceView* s[]{proxy.srv.Get(),nr.srv.Get(),original.srv.Get(),lut.Get()};c->CSSetShaderResources(0,4,s);target=out.uav.Get();c->CSSetUnorderedAccessViews(0,1,&target,nullptr);c->Dispatch(8,6,1);Unbind(c.Get());auto result=Read(d.Get(),c.Get(),out);
            for(UINT y=0;y<48;++y) for(UINT x=0;x<64;++x) {
                const float px=float(x)+.5f,py=float(y)+.5f;
                const float exterior=std::clamp(std::max({(map.x.begin-px)/std::max(map.x.begin,1e-6f),(px-map.x.end)/std::max(64-map.x.end,1e-6f),(map.y.begin-py)/std::max(map.y.begin,1e-6f),(py-map.y.end)/std::max(48-map.y.end,1e-6f)}),0.f,1.f);
                const float weight=(1+(strength-1)*Smooth(0,.05f,exterior))*(1-Smooth(.75f,1,exterior));const UINT i=(y*64+x)*4;
                for(UINT ch=0;ch<3;++ch) Require(std::abs(result[i+ch]-source[i+ch]-delta*weight*calibration)<2e-5f,"Residual, darkening or exterior fade wrong");
                Require(result[i+3]==source[i+3],"Alpha changed");
            }++cases;
        }
        // Different previous eye origins, crop extent and model tier; preserve stereo offset.
        Mapping prev{MakeAxis(8,40,52,20,100/70.f,compression,power),MakeAxis(7,31,40,29,100/70.f,compression,power)};
        auto leftMV=Make(d.Get(),32,24,2),rightMV=Make(d.Get(),32,24,2),leftDepth=Make(d.Get(),32,24,1),rightDepth=Make(d.Get(),32,24,1),motion=Make(d.Get(),68,24,2),depth=Make(d.Get(),68,24,1);
        std::vector<float> mv(32*24*2),z(32*24);for(UINT i=0;i<32*24;++i){mv[i*2]=.002f;mv[i*2+1]=-.001f;z[i]=float(i)*.0001f;}
        Upload(c.Get(),leftMV,mv);Upload(c.Get(),rightMV,mv);Upload(c.Get(),leftDepth,z);Upload(c.Get(),rightDepth,z);
        GuideConstants gc{};const UINT gw=std::min(32u,mw),gh=std::min(24u,mh);gc.current={mw,mh,gw,gh};gc.pitch={32,24,0,0};gc.previous={static_cast<UINT>(prev.x.packedExtent),static_cast<UINT>(prev.y.packedExtent),52,40};gc.layout={64,48,4,6};gc.left={17,31,20,29};gc.right={2017,31,2020,29};gc.scale={1000,1000,float(mw)/float(gw),float(mh)/float(gh)};gc.flags={1,4,64,0};gc.mappings={map,map,prev,prev};
        for(UINT valid:{0u,1u}) {
            gc.flags[0]=valid;c->UpdateSubresource(gb.Get(),0,nullptr,&gc,0,0);cb=gb.Get();c->CSSetConstantBuffers(0,1,&cb);
            ID3D11ShaderResourceView* s[]{leftMV.srv.Get(),rightMV.srv.Get(),leftDepth.srv.Get(),rightDepth.srv.Get(),lut.Get()};c->CSSetShaderResources(0,5,s);ID3D11UnorderedAccessView* u[]{motion.uav.Get(),depth.uav.Get()};c->CSSetUnorderedAccessViews(0,2,u,nullptr);c->CSSetShader(guidesShader.Get(),nullptr,0);c->Dispatch(9,3,1);Unbind(c.Get());auto vectors=Read(d.Get(),c.Get(),motion),depths=Read(d.Get(),c.Get(),depth);
            for(UINT eye=0;eye<2;++eye) for(UINT y=0;y<gh;++y) for(UINT x=0;x<gw;++x) {
                const float cx=(float(x)+.5f)*float(mw)/float(gw),cy=(float(y)+.5f)*float(mh)/float(gh),px=ToPhysical(cx,map.x),py=ToPhysical(cy,map.y);
                const float ppx=px-3+2,ppy=py+2-1,pmx=ToModel(ppx,prev.x),pmy=ToModel(ppy,prev.y);
                const bool ok=valid&&ppx>=0&&ppx<=52&&ppy>=0&&ppy<=40&&pmx>=.499f&&pmx<=float(gc.previous[0])-.499f&&pmy>=.499f&&pmy<=float(gc.previous[1])-.499f;
                const UINT index=y*68+x+eye*(gw+4);const float ex=ok?(pmx-cx+(eye?float(gc.previous[0]+6)-float(mw+4):0))/gc.scale[2]:0,ey=ok?(pmy-cy)/gc.scale[3]:128/gc.scale[3];
                Require(std::abs(vectors[index*2]-ex)<.002f&&std::abs(vectors[index*2+1]-ey)<.002f,"Warped motion/rejection or stereo origin wrong");
                const UINT dx=static_cast<UINT>(std::clamp(px*.5f,0.f,31.f)),dy=static_cast<UINT>(std::clamp(py*.5f,0.f,23.f));
                Require(std::abs(depths[index]-z[dy*32+dx])<1e-6f,"Depth not sampled from physical position");
            }++cases;
        }
    }
    std::cout<<cases<<" WARP sampling/residual/motion cases; centre identity, alpha, fades, previous geometry and stereo offset verified\n";
}
