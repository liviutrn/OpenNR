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
struct alignas(16) ResultShapingConstants
		{
			std::uint32_t colorWidth = 0;
			std::uint32_t colorHeight = 0;
			std::uint32_t guideWidth = 0;
			std::uint32_t guideHeight = 0;
			float motionScaleX = 1.0f;
			float motionScaleY = 1.0f;
			float frameDeltaSeconds = 1.0f / 90.0f;
			float stabilizeTimeMs = 60.0f;
			float editStrength = 1.0f;
			float brightening = 1.0f;
			float darkening = 1.0f;
			float colorStrength = 1.0f;
			float hueShiftStrength = 1.0f;
			float shadows = 1.0f;
			float midtones = 1.0f;
			float highlights = 1.0f;
			float largeScaleTone = 1.0f;
			float fineDetail = 1.0f;
			float detailRadius = 1.0f;
			float haloSuppression = 0.0f;
			float maxBrighteningStops = 0.0f;
			float maxDarkeningStops = 0.0f;
			float maxColorChangeStops = 0.0f;
			float depthThreshold = 0.05f;
			float colorTolerance = 0.08f;
			std::uint32_t shapeEnabled = 0;
			std::uint32_t stabilizeMode = 0;
			std::uint32_t stabilizeDetail = 0;
			float historyEdgeFadePixels = 0.0f;
			float transitionWeightScale = 1.0f;
			float nearBlackProtection = 0.0f;
			float nearBlackThreshold = 0.035f;
			std::array<std::uint32_t, 4> previousLayout{};
			std::array<float, 2> originDelta{};
			float nearBlackLiftSoftness = 0.001f;
			float layoutPadding = 0.0f;
		};;
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

