#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <d3d11.h>
#include <d3dcompiler.h>
#include <DirectXMath.h>
#include <openvr.h>
#include <vector>
#include <string>
#include <array>
#include <cmath>
#include <algorithm>
#include <cstdint>
#include <cstring>

#pragma comment(lib, "d3d11.lib")
#pragma comment(lib, "dxgi.lib")
#pragma comment(lib, "d3dcompiler.lib")

using namespace DirectX;

static constexpr float kChartDistanceM = 6.0f;
static constexpr float kNear = 0.01f;
static constexpr float kFar = 100.0f;

struct Vertex { XMFLOAT3 pos; XMFLOAT4 color; };
struct EyeTarget {
    ID3D11Texture2D* tex = nullptr;
    ID3D11RenderTargetView* rtv = nullptr;
};

struct CB { XMFLOAT4X4 mvp; };

static HWND g_hwnd = nullptr;
static vr::IVRSystem* g_vr = nullptr;
static vr::IVRCompositor* g_comp = nullptr;
static ID3D11Device* g_dev = nullptr;
static ID3D11DeviceContext* g_ctx = nullptr;
static ID3D11VertexShader* g_vs = nullptr;
static ID3D11PixelShader* g_ps = nullptr;
static ID3D11InputLayout* g_layout = nullptr;
static ID3D11RasterizerState* g_rs = nullptr;
static ID3D11Buffer* g_vb = nullptr;
static ID3D11Buffer* g_cb = nullptr;
static EyeTarget g_eye[2];
static uint32_t g_w = 0, g_h = 0;
static UINT g_vertexCount = 0;
static XMMATRIX g_chartWorld = XMMatrixIdentity();
static bool g_haveChartPose = false;

static XMMATRIX FromVR34(const vr::HmdMatrix34_t& a) {
    // OpenVR matrices act on column vectors. Transpose into DirectX row-vector convention.
    return XMMATRIX(
        a.m[0][0], a.m[1][0], a.m[2][0], 0.0f,
        a.m[0][1], a.m[1][1], a.m[2][1], 0.0f,
        a.m[0][2], a.m[1][2], a.m[2][2], 0.0f,
        a.m[0][3], a.m[1][3], a.m[2][3], 1.0f);
}
static XMMATRIX FromVR44(const vr::HmdMatrix44_t& a) {
    return XMMATRIX(
        a.m[0][0], a.m[1][0], a.m[2][0], a.m[3][0],
        a.m[0][1], a.m[1][1], a.m[2][1], a.m[3][1],
        a.m[0][2], a.m[1][2], a.m[2][2], a.m[3][2],
        a.m[0][3], a.m[1][3], a.m[2][3], a.m[3][3]);
}

static void AddQuad(std::vector<Vertex>& v, float x0, float y0, float x1, float y1, float z, const XMFLOAT4& c) {
    Vertex a{{x0,y0,z},c}, b{{x1,y0,z},c}, d{{x0,y1,z},c}, e{{x1,y1,z},c};
    v.insert(v.end(), {a,b,d, d,b,e});
}

using Glyph = std::array<const char*,5>;
static const Glyph* GlyphFor(char ch) {
    static const Glyph E={"11111","10000","11111","10000","11111"};
    static const Glyph F={"11111","10000","11110","10000","10000"};
    static const Glyph P={"11110","10001","11110","10000","10000"};
    static const Glyph T={"11111","00100","00100","00100","00100"};
    static const Glyph O={"01110","10001","10001","10001","01110"};
    static const Glyph Z={"11111","00010","00100","01000","11111"};
    static const Glyph L={"10000","10000","10000","10000","11111"};
    static const Glyph D={"11110","10001","10001","10001","11110"};
    static const Glyph C={"01111","10000","10000","10000","01111"};
    switch(ch){
        case 'E': return &E; case 'F': return &F; case 'P': return &P;
        case 'T': return &T; case 'O': return &O; case 'Z': return &Z;
        case 'L': return &L; case 'D': return &D; case 'C': return &C;
        default: return nullptr;
    }
}

