#define UNICODE
#define _UNICODE
#define NOMINMAX

#include <windows.h>
#include <shellapi.h>
#include <tlhelp32.h>

#include <algorithm>
#include <cstring>
#include <limits>
#include <set>
#include <string>
#include <vector>

namespace
{
constexpr wchar_t kDefaultGameDirectory[] = L"E:\\Games\\Steam\\steamapps\\common\\SkyrimVR";
constexpr wchar_t kDefaultLogPath[] = L"E:\\MGO-RC3-clean\\logs\\DLSS5-SKSE-Bridge.log";
constexpr wchar_t kDefaultUsvfsPath[] = L"E:\\MGO-RC3-clean\\usvfs_x64.dll";
constexpr wchar_t kSkseSteamLoaderName[] = L"sksevr_steam_loader.dll";

std::wstring GetOption(const std::vector<std::wstring>& args, const wchar_t* name)
{
    for (size_t i = 0; i + 1 < args.size(); ++i)
    {
        if (_wcsicmp(args[i].c_str(), name) == 0)
        {
            return args[i + 1];
        }
    }
    return {};
}

std::string Utf8(const std::wstring& value)
{
    if (value.empty())
    {
        return {};
    }

    const int size = WideCharToMultiByte(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), nullptr, 0, nullptr, nullptr);
    if (size <= 0)
    {
        return {};
    }

    std::string result(static_cast<size_t>(size), '\0');
    WideCharToMultiByte(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), result.data(), size, nullptr, nullptr);
    return result;
}

void Log(const std::wstring& path, const std::wstring& message)
{
    const std::string line = Utf8(L"[" + std::to_wstring(GetTickCount64()) + L"] " + message + L"\r\n");
    HANDLE file = CreateFileW(path.c_str(), FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE)
    {
        return;
    }

    DWORD written = 0;
    WriteFile(file, line.data(), static_cast<DWORD>(line.size()), &written, nullptr);
    CloseHandle(file);
}

bool IsSamePath(const std::wstring& left, const std::wstring& right)
{
    std::wstring leftCopy = left;
    std::wstring rightCopy = right;
    std::replace(leftCopy.begin(), leftCopy.end(), L'/', L'\\');
    std::replace(rightCopy.begin(), rightCopy.end(), L'/', L'\\');
    std::transform(leftCopy.begin(), leftCopy.end(), leftCopy.begin(), towlower);
    std::transform(rightCopy.begin(), rightCopy.end(), rightCopy.begin(), towlower);
    return leftCopy == rightCopy;
}

std::set<DWORD> ExistingGameProcesses()
{
    std::set<DWORD> result;
    HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snapshot == INVALID_HANDLE_VALUE)
    {
        return result;
    }

    PROCESSENTRY32W entry{};
    entry.dwSize = sizeof(entry);
    if (Process32FirstW(snapshot, &entry))
    {
        do
        {
            if (_wcsicmp(entry.szExeFile, L"SkyrimVR.exe") == 0)
            {
                result.insert(entry.th32ProcessID);
            }
        } while (Process32NextW(snapshot, &entry));
    }

    CloseHandle(snapshot);
    return result;
}

HANDLE FindNewGameProcess(const std::wstring& gamePath, const std::set<DWORD>& oldProcesses, DWORD& processId)
{
    HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snapshot == INVALID_HANDLE_VALUE)
    {
        return nullptr;
    }

    HANDLE result = nullptr;
    PROCESSENTRY32W entry{};
    entry.dwSize = sizeof(entry);
    if (Process32FirstW(snapshot, &entry))
    {
        do
        {
            if (_wcsicmp(entry.szExeFile, L"SkyrimVR.exe") != 0 || oldProcesses.contains(entry.th32ProcessID))
            {
                continue;
            }

            HANDLE process = OpenProcess(PROCESS_CREATE_THREAD | PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_OPERATION | PROCESS_VM_WRITE | PROCESS_SUSPEND_RESUME | SYNCHRONIZE, FALSE, entry.th32ProcessID);
            if (process == nullptr)
            {
                continue;
            }

            std::vector<wchar_t> pathBuffer(32768);
            DWORD pathLength = static_cast<DWORD>(pathBuffer.size());
            if (QueryFullProcessImageNameW(process, 0, pathBuffer.data(), &pathLength) &&
                IsSamePath(std::wstring(pathBuffer.data(), pathLength), gamePath))
            {
                processId = entry.th32ProcessID;
                result = process;
                break;
            }

            CloseHandle(process);
        } while (Process32NextW(snapshot, &entry));
    }

    CloseHandle(snapshot);
    return result;
}