static_assert(sizeof(ResultShapingConstants)==160);
float Smooth(float a,float b,float v) {float t=std::clamp((v-a)/(b-a),0.0f,1.0f);return t*t*(3-2*t);}
int main()
{
    ComPtr<ID3D11Device> device;ComPtr<ID3D11DeviceContext> context;
    const D3D_FEATURE_LEVEL requested=D3D_FEATURE_LEVEL_11_0;D3D_FEATURE_LEVEL actual{};
    Check(D3D11CreateDevice(nullptr,D3D_DRIVER_TYPE_WARP,nullptr,0,&requested,1,D3D11_SDK_VERSION,device.GetAddressOf(),&actual,context.GetAddressOf()));
    auto shader=Compile(device.Get(),L"runtime/open-shaders/features/Upscaling/Shaders/Upscaling/NeuralRendering/ResultShapingCS.hlsl");
    auto original=MakeTexture(device.Get(),16,16),neural=MakeTexture(device.Get(),16,16);
    auto destination=MakeTexture(device.Get(),16,16),history=MakeTexture(device.Get(),16,16);
    auto buffer=MakeBuffer(device.Get(),160);
    D3D11_TEXTURE2D_DESC desc{};destination.texture->GetDesc(&desc);desc.BindFlags=0;desc.Usage=D3D11_USAGE_STAGING;desc.CPUAccessFlags=D3D11_CPU_ACCESS_READ;
    ComPtr<ID3D11Texture2D> staging;Check(device->CreateTexture2D(&desc,nullptr,staging.GetAddressOf()));
    unsigned cases=0;
    for(float strength:{0.0f,.5f,1.0f,2.0f}) for(float threshold:{.035f,.08f}) for(float softness:{.001f,.01f}) for(bool shaped:{false,true}) {
        std::vector<std::array<float,4>> input(256),nr(256),sentinel(256,std::array<float,4>{-1,-1,-1,-1});
        for(unsigned y=0;y<16;++y)for(unsigned x=0;x<16;++x) {
            auto& base=input[y*16+x];auto& model=nr[y*16+x];
            const unsigned fixture=x%8;const float gray=fixture==0?0:fixture==1?.005f:fixture==2?.02f:fixture==3?.06f:fixture==4?.15f:fixture==5?.025f:fixture==6?.01f:.007f;
            base={gray,gray,gray,.37f};model=base;model[3]=.73f;
            const float delta=fixture<2?.04f:fixture<5?.02f:fixture==5?-.01f:0;
            for(unsigned c=0;c<3;++c)model[c]+=delta;
            if(!shaped&&fixture==4) {base={.005f,.005f,.15f,.37f};model={.025f,.025f,.17f,.73f};}
            if(!shaped&&fixture==6) {model[0]+=.002f;model[1]-=.002f*.2126f/.7152f;model[1]+=(y%2?1:-1)*1e-7f;}
        }
        context->UpdateSubresource(original.texture.Get(),0,nullptr,input.data(),16*16,0);
        context->UpdateSubresource(neural.texture.Get(),0,nullptr,nr.data(),16*16,0);
        context->UpdateSubresource(destination.texture.Get(),0,nullptr,sentinel.data(),16*16,0);
        context->UpdateSubresource(history.texture.Get(),0,nullptr,sentinel.data(),16*16,0);
        ResultShapingConstants cb;cb.colorWidth=13;cb.colorHeight=11;cb.guideWidth=13;cb.guideHeight=11;
        cb.nearBlackProtection=strength;cb.nearBlackThreshold=threshold;cb.nearBlackLiftSoftness=softness;
        cb.shapeEnabled=shaped?1u:0u;cb.brightening=2;
        context->UpdateSubresource(buffer.Get(),0,nullptr,&cb,0,0);
        ID3D11Buffer* cbp=buffer.Get();context->CSSetConstantBuffers(0,1,&cbp);
        ID3D11ShaderResourceView* sources[]{original.srv.Get(),neural.srv.Get()};context->CSSetShaderResources(0,2,sources);
        ID3D11UnorderedAccessView* targets[]{destination.uav.Get(),history.uav.Get()};context->CSSetUnorderedAccessViews(0,2,targets,nullptr);
        context->CSSetShader(shader.Get(),nullptr,0);context->Dispatch(2,2,1);
        ID3D11UnorderedAccessView* nullTargets[2]{};context->CSSetUnorderedAccessViews(0,2,nullTargets,nullptr);Unbind(context.Get());
        for(unsigned which=0;which<2;++which) {
            context->CopyResource(staging.Get(),which?history.texture.Get():destination.texture.Get());
            D3D11_MAPPED_SUBRESOURCE mapped{};Check(context->Map(staging.Get(),0,D3D11_MAP_READ,0,&mapped));
            for(unsigned y=0;y<16;++y) {
                const auto* row=reinterpret_cast<const std::array<float,4>*>(static_cast<const unsigned char*>(mapped.pData)+y*mapped.RowPitch);
                for(unsigned x=0;x<16;++x)for(unsigned c=0;c<4;++c) {
                    float expected=-1;
                    if(x<13&&y<11) {
                        const auto& base=input[y*16+x];const auto& model=nr[y*16+x];
                        if(which||c==3) expected=model[c];
                        else {
                            std::array<float,3> delta{model[0]-base[0],model[1]-base[1],model[2]-base[2]};
                            if(shaped) {float lum=delta[0]*.2126f+delta[1]*.7152f+delta[2]*.0722f;if(lum>0)for(auto& value:delta)value+=lum;}
                            const float lum=delta[0]*.2126f+delta[1]*.7152f+delta[2]*.0722f;
                            const float peak=std::max({base[0],base[1],base[2],0.0f});
                            const float weight=lum<=0?0:std::clamp(strength*(1-Smooth(0,threshold,peak))*Smooth(0,softness,lum),0.0f,1.0f);
                            expected=std::max(base[c]+delta[c]*(1-weight),0.0f);
                        }
                    }
                    if(!std::isfinite(row[x][c])||std::abs(row[x][c]-expected)>1e-5f)throw std::runtime_error("Inside NR protection/history/alpha/dispatch bounds mismatch");
                }
            }
            context->Unmap(staging.Get(),0);
        }
        ++cases;
    }
    std::cout<<"Actual ResultShaping HLSL executed on D3D11 WARP; cases="<<cases<<"; 0/0.5/1/2 strengths, thresholds, onset softness, shaped and unshaped output, darkening, colored highlights, near-zero chroma edits, raw history, alpha and dispatch bounds passed. No hardware GPU timing.\n";
}