static float SnellenHeightM(int denominator) {
    // A 20/20 optotype subtends exactly 5 arc-minutes. Larger rows scale by denominator/20.
    const double minutes = 5.0 * (double(denominator) / 20.0);
    const double theta = minutes * (3.14159265358979323846 / (180.0 * 60.0));
    return float(2.0 * kChartDistanceM * std::tan(theta * 0.5));
}

static void AddGlyph(std::vector<Vertex>& v, char ch, float cx, float cy, float h) {
    const Glyph* g = GlyphFor(ch); if(!g) return;
    const float cell = h/5.0f;
    const float left = cx - h*0.5f;
    const float top = cy + h*0.5f;
    const XMFLOAT4 black{0,0,0,1};
    for(int r=0;r<5;r++) for(int c=0;c<5;c++) if((*g)[r][c]=='1') {
        float x0 = left + c*cell;
        float x1 = x0 + cell;
        float y1 = top - r*cell;
        float y0 = y1 - cell;
        AddQuad(v,x0,y0,x1,y1,-0.0005f,black);
    }
}

static std::vector<Vertex> BuildChart() {
    struct Row { int den; const char* text; };
    const Row rows[] = {
        {200,"E"}, {100,"FP"}, {70,"TOZ"}, {50,"LPED"},
        {40,"PECFD"}, {30,"EDFCZP"}, {25,"FELOPZD"}, {20,"DEFPOTEC"}
    };
    std::vector<Vertex> v;

    // Layout is physically dimensioned in metres at the plane, not in pixels.
    float y = 0.170f;
    float minY = 1e9f, maxY = -1e9f, maxHalfWidth = 0.0f;
    struct L { float y,h,w; const char* s; };
    std::vector<L> laid;
    for (const auto& row: rows) {
        float h = SnellenHeightM(row.den);
        size_t n = strlen(row.text);
        float gap = 0.55f*h;
        float w = n*h + (n>0 ? (n-1)*gap : 0.0f);
        laid.push_back({y,h,w,row.text});
        minY = std::min(minY, y-h*0.5f); maxY = std::max(maxY, y+h*0.5f);
        maxHalfWidth = std::max(maxHalfWidth, w*0.5f);
        y -= h + std::max(0.010f, 0.50f*h);
    }
    float centerY=(minY+maxY)*0.5f;
    const float marginX=0.050f, marginY=0.040f;
    const XMFLOAT4 white{1,1,1,1};
    AddQuad(v,-maxHalfWidth-marginX,minY-centerY-marginY,maxHalfWidth+marginX,maxY-centerY+marginY,0.0f,white);
    for(const auto& line: laid){
        size_t n=strlen(line.s); float gap=0.55f*line.h;
        float x=-line.w*0.5f + line.h*0.5f;
        for(size_t i=0;i<n;i++,x+=line.h+gap) AddGlyph(v,line.s[i],x,line.y-centerY,line.h);
    }
    return v;
}

static bool CompileShader(const char* src, const char* entry, const char* target, ID3DBlob** blob) {
    ID3DBlob* err=nullptr;
    HRESULT hr=D3DCompile(src,strlen(src),nullptr,nullptr,nullptr,entry,target,D3DCOMPILE_OPTIMIZATION_LEVEL3,0,blob,&err);
    if(FAILED(hr)){
        if(err){ OutputDebugStringA((char*)err->GetBufferPointer()); err->Release(); }
        return false;
    }
    if(err) err->Release();
    return true;
}