ULONGLONG FileTimeValue(const FILETIME& value)
{
    ULARGE_INTEGER result{};
    result.LowPart = value.dwLowDateTime;
    result.HighPart = value.dwHighDateTime;
    return result.QuadPart;
}

bool SuspendPrimaryThread(DWORD processId, HANDLE& suspendedThread, DWORD& detail)
{
    suspendedThread = nullptr;
    detail = 0;

    HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
    if (snapshot == INVALID_HANDLE_VALUE)
    {
        detail = GetLastError();
        return false;
    }

    DWORD selectedThreadId = 0;
    ULONGLONG selectedCreationTime = std::numeric_limits<ULONGLONG>::max();
    THREADENTRY32 entry{};
    entry.dwSize = sizeof(entry);
    if (Thread32First(snapshot, &entry))
    {
        do
        {
            if (entry.th32OwnerProcessID != processId)
            {
                continue;
            }

            HANDLE thread = OpenThread(THREAD_QUERY_INFORMATION | THREAD_SUSPEND_RESUME, FALSE, entry.th32ThreadID);
            if (thread == nullptr)
            {
                continue;
            }

            FILETIME creationTime{}, exitTime{}, kernelTime{}, userTime{};
            const bool validTimes = GetThreadTimes(thread, &creationTime, &exitTime, &kernelTime, &userTime) != FALSE;
            const ULONGLONG threadCreationTime = validTimes ? FileTimeValue(creationTime) : std::numeric_limits<ULONGLONG>::max();
            if (validTimes && (threadCreationTime < selectedCreationTime ||
                (threadCreationTime == selectedCreationTime && entry.th32ThreadID < selectedThreadId)))
            {
                selectedThreadId = entry.th32ThreadID;
                selectedCreationTime = threadCreationTime;
            }
            CloseHandle(thread);
        } while (Thread32Next(snapshot, &entry));
    }
    CloseHandle(snapshot);

    if (selectedThreadId == 0)
    {
        detail = ERROR_NOT_FOUND;
        return false;
    }

    suspendedThread = OpenThread(THREAD_SUSPEND_RESUME, FALSE, selectedThreadId);
    if (suspendedThread == nullptr)
    {
        detail = GetLastError();
        return false;
    }

    if (SuspendThread(suspendedThread) == static_cast<DWORD>(-1))
    {
        detail = GetLastError();
        CloseHandle(suspendedThread);
        suspendedThread = nullptr;
        return false;
    }
    return true;
}

bool ResumePrimaryThread(HANDLE suspendedThread, DWORD& detail)
{
    detail = 0;
    if (suspendedThread == nullptr)
    {
        detail = ERROR_INVALID_HANDLE;
        return false;
    }

    if (ResumeThread(suspendedThread) == static_cast<DWORD>(-1))
    {
        detail = GetLastError();
        return false;
    }
    return true;
}

