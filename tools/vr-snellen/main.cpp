#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <d3d11.h>
#include <d3dcompiler.h>
#include <DirectXMath.h>
#include <openvr.h>
#include <vector>
#include <array>
#include <cmath>
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <cstdio>

#pragma comment(lib, "d3d11.lib")
#pragma comment(lib, "dxgi.lib")
#pragma comment(lib, "d3dcompiler.lib")

using namespace DirectX;

static constexpr float kChartDistanceM = 6.0f;
static constexpr float kNear = 0.01f;
static constexpr float kFar = 100.0f;

struct Vertex { XMFLOAT3 pos; XMFLOAT4 color; };

struct EyeTarget {
    ID3D11Texture2D* submitTex = nullptr;   // single-sample texture submitted to OpenVR
    ID3D11RenderTargetView* submitRTV = nullptr;
    ID3D11Texture2D* msaaTex = nullptr;     // multisample render target
    ID3D11RenderTargetView* msaaRTV = nullptr;
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
static UINT g_msaaCount = 1;
static UINT g_vertexCount = 0;

static XMMATRIX FromVR34(const vr::HmdMatrix34_t& a) {
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

// Snellen-style 5x5 optotypes. Each occupied cell is exactly one-fifth
// of the optotype height/width, so a 20/20 cell subtends 1 arc-minute.
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
    switch(ch) {
        case 'E': return &E; case 'F': return &F; case 'P': return &P;
        case 'T': return &T; case 'O': return &O; case 'Z': return &Z;
        case 'L': return &L; case 'D': return &D; case 'C': return &C;
        default: return nullptr;
    }
}

static float SnellenHeightM(int denominator) {
    // Exact angular definition: 20/20 optotype = 5 arc-minutes high.
    const double minutes = 5.0 * (double(denominator) / 20.0);
    const double theta = minutes * (3.14159265358979323846 / (180.0 * 60.0));
    return float(2.0 * kChartDistanceM * std::tan(theta * 0.5));
}

static void AddGlyph(std::vector<Vertex>& v, char ch, float cx, float cy, float h) {
    const Glyph* g = GlyphFor(ch);
    if(!g) return;
    const float cell = h / 5.0f;
    const float left = cx - h * 0.5f;
    const float top = cy + h * 0.5f;
    const XMFLOAT4 black{0,0,0,1};
    for(int r=0; r<5; ++r) for(int c=0; c<5; ++c) if((*g)[r][c]=='1') {
        const float x0 = left + c*cell, x1 = x0 + cell;
        const float y1 = top - r*cell,  y0 = y1 - cell;
        AddQuad(v, x0,y0,x1,y1, -0.0005f, black);
    }
}

// Small vector font used only for row labels (20/20, 20/40, ...).
using LabelGlyph = std::array<const char*,7>;
static const LabelGlyph* LabelFor(char ch) {
    static const LabelGlyph n0={"01110","10001","10011","10101","11001","10001","01110"};
    static const LabelGlyph n1={"00100","01100","00100","00100","00100","00100","01110"};
    static const LabelGlyph n2={"01110","10001","00001","00010","00100","01000","11111"};
    static const LabelGlyph n3={"11110","00001","00001","01110","00001","00001","11110"};
    static const LabelGlyph n4={"00010","00110","01010","10010","11111","00010","00010"};
    static const LabelGlyph n5={"11111","10000","10000","11110","00001","00001","11110"};
    static const LabelGlyph n6={"01110","10000","10000","11110","10001","10001","01110"};
    static const LabelGlyph n7={"11111","00001","00010","00100","01000","01000","01000"};
    static const LabelGlyph n8={"01110","10001","10001","01110","10001","10001","01110"};
    static const LabelGlyph n9={"01110","10001","10001","01111","00001","00001","01110"};
    static const LabelGlyph sl={"00001","00010","00100","01000","10000","00000","00000"};
    switch(ch) {
        case '0': return &n0; case '1': return &n1; case '2': return &n2; case '3': return &n3; case '4': return &n4;
        case '5': return &n5; case '6': return &n6; case '7': return &n7; case '8': return &n8; case '9': return &n9;
        case '/': return &sl; default: return nullptr;
    }
}

static void AddLabel(std::vector<Vertex>& v, const char* text, float left, float cy, float h) {
    const float cell = h / 7.0f;
    const float glyphW = cell * 5.0f;
    const float gap = cell * 1.5f;
    const XMFLOAT4 black{0,0,0,1};
    float x = left;
    for(const char* p=text; *p; ++p) {
        const LabelGlyph* g = LabelFor(*p);
        if(g) {
            const float top = cy + h*0.5f;
            for(int r=0;r<7;++r) for(int c=0;c<5;++c) if((*g)[r][c]=='1') {
                float x0=x+c*cell, x1=x0+cell;
                float y1=top-r*cell, y0=y1-cell;
                AddQuad(v,x0,y0,x1,y1,-0.0006f,black);
            }
        }
        x += glyphW + gap;
    }
}

static std::vector<Vertex> BuildChart() {
    struct Row { int den; const char* text; };

    // Fixed 20-optotype rows so comparisons remain identical between resolutions/runs.
    // Characters are drawn from the same Snellen-style set used by the original chart.
    const Row rows[] = {
        {200,"EFPTOZLCDPEFTOZLCPDF"},
        {100,"PZLFEOTCDEZPTFLCODPE"},
        { 70,"TOZLPEDCFETZOLPCDFEP"},
        { 50,"LPEDCFZOTPECLDFOZETP"},
        { 40,"PECFDZLTODFEPCLZOTPE"},
        { 30,"EDFCZPLOTCEFDZLTOPCE"},
        { 25,"FELOPZDCETFPLZODECFT"},
        { 20,"DEFPOTECZLCPDFOZETLP"}
    };

    std::vector<Vertex> v;
    struct L { float y,h,w; const char* s; int den; };
    std::vector<L> laid;

    float y = 0.330f;
    float minY = 1e9f, maxY = -1e9f, maxHalfWidth = 0.0f;

    for(const auto& row : rows) {
        const float h = SnellenHeightM(row.den);
        const size_t n = strlen(row.text);
        const float gap = 0.45f * h;
        const float w = n*h + (n ? (n-1)*gap : 0.0f);
        laid.push_back({y,h,w,row.text,row.den});
        minY = std::min(minY, y-h*0.5f);
        maxY = std::max(maxY, y+h*0.5f);
        maxHalfWidth = std::max(maxHalfWidth, w*0.5f);
        y -= h + std::max(0.014f, 0.48f*h);
    }

    const float centerY = (minY+maxY)*0.5f;
    const float labelH = 0.018f;          // readable annotation; does not define acuity
    const float labelGap = 0.025f;
    const float labelWidth = 7.0f * (labelH/7.0f*5.0f + labelH/7.0f*1.5f);
    const float marginX = 0.060f, marginY = 0.050f;

    // Board is intentionally much larger than v1; optotype angular sizes are unchanged.
    const float boardHalfW = maxHalfWidth + labelGap + labelWidth + marginX;
    const XMFLOAT4 white{1,1,1,1};
    AddQuad(v, -boardHalfW, minY-centerY-marginY, boardHalfW, maxY-centerY+marginY, 0.0f, white);

    char label[16]{};
    for(const auto& line : laid) {
        const size_t n = strlen(line.s);
        const float gap = 0.45f*line.h;
        float x = -line.w*0.5f + line.h*0.5f;
        for(size_t i=0;i<n;++i, x += line.h+gap)
            AddGlyph(v, line.s[i], x, line.y-centerY, line.h);

        std::snprintf(label,sizeof(label),"20/%d",line.den);
        AddLabel(v,label,line.w*0.5f+labelGap,line.y-centerY,labelH);
    }
    return v;
}

static bool CompileShader(const char* src, const char* entry, const char* target, ID3DBlob** blob) {
    ID3DBlob* err=nullptr;
    HRESULT hr=D3DCompile(src,strlen(src),nullptr,nullptr,nullptr,entry,target,D3DCOMPILE_OPTIMIZATION_LEVEL3,0,blob,&err);
    if(FAILED(hr)) {
        if(err) { OutputDebugStringA((char*)err->GetBufferPointer()); err->Release(); }
        return false;
    }
    if(err) err->Release();
    return true;
}

static void ReleaseEyeTargets() {
    for(auto& e : g_eye) {
        if(e.msaaRTV) { e.msaaRTV->Release(); e.msaaRTV=nullptr; }
        if(e.msaaTex) { e.msaaTex->Release(); e.msaaTex=nullptr; }
        if(e.submitRTV) { e.submitRTV->Release(); e.submitRTV=nullptr; }
        if(e.submitTex) { e.submitTex->Release(); e.submitTex=nullptr; }
    }
}

static UINT ChooseMSAA() {
    const DXGI_FORMAT fmt=DXGI_FORMAT_R8G8B8A8_UNORM;
    for(UINT count : {8u,4u,2u}) {
        UINT q=0;
        if(SUCCEEDED(g_dev->CheckMultisampleQualityLevels(fmt,count,&q)) && q>0) return count;
    }
    return 1;
}

static void UpdateWindowTitle() {
    char t[256];
    std::snprintf(t,sizeof(t),"VR Snellen 6m | HEAD-LOCKED | %ux%u per eye | %ux MSAA | Esc quit",g_w,g_h,g_msaaCount);
    SetWindowTextA(g_hwnd,t);
}

static bool CreateEyeTargets(uint32_t w, uint32_t h) {
    ReleaseEyeTargets();
    g_w=w; g_h=h;
    g_msaaCount=ChooseMSAA();
    const DXGI_FORMAT fmt=DXGI_FORMAT_R8G8B8A8_UNORM;

    for(int i=0;i<2;++i) {
        D3D11_TEXTURE2D_DESC td{};
        td.Width=g_w; td.Height=g_h; td.MipLevels=1; td.ArraySize=1;
        td.Format=fmt; td.SampleDesc.Count=1;
        td.Usage=D3D11_USAGE_DEFAULT;
        td.BindFlags=D3D11_BIND_RENDER_TARGET|D3D11_BIND_SHADER_RESOURCE;
        if(FAILED(g_dev->CreateTexture2D(&td,nullptr,&g_eye[i].submitTex))) return false;
        if(FAILED(g_dev->CreateRenderTargetView(g_eye[i].submitTex,nullptr,&g_eye[i].submitRTV))) return false;

        if(g_msaaCount>1) {
            D3D11_TEXTURE2D_DESC md=td;
            md.SampleDesc.Count=g_msaaCount;
            md.SampleDesc.Quality=0;
            md.BindFlags=D3D11_BIND_RENDER_TARGET;
            if(FAILED(g_dev->CreateTexture2D(&md,nullptr,&g_eye[i].msaaTex))) return false;
            if(FAILED(g_dev->CreateRenderTargetView(g_eye[i].msaaTex,nullptr,&g_eye[i].msaaRTV))) return false;
        }
    }
    UpdateWindowTitle();
    return true;
}

static bool EnsureSteamVRRenderTargetSize() {
    uint32_t w=0,h=0;
    g_vr->GetRecommendedRenderTargetSize(&w,&h);
    if(w==0 || h==0) return false;
    if(w!=g_w || h!=g_h || !g_eye[0].submitTex || !g_eye[1].submitTex)
        return CreateEyeTargets(w,h);
    return true;
}

static bool InitD3D() {
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
    vsb->Release(); psb->Release();
    if(FAILED(hr)) return false;

    D3D11_RASTERIZER_DESC rd{};
    rd.FillMode=D3D11_FILL_SOLID; rd.CullMode=D3D11_CULL_NONE;
    rd.MultisampleEnable=TRUE; rd.AntialiasedLineEnable=FALSE; rd.DepthClipEnable=TRUE;
    if(FAILED(g_dev->CreateRasterizerState(&rd,&g_rs))) return false;

    auto verts=BuildChart();
    g_vertexCount=(UINT)verts.size();

    D3D11_BUFFER_DESC bd{};
    bd.ByteWidth=(UINT)(verts.size()*sizeof(Vertex));
    bd.Usage=D3D11_USAGE_IMMUTABLE; bd.BindFlags=D3D11_BIND_VERTEX_BUFFER;
    D3D11_SUBRESOURCE_DATA sd{}; sd.pSysMem=verts.data();
    if(FAILED(g_dev->CreateBuffer(&bd,&sd,&g_vb))) return false;

    D3D11_BUFFER_DESC cbd{};
    cbd.ByteWidth=(sizeof(CB)+15)&~15;
    cbd.Usage=D3D11_USAGE_DYNAMIC; cbd.BindFlags=D3D11_BIND_CONSTANT_BUFFER;
    cbd.CPUAccessFlags=D3D11_CPU_ACCESS_WRITE;
    if(FAILED(g_dev->CreateBuffer(&cbd,nullptr,&g_cb))) return false;

    return EnsureSteamVRRenderTargetSize();
}

static XMVECTOR CyclopeanEyeInHead() {
    const auto l=g_vr->GetEyeToHeadTransform(vr::Eye_Left);
    const auto r=g_vr->GetEyeToHeadTransform(vr::Eye_Right);
    return XMVectorSet((l.m[0][3]+r.m[0][3])*0.5f,
                       (l.m[1][3]+r.m[1][3])*0.5f,
                       (l.m[2][3]+r.m[2][3])*0.5f,1.0f);
}

static XMMATRIX HeadLockedChartTransform() {
    // Keep the plane rigidly head-locked, but preserve physical 6.000 m distance
    // from the cyclopean eye and preserve the normal per-eye stereo transforms.
    XMFLOAT4 cycl{};
    XMStoreFloat4(&cycl,CyclopeanEyeInHead());
    return XMMatrixTranslation(cycl.x,cycl.y,cycl.z-kChartDistanceM);
}

static void RenderEye(int idx, vr::Hmd_Eye eye) {
    ID3D11RenderTargetView* target =
        (g_msaaCount>1 && g_eye[idx].msaaRTV) ? g_eye[idx].msaaRTV : g_eye[idx].submitRTV;

    const float clear[4]={0,0,0,1};
    g_ctx->OMSetRenderTargets(1,&target,nullptr);
    g_ctx->ClearRenderTargetView(target,clear);

    D3D11_VIEWPORT vp{0,0,(float)g_w,(float)g_h,0,1};
    g_ctx->RSSetViewports(1,&vp);
    g_ctx->RSSetState(g_rs);

    UINT stride=sizeof(Vertex), offset=0;
    g_ctx->IASetInputLayout(g_layout);
    g_ctx->IASetVertexBuffers(0,1,&g_vb,&stride,&offset);
    g_ctx->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    g_ctx->VSSetShader(g_vs,nullptr,0);
    g_ctx->PSSetShader(g_ps,nullptr,0);
    g_ctx->VSSetConstantBuffers(0,1,&g_cb);

    const XMMATRIX chartInHead=HeadLockedChartTransform();
    const XMMATRIX eyeToHead=FromVR34(g_vr->GetEyeToHeadTransform(eye));
    const XMMATRIX headToEye=XMMatrixInverse(nullptr,eyeToHead);
    const XMMATRIX proj=FromVR44(g_vr->GetProjectionMatrix(eye,kNear,kFar));
    const XMMATRIX mvp=chartInHead*headToEye*proj;

    D3D11_MAPPED_SUBRESOURCE ms{};
    if(SUCCEEDED(g_ctx->Map(g_cb,0,D3D11_MAP_WRITE_DISCARD,0,&ms))) {
        CB* cb=(CB*)ms.pData;
        XMStoreFloat4x4(&cb->mvp,mvp);
        g_ctx->Unmap(g_cb,0);
    }
    g_ctx->Draw(g_vertexCount,0);

    if(g_msaaCount>1 && g_eye[idx].msaaTex)
        g_ctx->ResolveSubresource(g_eye[idx].submitTex,0,g_eye[idx].msaaTex,0,DXGI_FORMAT_R8G8B8A8_UNORM);
}

static LRESULT CALLBACK WndProc(HWND h,UINT m,WPARAM w,LPARAM l) {
    if(m==WM_DESTROY) { PostQuitMessage(0); return 0; }
    if(m==WM_KEYDOWN && w==VK_ESCAPE) { PostQuitMessage(0); return 0; }
    return DefWindowProc(h,m,w,l);
}

static void Cleanup() {
    ReleaseEyeTargets();
    if(g_cb)g_cb->Release();
    if(g_vb)g_vb->Release();
    if(g_rs)g_rs->Release();
    if(g_layout)g_layout->Release();
    if(g_ps)g_ps->Release();
    if(g_vs)g_vs->Release();
    if(g_ctx)g_ctx->Release();
    if(g_dev)g_dev->Release();
    if(g_vr) vr::VR_Shutdown();
}

int WINAPI WinMain(HINSTANCE hi,HINSTANCE,LPSTR,int) {
    WNDCLASSA wc{};
    wc.lpfnWndProc=WndProc; wc.hInstance=hi;
    wc.lpszClassName="VRSnellenWnd"; wc.hCursor=LoadCursor(nullptr,IDC_ARROW);
    RegisterClassA(&wc);
    g_hwnd=CreateWindowA(wc.lpszClassName,"VR Snellen 6m",WS_OVERLAPPEDWINDOW,
                         100,100,760,240,nullptr,nullptr,hi,nullptr);
    ShowWindow(g_hwnd,SW_SHOW);

    vr::EVRInitError err=vr::VRInitError_None;
    g_vr=vr::VR_Init(&err,vr::VRApplication_Scene);
    if(err!=vr::VRInitError_None || !g_vr) {
        MessageBoxA(nullptr,vr::VR_GetVRInitErrorAsEnglishDescription(err),"OpenVR init failed",MB_ICONERROR);
        return 1;
    }
    g_comp=vr::VRCompositor();
    if(!g_comp) {
        MessageBoxA(nullptr,"SteamVR compositor unavailable.","VR Snellen",MB_ICONERROR);
        Cleanup(); return 2;
    }
    if(!InitD3D()) {
        MessageBoxA(nullptr,"Direct3D 11 initialization failed.","VR Snellen",MB_ICONERROR);
        Cleanup(); return 3;
    }

    bool quit=false;
    vr::TrackedDevicePose_t poses[vr::k_unMaxTrackedDeviceCount]{};

    while(!quit) {
        MSG msg;
        while(PeekMessage(&msg,nullptr,0,0,PM_REMOVE)) {
            if(msg.message==WM_QUIT) quit=true;
            TranslateMessage(&msg);
            DispatchMessage(&msg);
        }
        if(quit) break;

        g_comp->WaitGetPoses(poses,vr::k_unMaxTrackedDeviceCount,nullptr,0);

        // Poll every frame. If SteamVR changes the recommended per-eye target
        // while this app is running, recreate both eye buffers immediately.
        if(!EnsureSteamVRRenderTargetSize()) continue;

        RenderEye(0,vr::Eye_Left);
        RenderEye(1,vr::Eye_Right);

        vr::Texture_t lt={(void*)g_eye[0].submitTex,vr::TextureType_DirectX,vr::ColorSpace_Gamma};
        vr::Texture_t rt={(void*)g_eye[1].submitTex,vr::TextureType_DirectX,vr::ColorSpace_Gamma};
        g_comp->Submit(vr::Eye_Left,&lt);
        g_comp->Submit(vr::Eye_Right,&rt);
        g_comp->PostPresentHandoff();
    }

    Cleanup();
    return 0;
}