static bool InitD3D(){
    D3D_FEATURE_LEVEL got;
    D3D_FEATURE_LEVEL levels[]={D3D_FEATURE_LEVEL_11_1,D3D_FEATURE_LEVEL_11_0,D3D_FEATURE_LEVEL_10_1};
    UINT flags=D3D11_CREATE_DEVICE_BGRA_SUPPORT;
    HRESULT hr=D3D11CreateDevice(nullptr,D3D_DRIVER_TYPE_HARDWARE,nullptr,flags,levels,3,D3D11_SDK_VERSION,&g_dev,&got,&g_ctx);
    if(FAILED(hr)) return false;

    const char* vsSrc=R"(
cbuffer CB0 : register(b0) { row_major float4x4 mvp; };
struct VSIn { float3 pos:POSITION; float4 color:COLOR; };
struct VSOut { float4 pos:SV_POSITION; float4 color:COLOR; };
VSOut main(VSIn i){ VSOut o; o.pos=mul(float4(i.pos,1.0),mvp); o.color=i.color; return o; }
)";
    const char* psSrc=R"(
struct PSIn { float4 pos:SV_POSITION; float4 color:COLOR; };
float4 main(PSIn i):SV_TARGET { return i.color; }
)";
    ID3DBlob *vsb=nullptr,*psb=nullptr;
    if(!CompileShader(vsSrc,"main","vs_5_0",&vsb) || !CompileShader(psSrc,"main","ps_5_0",&psb)) return false;
    hr=g_dev->CreateVertexShader(vsb->GetBufferPointer(),vsb->GetBufferSize(),nullptr,&g_vs); if(FAILED(hr)) return false;
    hr=g_dev->CreatePixelShader(psb->GetBufferPointer(),psb->GetBufferSize(),nullptr,&g_ps); if(FAILED(hr)) return false;
    D3D11_INPUT_ELEMENT_DESC il[]={
        {"POSITION",0,DXGI_FORMAT_R32G32B32_FLOAT,0,0,D3D11_INPUT_PER_VERTEX_DATA,0},
        {"COLOR",0,DXGI_FORMAT_R32G32B32A32_FLOAT,0,12,D3D11_INPUT_PER_VERTEX_DATA,0}
    };
    hr=g_dev->CreateInputLayout(il,2,vsb->GetBufferPointer(),vsb->GetBufferSize(),&g_layout);
    vsb->Release(); psb->Release(); if(FAILED(hr)) return false;
    D3D11_RASTERIZER_DESC rd{}; rd.FillMode=D3D11_FILL_SOLID; rd.CullMode=D3D11_CULL_NONE; rd.DepthClipEnable=TRUE;
    if(FAILED(g_dev->CreateRasterizerState(&rd,&g_rs))) return false;

    auto verts=BuildChart(); g_vertexCount=(UINT)verts.size();
    D3D11_BUFFER_DESC bd{}; bd.ByteWidth=(UINT)(verts.size()*sizeof(Vertex)); bd.Usage=D3D11_USAGE_IMMUTABLE; bd.BindFlags=D3D11_BIND_VERTEX_BUFFER;
    D3D11_SUBRESOURCE_DATA sd{}; sd.pSysMem=verts.data();
    if(FAILED(g_dev->CreateBuffer(&bd,&sd,&g_vb))) return false;
    D3D11_BUFFER_DESC cbd{}; cbd.ByteWidth=(sizeof(CB)+15)&~15; cbd.Usage=D3D11_USAGE_DYNAMIC; cbd.BindFlags=D3D11_BIND_CONSTANT_BUFFER; cbd.CPUAccessFlags=D3D11_CPU_ACCESS_WRITE;
    if(FAILED(g_dev->CreateBuffer(&cbd,nullptr,&g_cb))) return false;

    g_vr->GetRecommendedRenderTargetSize(&g_w,&g_h);
    for(int i=0;i<2;i++){
        D3D11_TEXTURE2D_DESC td{}; td.Width=g_w; td.Height=g_h; td.MipLevels=1; td.ArraySize=1; td.Format=DXGI_FORMAT_R8G8B8A8_UNORM; td.SampleDesc.Count=1;
        td.Usage=D3D11_USAGE_DEFAULT; td.BindFlags=D3D11_BIND_RENDER_TARGET|D3D11_BIND_SHADER_RESOURCE;
        if(FAILED(g_dev->CreateTexture2D(&td,nullptr,&g_eye[i].tex))) return false;
        if(FAILED(g_dev->CreateRenderTargetView(g_eye[i].tex,nullptr,&g_eye[i].rtv))) return false;
    }
    return true;
}