bool InjectDll(HANDLE process, const std::wstring& dllPath, DWORD& detail, const char* invokeExport = nullptr)
{
    detail = 0;
    HMODULE kernel32 = GetModuleHandleW(L"kernel32.dll");
    const uintptr_t loadLibraryW = kernel32 == nullptr
        ? 0
        : reinterpret_cast<uintptr_t>(GetProcAddress(kernel32, "LoadLibraryW"));
    const uintptr_t getProcAddress = kernel32 == nullptr
        ? 0
        : reinterpret_cast<uintptr_t>(GetProcAddress(kernel32, "GetProcAddress"));
    const bool invokeNamedExport = invokeExport != nullptr;
    if (loadLibraryW == 0 || (invokeNamedExport && getProcAddress == 0))
    {
        detail = GetLastError();
        return false;
    }

    struct RemoteLoaderData
    {
        uintptr_t loadLibraryW;
        uintptr_t getProcAddress;
        wchar_t dllPath[2048];
        char exportName[64];
        unsigned char code[160];
    } data{};
    static_assert(offsetof(RemoteLoaderData, exportName) == 0x1010);

    data.loadLibraryW = loadLibraryW;
    data.getProcAddress = getProcAddress;
    if (dllPath.size() >= (sizeof(data.dllPath) / sizeof(data.dllPath[0])))
    {
        detail = ERROR_FILENAME_EXCED_RANGE;
        return false;
    }
    std::copy(dllPath.begin(), dllPath.end(), std::begin(data.dllPath));
    if (invokeNamedExport)
    {
        const size_t exportLength = std::strlen(invokeExport);
        if (exportLength >= sizeof(data.exportName))
        {
            detail = ERROR_FILENAME_EXCED_RANGE;
            return false;
        }
        std::copy(invokeExport, invokeExport + exportLength + 1, std::begin(data.exportName));
    }

    static constexpr unsigned char kLoadOnlyCode[] =
    {
        0x48, 0x83, 0xEC, 0x28,             // sub rsp, 28h
        0x48, 0x8B, 0xD9,                   // mov rbx, rcx
        0x48, 0x8D, 0x4B, 0x10,             // lea rcx, [rbx+10h]
        0xFF, 0x13,                         // call qword ptr [rbx]
        0x48, 0x83, 0xC4, 0x28,             // add rsp, 28h
        0xC3                                // ret
    };

    // Load the Steam helper and invoke its exported InitSKSESteamLoader entry
    // point by name. The VR helper has a named export; ordinal 1 is not valid.
    static constexpr unsigned char kLoadAndCallNamedExportCode[] =
    {
        0x48, 0x83, 0xEC, 0x28,             // sub rsp, 28h
        0x48, 0x8B, 0xD9,                   // mov rbx, rcx
        0x48, 0x8D, 0x4B, 0x10,             // lea rcx, [rbx+10h]
        0xFF, 0x13,                         // call qword ptr [rbx]
        0x48, 0x85, 0xC0,                   // test rax, rax
        0x74, 0x1B,                         // je failure
        0x48, 0x8B, 0xC8,                   // mov rcx, rax
        0x48, 0x8D, 0x93, 0x10, 0x10, 0x00, 0x00, // lea rdx, [rbx+1010h]
        0xFF, 0x53, 0x08,                   // call qword ptr [rbx+8]
        0x48, 0x85, 0xC0,                   // test rax, rax
        0x74, 0x09,                         // je failure
        0xFF, 0xD0,                         // call rax
        0xB8, 0x01, 0x00, 0x00, 0x00,       // mov eax, 1
        0xEB, 0x02,                         // jmp done
        0x33, 0xC0,                         // failure: xor eax, eax
        0x48, 0x83, 0xC4, 0x28,             // add rsp, 28h
        0xC3                                // ret
    };
    const unsigned char* code = invokeNamedExport ? kLoadAndCallNamedExportCode : kLoadOnlyCode;
    const size_t codeSize = invokeNamedExport
        ? sizeof(kLoadAndCallNamedExportCode)
        : sizeof(kLoadOnlyCode);
    std::copy(code, code + codeSize, std::begin(data.code));

    const SIZE_T dataBytes = sizeof(data);
    void* remoteData = VirtualAllocEx(process, nullptr, dataBytes, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (remoteData == nullptr)
    {
        detail = GetLastError();
        return false;
    }

    SIZE_T bytesWritten = 0;
    if (!WriteProcessMemory(process, remoteData, &data, dataBytes, &bytesWritten) || bytesWritten != dataBytes)
    {
        detail = GetLastError();
        VirtualFreeEx(process, remoteData, 0, MEM_RELEASE);
        return false;
    }

    auto remoteCode = reinterpret_cast<LPTHREAD_START_ROUTINE>(reinterpret_cast<unsigned char*>(remoteData) + offsetof(RemoteLoaderData, code));

    HANDLE thread = CreateRemoteThread(process, nullptr, 0, remoteCode, remoteData, 0, nullptr);
    if (thread == nullptr)
    {
        detail = GetLastError();
        VirtualFreeEx(process, remoteData, 0, MEM_RELEASE);
        return false;
    }

    const DWORD waitResult = WaitForSingleObject(thread, 5000);
    if (waitResult == WAIT_OBJECT_0)
    {
        DWORD threadResult = 0;
        GetExitCodeThread(thread, &threadResult);
        if (threadResult == 0)
        {
            detail = invokeNamedExport ? ERROR_PROC_NOT_FOUND : ERROR_DLL_INIT_FAILED;
        }
    }
    else
    {
        detail = waitResult == WAIT_TIMEOUT ? ERROR_TIMEOUT : GetLastError();
    }

    CloseHandle(thread);
    VirtualFreeEx(process, remoteData, 0, MEM_RELEASE);
    return waitResult == WAIT_OBJECT_0 && detail == 0;
}

bool InjectIntoRunningSteam(const std::wstring& dllPath, const std::wstring& logPath)
{
    HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snapshot == INVALID_HANDLE_VALUE)
    {
        Log(logPath, L"WARNING: could not enumerate processes before Steam VFS injection. win32=" + std::to_wstring(GetLastError()));
        return false;
    }

    bool found = false;
    bool injectedAny = false;
    PROCESSENTRY32W entry{};
    entry.dwSize = sizeof(entry);
    if (Process32FirstW(snapshot, &entry))
    {
        do
        {
            if (_wcsicmp(entry.szExeFile, L"steam.exe") != 0)
            {
                continue;
            }

            HANDLE process = OpenProcess(PROCESS_CREATE_THREAD | PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_OPERATION | PROCESS_VM_WRITE | SYNCHRONIZE, FALSE, entry.th32ProcessID);
            if (process == nullptr)
            {
                continue;
            }

            std::vector<wchar_t> pathBuffer(32768);
            DWORD pathLength = static_cast<DWORD>(pathBuffer.size());
            const bool pathMatches = QueryFullProcessImageNameW(process, 0, pathBuffer.data(), &pathLength);
            if (!pathMatches)
            {
                CloseHandle(process);
                continue;
            }

            found = true;
            DWORD detail = 0;
            const bool injected = InjectDll(process, dllPath, detail);
            if (injected)
            {
                Log(logPath, L"USVFS injected into running Steam client. pid=" + std::to_wstring(entry.th32ProcessID));
                injectedAny = true;
            }
            else
            {
                Log(logPath, L"WARNING: USVFS injection into running Steam client failed. pid=" + std::to_wstring(entry.th32ProcessID) + L"; win32=" + std::to_wstring(detail));
            }
            CloseHandle(process);
        } while (Process32NextW(snapshot, &entry));
    }

    CloseHandle(snapshot);
    if (!found)
    {
        Log(logPath, L"WARNING: running Steam client was not found; successor VFS propagation was not pre-seeded.");
    }
    return injectedAny;
}

