// Regression tests for existing v0.1 settings, stable v0.3 defaults,
// UI events, and never persisting opt-in GPU timing across sessions.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <uevr/API.h>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>
#include <unordered_map>
static UEVR_OnCustomEventCb custom{};
static UEVR_OnPresentCb present{};
static std::wstring basePath;
static std::unordered_map<std::string,std::string> fields;
static bool setCustom(UEVR_OnCustomEventCb cb){custom=cb;return true;}
static bool setPresent(UEVR_OnPresentCb cb){present=cb;return true;}
static bool setReset(UEVR_OnDeviceResetCb){return true;}
static void logger(const char*,...) {}
static void event(const char* name,const char* payload){
    if(!name || std::strcmp(name,"glamayre_sharpen.status") || !payload)return;
    fields.clear();
    const char* p=payload;
    while(*p){
        const char* e=std::strchr(p,';');
        std::string pair(p,e?size_t(e-p):std::strlen(p));
        const size_t sep=pair.find('=');
        if(sep!=std::string::npos)fields[pair.substr(0,sep)]=pair.substr(sep+1);
        if(!e)break;
        p=e+1;
    }
}
static unsigned persistent(wchar_t* buffer,unsigned size){
    if(!buffer||!size)return unsigned(basePath.size()+1);
    if(size<basePath.size()+1)return unsigned(basePath.size()+1);
    std::wcscpy(buffer,basePath.c_str());
    return unsigned(basePath.size()+1);
}
static bool approx(const char* key,float v){
    auto i=fields.find(key);
    return i!=fields.end()&&std::abs(std::strtof(i->second.c_str(),nullptr)-v)<0.001f;
}
int main(int argc,char** argv){
    if(argc!=2)return 2;
    const std::string scenario=argv[1];
    wchar_t temp[MAX_PATH]{};
    DWORD n=GetTempPathW(MAX_PATH,temp);
    if(!n || n>=MAX_PATH)return 3;
    basePath=temp;
    basePath+=L"GlamayreSettingsAudit_";
    basePath+=std::to_wstring(GetCurrentProcessId());
    basePath+=L"_";
    basePath+=std::wstring(scenario.begin(),scenario.end());
    if(!CreateDirectoryW(basePath.c_str(),nullptr)&&GetLastError()!=ERROR_ALREADY_EXISTS)return 4;
    const std::wstring ini=basePath+L"\\GlamaryeUEVR.ini";
    DeleteFileW(ini.c_str());
    auto save=[&](const wchar_t* key,const wchar_t* value){
        if(!WritePrivateProfileStringW(L"Sharpen",key,value,ini.c_str())) {
            fprintf(stderr,"Failed writing ini value\n");std::exit(5);
        }
    };
    if(scenario=="old_big") {
        save(L"Enabled",L"1");save(L"Bigger",L"1");save(L"Strength",L"1.375");
    } else if(scenario=="old_small") {
        save(L"Enabled",L"1");save(L"Bigger",L"0");save(L"Strength",L"0.850");
    } else if(scenario=="explicit") {
        save(L"Enabled",L"1");save(L"SmallStrength",L"1.000");
        save(L"BigStrength",L"2.000");save(L"ExtraStrength",L"3.000");
        save(L"UltraStrength",L"4.000");save(L"ThinLineProtection",L"0.35");
    } else if(scenario=="timing_saved") {
        save(L"GpuTiming",L"1");save(L"Enabled",L"1");save(L"BigStrength",L"0.8");
    } else if(scenario!="fresh"&&scenario!="ui_events")return 6;
    UEVR_PluginCallbacks cb{};
    cb.on_custom_event=setCustom;
    cb.on_present=setPresent;
    cb.on_device_reset=setReset;
    UEVR_PluginFunctions fun{};
    fun.get_persistent_dir=persistent;
    fun.dispatch_lua_event=event;
    fun.log_info=logger;fun.log_error=logger;fun.log_warn=logger;
    UEVR_PluginVersion version{UEVR_PLUGIN_VERSION_MAJOR,UEVR_PLUGIN_VERSION_MINOR,UEVR_PLUGIN_VERSION_PATCH};
    UEVR_RendererData render{};
    render.renderer_type=UEVR_RENDERER_D3D12;
    UEVR_PluginInitializeParam host{};
    host.version=&version;host.callbacks=&cb;host.functions=&fun;host.renderer=&render;
    HMODULE dll=LoadLibraryW(L"GlamaryeSharpenUEVR.dll");
    if(!dll){fprintf(stderr,"Could not load production plugin\n");return 7;}
    using Init=bool(*)(const UEVR_PluginInitializeParam*);
    auto init=reinterpret_cast<Init>(GetProcAddress(dll,"uevr_plugin_initialize"));
    if(!init || !init(&host) || !custom || !present){
        fprintf(stderr,"Plugin init failed\n");return 8;
    }
    present();
    bool ok=fields.count("small") && fields.count("bigStrength") &&
            fields.count("extra") && fields.count("ultra") &&
            fields.count("thin") && fields.count("timing");
    if(!ok){fprintf(stderr,"Missing required fields in plugin status\n");return 9;}
    if(scenario=="fresh"||scenario=="ui_events") {
        ok=approx("small",0)&&approx("bigStrength",0.4)&&
           approx("extra",0)&&approx("ultra",0)&&approx("thin",0)&&approx("timing",0);
    } else if(scenario=="old_big"){
        ok=approx("small",0)&&approx("bigStrength",1.375)&&approx("extra",0)&&
            approx("ultra",0)&&approx("thin",0);
    }else if(scenario=="old_small"){
        ok=approx("small",0.85)&&approx("bigStrength",0)&&approx("extra",0)&&
            approx("ultra",0)&&approx("thin",0);
    }else if(scenario=="explicit"){
        ok=approx("small",1)&&approx("bigStrength",2)&&approx("extra",3)&&
            approx("ultra",4)&&approx("thin",0.35);
    }else if(scenario=="timing_saved"){
        ok=approx("timing",0)&&approx("bigStrength",0.8);
    }
    if(!ok){fprintf(stderr,"Unexpected loaded settings in case %s\n",scenario.c_str());return 10;}
    if(scenario=="ui_events"){
        const char* settings[]={"small=5","bigStrength=4","extra=3","ultra=2",
           "thin=0.6","edges=0","timing=1"};
        for(auto* value:settings)custom("glamayre_sharpen.set",value);
        // Force status without an actual game loop.
        Sleep(430);present();
        ok=approx("small",5)&&approx("bigStrength",4)&&approx("extra",3)&&
           approx("ultra",2)&&approx("thin",0.6)&&approx("edges",0)&&approx("timing",1);
        if(!ok){fprintf(stderr,"Native settings callback did not apply changes\n");return 11;}
        wchar_t buf[64]{};
        GetPrivateProfileStringW(L"Sharpen",L"UltraStrength",L"not_saved",buf,64,ini.c_str());
        ok=std::wcstof(buf,nullptr)>1.99f;
        GetPrivateProfileStringW(L"Sharpen",L"GpuTiming",L"not_saved",buf,64,ini.c_str());
        ok=ok && std::wcscmp(buf,L"not_saved")==0;
        if(!ok){fprintf(stderr,"Settings were not saved or timing unexpectedly persisted\n");return 12;}
    }
    printf("PASS config regression: %s\n",scenario.c_str());
    DeleteFileW(ini.c_str());
    RemoveDirectoryW(basePath.c_str());
    return 0;
}