static XMVECTOR CyclopeanEyeInHead(){
    auto l=g_vr->GetEyeToHeadTransform(vr::Eye_Left);
    auto r=g_vr->GetEyeToHeadTransform(vr::Eye_Right);
    return XMVectorSet((l.m[0][3]+r.m[0][3])*0.5f,(l.m[1][3]+r.m[1][3])*0.5f,(l.m[2][3]+r.m[2][3])*0.5f,1.0f);
}

static void SetChartPose(const vr::TrackedDevicePose_t& pose){
    if(!pose.bPoseIsValid) return;
    XMMATRIX headToWorld=FromVR34(pose.mDeviceToAbsoluteTracking);
    XMVECTOR cycl=XMVector3TransformCoord(CyclopeanEyeInHead(),headToWorld);
    // Head local -Z is forward in OpenVR. Transform as a direction into world space.
    XMVECTOR forward=XMVector3Normalize(XMVector3TransformNormal(XMVectorSet(0,0,-1,0),headToWorld));
    XMVECTOR up=XMVector3Normalize(XMVector3TransformNormal(XMVectorSet(0,1,0,0),headToWorld));
    XMVECTOR right=XMVector3Normalize(XMVector3Cross(forward,up));
    up=XMVector3Normalize(XMVector3Cross(right,forward));
    XMVECTOR center=cycl + forward*kChartDistanceM;

    XMFLOAT3 rr,uu,cc; XMStoreFloat3(&rr,right); XMStoreFloat3(&uu,up); XMStoreFloat3(&cc,center);
    // Local chart +X=right, +Y=up, +Z=toward viewer (opposite forward).
    XMVECTOR toward=-forward; XMFLOAT3 tt; XMStoreFloat3(&tt,toward);
    g_chartWorld=XMMATRIX(
        rr.x,rr.y,rr.z,0,
        uu.x,uu.y,uu.z,0,
        tt.x,tt.y,tt.z,0,
        cc.x,cc.y,cc.z,1);
    g_haveChartPose=true;
}

static void RenderEye(int idx, vr::Hmd_Eye eye, const vr::TrackedDevicePose_t& hmdPose){
    float clear[4]={0,0,0,1};
    g_ctx->OMSetRenderTargets(1,&g_eye[idx].rtv,nullptr);
    g_ctx->ClearRenderTargetView(g_eye[idx].rtv,clear);
    D3D11_VIEWPORT vp{0,0,(float)g_w,(float)g_h,0,1}; g_ctx->RSSetViewports(1,&vp); g_ctx->RSSetState(g_rs);
    UINT stride=sizeof(Vertex), offset=0; g_ctx->IASetInputLayout(g_layout); g_ctx->IASetVertexBuffers(0,1,&g_vb,&stride,&offset); g_ctx->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    g_ctx->VSSetShader(g_vs,nullptr,0); g_ctx->PSSetShader(g_ps,nullptr,0); g_ctx->VSSetConstantBuffers(0,1,&g_cb);

    XMMATRIX hmdToWorld=FromVR34(hmdPose.mDeviceToAbsoluteTracking);
    XMMATRIX worldToHead=XMMatrixInverse(nullptr,hmdToWorld);
    XMMATRIX eyeToHead=FromVR34(g_vr->GetEyeToHeadTransform(eye));
    XMMATRIX headToEye=XMMatrixInverse(nullptr,eyeToHead);
    XMMATRIX proj=FromVR44(g_vr->GetProjectionMatrix(eye,kNear,kFar));
    XMMATRIX mvp=g_chartWorld*worldToHead*headToEye*proj;

    D3D11_MAPPED_SUBRESOURCE ms{}; if(SUCCEEDED(g_ctx->Map(g_cb,0,D3D11_MAP_WRITE_DISCARD,0,&ms))){
        CB* cb=(CB*)ms.pData; XMStoreFloat4x4(&cb->mvp,mvp); g_ctx->Unmap(g_cb,0);
    }
    g_ctx->Draw(g_vertexCount,0);
}

