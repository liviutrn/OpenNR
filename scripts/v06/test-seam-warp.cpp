#define NOMINMAX
#include <d3d11.h>
#include <d3dcompiler.h>
#include <wrl/client.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <vector>

using Microsoft::WRL::ComPtr;
void Check(HRESULT result) { if (FAILED(result)) throw std::runtime_error("D3D11 WARP operation failed"); }
struct MapConstants
{
    std::array<std::uint32_t,2> size{128,96}, origin{64,48};
    std::array<float,2> radii{64,48}, inset{};
    float stops=.5f, offset=.08f, sampleWidth=16;
    std::uint32_t oval=0;
    float smoothing=.35f;
    std::uint32_t mode=2;
    float focus=.5f,padding=0;
};
struct ApplyConstants
{
    std::array<std::uint32_t,2> origin{}, extent{256,192}, cropOrigin{64,48}, cropSize{128,96};
    std::array<float,2> radii{64,48}, inset{};
    float width=32,brightness=1,color=1,curve=1;
    float dither=0,ramp=4,sampleInset=0;
    std::uint32_t oval=0;
    float stops=.5f,offset=.08f,edge=0;
    std::uint32_t mode=2;
    float contrast=1,nonlinear=1,plateau=.35f,black=0;
    std::array<std::uint32_t,2> innerOrigin{96,72},innerSize{64,48};
    std::uint32_t top=256*72,side=(256-64)*48,total=256*192-64*48,padding=0;
    float contrastReach=1;
    std::array<float,3> seamPadding{};
};
static_assert(sizeof(MapConstants)==64 && sizeof(ApplyConstants)==160);