int Run(const std::vector<std::wstring>& args)
{
    const std::wstring gameDirectory = GetOption(args, L"--game-dir").empty()
        ? kDefaultGameDirectory
        : GetOption(args, L"--game-dir");
    const std::wstring logPath = GetOption(args, L"--log").empty()
        ? kDefaultLogPath
        : GetOption(args, L"--log");
    const std::wstring usvfsPath = GetOption(args, L"--usvfs").empty()
        ? kDefaultUsvfsPath
        : GetOption(args, L"--usvfs");
    const std::wstring gamePath = gameDirectory + L"\\SkyrimVR.exe";
    const std::wstring loaderPath = gameDirectory + L"\\sksevr_loader.exe";
    const std::wstring skseSteamLoaderPath = gameDirectory + L"\\" + kSkseSteamLoaderName;

    Log(logPath, L"Native bridge starting. gameDir=" + gameDirectory);
    if (GetFileAttributesW(loaderPath.c_str()) == INVALID_FILE_ATTRIBUTES)
    {
        Log(logPath, L"ERROR: SKSE loader is missing: " + loaderPath);
        return 2;
    }
    if (GetFileAttributesW(gamePath.c_str()) == INVALID_FILE_ATTRIBUTES)
    {
        Log(logPath, L"ERROR: SkyrimVR.exe is missing: " + gamePath);
        return 3;
    }
    if (GetFileAttributesW(skseSteamLoaderPath.c_str()) == INVALID_FILE_ATTRIBUTES)
    {
        Log(logPath, L"ERROR: SKSE Steam loader is missing: " + skseSteamLoaderPath);
        return 4;
    }
    if (GetFileAttributesW(usvfsPath.c_str()) == INVALID_FILE_ATTRIBUTES)
    {
        Log(logPath, L"ERROR: USVFS library is missing: " + usvfsPath);
        return 5;
    }

    // Steam is normally already running outside MO2's child-process boundary.
    // Seed the MO2 VFS hook in that client before SKSE starts so the real
    // Skyrim successor inherits the virtual plugin tree early enough for the
    // SKSE preloader and Community Shaders to see it.
    InjectIntoRunningSteam(usvfsPath, logPath);

    // Keep the Steam identity on the loader and every child it creates.
    SetEnvironmentVariableW(L"SteamGameId", L"611670");
    SetEnvironmentVariableW(L"SteamAppID", L"611670");

    const std::set<DWORD> existingProcesses = ExistingGameProcesses();
    STARTUPINFOW loaderStartup{};
    loaderStartup.cb = sizeof(loaderStartup);
    PROCESS_INFORMATION loaderProcess{};
    // This is the handoff mode used by the known-good MGO launch.  Steam is
    // seeded above, so the successor retains MO2's VFS while SKSE performs
    // its normal VR Steam handoff.
    const std::wstring loaderCommand = L"\"" + loaderPath + L"\" -forcesteamloader";
    std::vector<wchar_t> loaderCommandLine(loaderCommand.begin(), loaderCommand.end());
    loaderCommandLine.push_back(L'\0');

    Log(logPath, L"Starting SKSE loader with -forcesteamloader: " + loaderPath);
    if (!CreateProcessW(loaderPath.c_str(), loaderCommandLine.data(), nullptr, nullptr, FALSE, CREATE_NO_WINDOW, nullptr, gameDirectory.c_str(), &loaderStartup, &loaderProcess))
    {
        Log(logPath, L"ERROR: CreateProcessW failed for SKSE loader. win32=" + std::to_wstring(GetLastError()));
        return 6;
    }
    CloseHandle(loaderProcess.hThread);
    Log(logPath, L"SKSE loader started. pid=" + std::to_wstring(loaderProcess.dwProcessId));

    std::set<DWORD> seenProcesses = existingProcesses;
    const ULONGLONG deadline = GetTickCount64() + 120000;
    unsigned int candidateNumber = 0;
    while (GetTickCount64() < deadline)
    {
        DWORD processId = 0;
        HANDLE gameProcess = FindNewGameProcess(gamePath, seenProcesses, processId);
        if (gameProcess == nullptr)
        {
            // Keep polling while SKSE performs its Steam handoff.
            Sleep(25);
            continue;
        }

        seenProcesses.insert(processId);
        ++candidateNumber;
        Log(logPath, L"SkyrimVR candidate observed. pid=" + std::to_wstring(processId) + L"; validating handoff.");

        DWORD injectionDetail = 0;
        if (!InjectDll(gameProcess, usvfsPath, injectionDetail))
        {
            Log(logPath, L"WARNING: USVFS injection failed for SkyrimVR candidate. pid=" + std::to_wstring(processId) + L"; win32=" + std::to_wstring(injectionDetail));
        }
        else
        {
            Log(logPath, L"USVFS injected into SkyrimVR candidate. pid=" + std::to_wstring(processId));
        }

        // Do not inject sksevr_steam_loader.dll after Skyrim has started.
        // The VR loader's startup hook must run at the supported early
        // handoff boundary; a late remote LoadLibrary can crash the game.
        // Steam was seeded above, so a successor created by Steam inherits
        // USVFS and the loader's normal handoff remains intact.

        const DWORD validationWait = WaitForSingleObject(gameProcess, 8000);
        if (validationWait == WAIT_TIMEOUT)
        {
            Log(logPath, L"SkyrimVR observed. pid=" + std::to_wstring(processId) + L"; bridge will remain alive until it exits.");
            WaitForSingleObject(gameProcess, INFINITE);
            DWORD exitCode = 0;
            GetExitCodeProcess(gameProcess, &exitCode);
            CloseHandle(gameProcess);
            CloseHandle(loaderProcess.hProcess);
            Log(logPath, L"SkyrimVR exited. code=" + std::to_wstring(exitCode));
            return static_cast<int>(exitCode);
        }

        if (validationWait == WAIT_OBJECT_0)
        {
            DWORD exitCode = 0;
            GetExitCodeProcess(gameProcess, &exitCode);
            CloseHandle(gameProcess);
            Log(logPath, L"SkyrimVR candidate exited during validation. pid=" + std::to_wstring(processId) + L"; code=" + std::to_wstring(exitCode));
            if (exitCode == 53 || candidateNumber == 1)
            {
                Log(logPath, L"Ignoring short-lived SkyrimVR handoff candidate; continuing to wait for the successor.");
                continue;
            }

            CloseHandle(loaderProcess.hProcess);
            return static_cast<int>(exitCode);
        }

        CloseHandle(gameProcess);
        CloseHandle(loaderProcess.hProcess);
        Log(logPath, L"ERROR: WaitForSingleObject failed for SkyrimVR candidate. win32=" + std::to_wstring(GetLastError()));
        return 10;
    }

    DWORD loaderExitCode = 0;
    if (GetExitCodeProcess(loaderProcess.hProcess, &loaderExitCode) && loaderExitCode != STILL_ACTIVE)
    {
        Log(logPath, L"SKSE loader exited with code " + std::to_wstring(loaderExitCode) + L" without a stable SkyrimVR handoff.");
    }
    CloseHandle(loaderProcess.hProcess);
    Log(logPath, L"ERROR: SkyrimVR.exe was not observed within 120 seconds.");
    return 11;
}
}

int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR, int)
{
    int argc = 0;
    LPWSTR* argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (argv == nullptr)
    {
        return 10;
    }

    std::vector<std::wstring> args;
    args.reserve(static_cast<size_t>(argc));
    for (int i = 0; i < argc; ++i)
    {
        args.emplace_back(argv[i]);
    }
    LocalFree(argv);

    try
    {
        return Run(args);
    }
    catch (...)
    {
        return 10;
    }
}