static LRESULT CALLBACK WndProc(HWND h,UINT m,WPARAM w,LPARAM l){
    if(m==WM_DESTROY){PostQuitMessage(0);return 0;}
    if(m==WM_KEYDOWN && w==VK_ESCAPE){PostQuitMessage(0);return 0;}
    return DefWindowProc(h,m,w,l);
}

static void Cleanup(){
    for(auto& e:g_eye){ if(e.rtv)e.rtv->Release(); if(e.tex)e.tex->Release(); }
    if(g_cb)g_cb->Release(); if(g_vb)g_vb->Release(); if(g_rs)g_rs->Release(); if(g_layout)g_layout->Release(); if(g_ps)g_ps->Release(); if(g_vs)g_vs->Release();
    if(g_ctx)g_ctx->Release(); if(g_dev)g_dev->Release();
    if(g_vr) vr::VR_Shutdown();
}

int WINAPI WinMain(HINSTANCE hi,HINSTANCE,LPSTR,int){
    WNDCLASSA wc{}; wc.lpfnWndProc=WndProc; wc.hInstance=hi; wc.lpszClassName="VRSnellenWnd"; wc.hCursor=LoadCursor(nullptr,IDC_ARROW);
    RegisterClassA(&wc); g_hwnd=CreateWindowA(wc.lpszClassName,"VR Snellen 6m - R recenter, Esc quit",WS_OVERLAPPEDWINDOW,100,100,640,240,nullptr,nullptr,hi,nullptr);
    ShowWindow(g_hwnd,SW_SHOW);

    vr::EVRInitError err=vr::VRInitError_None; g_vr=vr::VR_Init(&err,vr::VRApplication_Scene);
    if(err!=vr::VRInitError_None || !g_vr){ MessageBoxA(nullptr,vr::VR_GetVRInitErrorAsEnglishDescription(err),"OpenVR init failed",MB_ICONERROR); return 1; }
    g_comp=vr::VRCompositor(); if(!g_comp){MessageBoxA(nullptr,"SteamVR compositor unavailable.","VR Snellen",MB_ICONERROR);Cleanup();return 2;}
    if(!InitD3D()){MessageBoxA(nullptr,"Direct3D 11 initialization failed.","VR Snellen",MB_ICONERROR);Cleanup();return 3;}

    bool quit=false; vr::TrackedDevicePose_t poses[vr::k_unMaxTrackedDeviceCount]{};
    while(!quit){
        MSG msg; while(PeekMessage(&msg,nullptr,0,0,PM_REMOVE)){ if(msg.message==WM_QUIT)quit=true; TranslateMessage(&msg); DispatchMessage(&msg); }
        if(quit) break;
        g_comp->WaitGetPoses(poses,vr::k_unMaxTrackedDeviceCount,nullptr,0);
        auto& hp=poses[vr::k_unTrackedDeviceIndex_Hmd]; if(!hp.bPoseIsValid) continue;
        if(!g_haveChartPose || (GetAsyncKeyState('R')&1)) SetChartPose(hp);
        RenderEye(0,vr::Eye_Left,hp); RenderEye(1,vr::Eye_Right,hp);
        vr::Texture_t lt={(void*)g_eye[0].tex,vr::TextureType_DirectX,vr::ColorSpace_Gamma};
        vr::Texture_t rt={(void*)g_eye[1].tex,vr::TextureType_DirectX,vr::ColorSpace_Gamma};
        g_comp->Submit(vr::Eye_Left,&lt); g_comp->Submit(vr::Eye_Right,&rt); g_comp->PostPresentHandoff();
    }
    Cleanup(); return 0;
}