struct Texture
{
    ComPtr<ID3D11Texture2D> texture;
    ComPtr<ID3D11ShaderResourceView> srv;
    ComPtr<ID3D11UnorderedAccessView> uav;
};
Texture MakeTexture(ID3D11Device* device,UINT width,UINT height,UINT layers=1)
{
    Texture result;
    D3D11_TEXTURE2D_DESC desc{};
    desc.Width=width;desc.Height=height;desc.ArraySize=layers;desc.MipLevels=1;
    desc.Format=DXGI_FORMAT_R32G32B32A32_FLOAT;desc.SampleDesc.Count=1;
    desc.BindFlags=D3D11_BIND_SHADER_RESOURCE|D3D11_BIND_UNORDERED_ACCESS;
    Check(device->CreateTexture2D(&desc,nullptr,result.texture.GetAddressOf()));
    Check(device->CreateShaderResourceView(result.texture.Get(),nullptr,result.srv.GetAddressOf()));
    Check(device->CreateUnorderedAccessView(result.texture.Get(),nullptr,result.uav.GetAddressOf()));
    return result;
}
ComPtr<ID3D11ComputeShader> Compile(ID3D11Device* device,const wchar_t* path)
{
    ComPtr<ID3DBlob> blob,error;
    HRESULT result=D3DCompileFromFile(path,nullptr,D3D_COMPILE_STANDARD_FILE_INCLUDE,"main","cs_5_0",D3DCOMPILE_WARNINGS_ARE_ERRORS,0,blob.GetAddressOf(),error.GetAddressOf());
    if (FAILED(result) && error) std::cerr << static_cast<const char*>(error->GetBufferPointer());
    Check(result);
    ComPtr<ID3D11ComputeShader> shader;
    Check(device->CreateComputeShader(blob->GetBufferPointer(),blob->GetBufferSize(),nullptr,shader.GetAddressOf()));
    return shader;
}
ComPtr<ID3D11Buffer> MakeBuffer(ID3D11Device* device,UINT size)
{
    D3D11_BUFFER_DESC desc{};desc.ByteWidth=size;desc.BindFlags=D3D11_BIND_CONSTANT_BUFFER;
    ComPtr<ID3D11Buffer> result;Check(device->CreateBuffer(&desc,nullptr,result.GetAddressOf()));return result;
}
void Unbind(ID3D11DeviceContext* context)
{
    ID3D11ShaderResourceView* sources[2]{};ID3D11UnorderedAccessView* target=nullptr;
    context->CSSetShaderResources(0,2,sources);context->CSSetUnorderedAccessViews(0,1,&target,nullptr);
}
int main()
{
    ComPtr<ID3D11Device> device;ComPtr<ID3D11DeviceContext> context;
    const D3D_FEATURE_LEVEL requested=D3D_FEATURE_LEVEL_11_0;D3D_FEATURE_LEVEL actual{};
    Check(D3D11CreateDevice(nullptr,D3D_DRIVER_TYPE_WARP,nullptr,0,&requested,1,D3D11_SDK_VERSION,device.GetAddressOf(),&actual,context.GetAddressOf()));
    auto map=Compile(device.Get(),L"scratch-shaders/OutsideSeamMapCS.hlsl");
    auto smooth=Compile(device.Get(),L"scratch-shaders/OutsideSeamSmoothCS.hlsl");
    auto apply=Compile(device.Get(),L"scratch-shaders/OutsideSeamApplyCS.hlsl");
    auto original=MakeTexture(device.Get(),128,96),neural=MakeTexture(device.Get(),128,96);
    auto coefficients=MakeTexture(device.Get(),16,16,4),filtered=MakeTexture(device.Get(),16,16,4);
    auto destination=MakeTexture(device.Get(),256,192);
    auto mapCB=MakeBuffer(device.Get(),static_cast<UINT>(sizeof(MapConstants))),applyCB=MakeBuffer(device.Get(),static_cast<UINT>(sizeof(ApplyConstants)));
    D3D11_SAMPLER_DESC samplerDesc{};samplerDesc.Filter=D3D11_FILTER_MIN_MAG_MIP_LINEAR;
    samplerDesc.AddressU=samplerDesc.AddressV=samplerDesc.AddressW=D3D11_TEXTURE_ADDRESS_CLAMP;samplerDesc.MaxLOD=D3D11_FLOAT32_MAX;
    ComPtr<ID3D11SamplerState> sampler;Check(device->CreateSamplerState(&samplerDesc,sampler.GetAddressOf()));
    D3D11_TEXTURE2D_DESC stagingDesc{};destination.texture->GetDesc(&stagingDesc);
    stagingDesc.BindFlags=0;stagingDesc.Usage=D3D11_USAGE_STAGING;stagingDesc.CPUAccessFlags=D3D11_CPU_ACCESS_READ;
    ComPtr<ID3D11Texture2D> staging;Check(device->CreateTexture2D(&stagingDesc,nullptr,staging.GetAddressOf()));
    unsigned cases=0;
    for (bool oval : {false,true}) {
        for (unsigned fixture=0;fixture<6;++fixture) {
            const std::array<float,4> base=fixture==1||fixture==2 ? std::array<float,4>{0,0,0,.37f} : std::array<float,4>{.1f,.2f,.3f,.37f};
            const std::array<float,3> delta=fixture==3 ? std::array<float,3>{0,0,0} : fixture==0 ? std::array<float,3>{.04f,.02f,-.01f} : std::array<float,3>{.04f,.04f,.04f};
            std::vector<std::array<float,4>> crop(128*96,base),nr=crop,frame(256*192,base);
            if(fixture>=4) {
                for(unsigned y=0;y<192;++y)for(unsigned x=0;x<256;++x)
                    frame[y*256+x]={.08f+.5f*float(x%4)/3,.08f+.5f*float(y%4)/3,.1f+.4f*float((x+y)%4)/3,.37f};
                for(unsigned y=0;y<96;++y)for(unsigned x=0;x<128;++x)crop[y*128+x]=frame[(y+48)*256+x+64];
                nr=crop;
                for(auto& pixel:nr) {
                    const float luma=pixel[0]*.2126f+pixel[1]*.7152f+pixel[2]*.0722f;
                    pixel[0]=1.2f*pixel[0]+.015f+(fixture==5?.04f*luma*luma:0);
                    pixel[1]=.9f*pixel[1]-.01f-(fixture==5?.03f*luma*luma:0);
                    pixel[2]=1.1f*pixel[2]+.005f+(fixture==5?.02f*luma*luma:0);
                }
            } else for(auto& pixel:nr)for(unsigned c=0;c<3;++c)pixel[c]+=delta[c];
            context->UpdateSubresource(original.texture.Get(),0,nullptr,crop.data(),128*16,0);
            context->UpdateSubresource(neural.texture.Get(),0,nullptr,nr.data(),128*16,0);
            context->UpdateSubresource(destination.texture.Get(),0,nullptr,frame.data(),256*16,0);
            MapConstants mc;mc.oval=oval?1u:0u;
            context->UpdateSubresource(mapCB.Get(),0,nullptr,&mc,0,0);
            ID3D11Buffer* cb=mapCB.Get();context->CSSetConstantBuffers(0,1,&cb);
            ID3D11ShaderResourceView* sources[]{original.srv.Get(),neural.srv.Get()};context->CSSetShaderResources(0,2,sources);
            ID3D11UnorderedAccessView* target=coefficients.uav.Get();context->CSSetUnorderedAccessViews(0,1,&target,nullptr);
            context->CSSetShader(map.Get(),nullptr,0);context->Dispatch(2,2,1);Unbind(context.Get());
            sources[0]=coefficients.srv.Get();context->CSSetShaderResources(0,1,sources);
            target=filtered.uav.Get();context->CSSetUnorderedAccessViews(0,1,&target,nullptr);
            context->CSSetShader(smooth.Get(),nullptr,0);context->Dispatch(2,2,1);Unbind(context.Get());
            ApplyConstants ac;ac.oval=mc.oval;ac.black=fixture==2?1.0f:0.0f;
            context->UpdateSubresource(applyCB.Get(),0,nullptr,&ac,0,0);
            cb=applyCB.Get();context->CSSetConstantBuffers(0,1,&cb);
            sources[0]=filtered.srv.Get();context->CSSetShaderResources(0,1,sources);
            target=destination.uav.Get();context->CSSetUnorderedAccessViews(0,1,&target,nullptr);
            ID3D11SamplerState* smp=sampler.Get();context->CSSetSamplers(0,1,&smp);
            context->CSSetShader(apply.Get(),nullptr,0);context->Dispatch(256,(ac.total-1)/16384+1,1);Unbind(context.Get());
            context->CopyResource(staging.Get(),destination.texture.Get());
            D3D11_MAPPED_SUBRESOURCE mapped{};Check(context->Map(staging.Get(),0,D3D11_MAP_READ,0,&mapped));
            unsigned changed=0;
            for(unsigned y=0;y<192;++y) {
                const auto* row=reinterpret_cast<const std::array<float,4>*>(static_cast<const unsigned char*>(mapped.pData)+y*mapped.RowPitch);
                for(unsigned x=0;x<256;++x) {
                    const auto& before=frame[y*256+x];
                    const float dx=(float(x)+.5f-128)/64,dy=(float(y)+.5f-96)/48;
                    const bool inside=oval ? dx*dx+dy*dy<=1 : x>=64&&x<192&&y>=48&&y<144;
                    const bool distant=x<32||x>223||y<16||y>175;
                    for(unsigned c=0;c<4;++c) {
                        const float v=row[x][c];
                        if(!std::isfinite(v)||v<0)throw std::runtime_error("Invalid shader output");
                        if(c==3||inside||distant||fixture==2||fixture==3)
                            if(std::abs(v-before[c])>1e-5f)throw std::runtime_error("Protected/identity/black/alpha regression");
                    }
                    if(std::abs(row[x][0]-before[0])>.001f)++changed;
                    if(fixture>=4&&!inside) {
                        const float localX=float(x)-64,localY=float(y)-48;
                        const float outsideX=std::max(std::max(-localX,localX-127),0.0f),outsideY=std::max(std::max(-localY,localY-95),0.0f);
                        const float radial=std::sqrt(dx*dx+dy*dy);
                        const float distance=oval ? std::sqrt((float(x)+.5f-128)*(float(x)+.5f-128)+(float(y)+.5f-96)*(float(y)+.5f-96))*(1-1/radial) : std::sqrt(outsideX*outsideX+outsideY*outsideY);
                        const auto saturate=[](float v){return std::max(0.0f,std::min(1.0f,v));};
                        float t=saturate((distance/32-.35f)/.65f);const float fade=1-t*t*(3-2*t);
                        t=saturate(distance/4);const float weight=distance>=32?0:fade*t*t*(3-2*t);
                        const float luma=before[0]*.2126f+before[1]*.7152f+before[2]*.0722f;
                        const std::array<float,3> change{.2f*before[0]+.015f+(fixture==5?.04f*luma*luma:0),-.1f*before[1]-.01f-(fixture==5?.03f*luma*luma:0),.1f*before[2]+.005f+(fixture==5?.02f*luma*luma:0)};
                        for(unsigned c=0;c<3;++c)
                            if(std::abs(row[x][c]-(before[c]+change[c]*weight))>.003f)throw std::runtime_error("Mixed RGB curve prediction regression");
                    }
                }
            }
            context->Unmap(staging.Get(),0);
            if((fixture<2||fixture>=4) && changed<100)throw std::runtime_error("Outside tone or black lift missing");
            ++cases;
        }
    }
    std::cout << "Actual HLSL map, smoothing and compact apply executed on D3D11 WARP; cases=" << cases << "; protected masks, alpha, identity, color offsets, black lift and protection passed. No hardware GPU timing.\n";
}
