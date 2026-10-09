#define NOMINMAX
#include <d3d11.h>
#include <d3dcompiler.h>
#include <d3d11shader.h>
#include <wrl/client.h>
#include <array>
#include <cmath>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <vector>
using Microsoft::WRL::ComPtr;
void Check(HRESULT result) {if(FAILED(result)) throw std::runtime_error("D3D11 test failed");}
void Require(bool result,const char* reason) {if(!result) throw std::runtime_error(reason);}
int main() {
 ComPtr<ID3D11Device> device;ComPtr<ID3D11DeviceContext> context;
 Check(D3D11CreateDevice(nullptr,D3D_DRIVER_TYPE_WARP,nullptr,0,nullptr,0,D3D11_SDK_VERSION,device.GetAddressOf(),nullptr,context.GetAddressOf()));
 ComPtr<ID3DBlob> code,error;D3D_SHADER_MACRO defines[]={{"VR","1"},{nullptr,nullptr}};
 auto result=D3DCompileFromFile(L"shader-smoke/TestMaskCS.hlsl",defines,D3D_COMPILE_STANDARD_FILE_INCLUDE,"main","cs_5_0",D3DCOMPILE_WARNINGS_ARE_ERRORS|D3DCOMPILE_OPTIMIZATION_LEVEL3,0,code.GetAddressOf(),error.GetAddressOf());
 if(FAILED(result)&&error) std::cerr<<static_cast<const char*>(error->GetBufferPointer());Check(result);
 ComPtr<ID3D11ComputeShader> shader;Check(device->CreateComputeShader(code->GetBufferPointer(),code->GetBufferSize(),nullptr,shader.GetAddressOf()));
 ComPtr<ID3D11ShaderReflection> reflection;Check(D3DReflect(code->GetBufferPointer(),code->GetBufferSize(),IID_PPV_ARGS(reflection.GetAddressOf())));
 auto cb=reflection->GetConstantBufferByName("SharedData");D3D11_SHADER_BUFFER_DESC desc{};Check(cb->GetDesc(&desc));std::vector<float> data(desc.Size/4);
 auto offset=[&](const char* name) {D3D11_SHADER_VARIABLE_DESC v{};Check(cb->GetVariableByName(name)->GetDesc(&v));return v.StartOffset/4;};
 const auto modes=offset("VRDetailFoveationModes");Require(modes==offset("RefractionScale")+1,"Padding mode ABI changed");
 Require(offset("WindFieldTuning")==offset("RefractionScale")+4,"Wind ABI shifted");
 const auto mask=offset("VRFoveationData0"),centers=offset("VRFoveationCenterOffsets");
 data[mask]=0.594604f;data[mask+1]=0.05f;data[mask+2]=1;
 data[centers]=0.15f;data[centers+2]=-0.15f;
 std::array<std::array<float,4>,16> samples{};
 samples[0]={0.65f,0.5f,0,0};samples[1]={0.9f,0.75f,0,0};samples[2]={0.99f,0.99f,0,0};
 samples[3]={0.65f+0.594604f*0.5f+0.025f,0.5f,0,0};samples[4]={0.9f,0.75f,1,0};
 D3D11_BUFFER_DESC bufferDesc{};bufferDesc.ByteWidth=sizeof(samples);bufferDesc.BindFlags=D3D11_BIND_CONSTANT_BUFFER;
 D3D11_SUBRESOURCE_DATA init{samples.data(),0,0};ComPtr<ID3D11Buffer> sampleBuffer;Check(device->CreateBuffer(&bufferDesc,&init,sampleBuffer.GetAddressOf()));
 bufferDesc.ByteWidth=desc.Size;ComPtr<ID3D11Buffer> shared;Check(device->CreateBuffer(&bufferDesc,nullptr,shared.GetAddressOf()));
 D3D11_TEXTURE2D_DESC textureDesc{};textureDesc.Width=16;textureDesc.Height=1;textureDesc.MipLevels=1;textureDesc.ArraySize=1;textureDesc.Format=DXGI_FORMAT_R32G32B32A32_FLOAT;textureDesc.SampleDesc.Count=1;textureDesc.BindFlags=D3D11_BIND_UNORDERED_ACCESS;
 ComPtr<ID3D11Texture2D> output;Check(device->CreateTexture2D(&textureDesc,nullptr,output.GetAddressOf()));ComPtr<ID3D11UnorderedAccessView> uav;Check(device->CreateUnorderedAccessView(output.Get(),nullptr,uav.GetAddressOf()));
 textureDesc.BindFlags=0;textureDesc.Usage=D3D11_USAGE_STAGING;textureDesc.CPUAccessFlags=D3D11_CPU_ACCESS_READ;ComPtr<ID3D11Texture2D> readback;Check(device->CreateTexture2D(&textureDesc,nullptr,readback.GetAddressOf()));
 context->CSSetShader(shader.Get(),nullptr,0);auto sb=sampleBuffer.Get(),db=shared.Get();context->CSSetConstantBuffers(0,1,&sb);context->CSSetConstantBuffers(5,1,&db);auto view=uav.Get();
 for(float mode : {0.0f,1.0f,2.0f}) {
  data[modes]=mode;context->UpdateSubresource(shared.Get(),0,nullptr,data.data(),0,0);context->CSSetUnorderedAccessViews(0,1,&view,nullptr);context->Dispatch(1,1,1);
  ID3D11UnorderedAccessView* empty=nullptr;context->CSSetUnorderedAccessViews(0,1,&empty,nullptr);context->CopyResource(readback.Get(),output.Get());D3D11_MAPPED_SUBRESOURCE mapped{};Check(context->Map(readback.Get(),0,D3D11_MAP_READ,0,&mapped));
  const auto values=static_cast<const float*>(mapped.pData);for(unsigned i=0;i<16*4;i++) Require(std::isfinite(values[i]),"Mask output not finite");
  Require(std::abs(values[0]-1)<1e-6f&&std::abs(values[4]-1)<1e-6f,"SR centre/corner lost detail");
  if(mode==0) {for(unsigned i=0;i<16*4;i++) Require(values[i]==1,"Off did not bypass");}
  else {Require(values[8]==0&&values[16]==0,"Exterior or opposite eye did not skip");if(mode==1) Require(values[12]>0.1f&&values[12]<0.9f,"Feather transition missing");else Require(values[12]==0,"Hard cutoff missing");}
  context->Unmap(readback.Get(),0);
 }
 std::cout<<"Actual HLSL mask: off, feather, hard cutoff, stereo offsets, corners and shared buffer ABI passed\n";
}
