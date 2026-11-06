"""Windows Job Object containment using creation-time assignment only.

This module provides the Windows owner used by ValidationService. Windows 10 / Server 2016
or newer is required for PROC_THREAD_ATTRIBUTE_JOB_LIST. No child is launched
if creation-time Job assignment cannot be established.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any, Sequence

# Win32 constants.
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1
_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
_CREATE_NO_WINDOW = 0x08000000
_STARTF_USESTDHANDLES = 0x00000100
_PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_PROC_THREAD_ATTRIBUTE_JOB_LIST = 0x0002000D
_ERROR_INSUFFICIENT_BUFFER = 122
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 258
_INFINITE = 0xFFFFFFFF


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_int64),
        ("TotalKernelTime", ctypes.c_int64),
        ("ThisPeriodTotalUserTime", ctypes.c_int64),
        ("ThisPeriodTotalKernelTime", ctypes.c_int64),
        ("TotalPageFaultCount", wintypes.DWORD),
        ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD),
        ("TotalTerminatedProcesses", wintypes.DWORD),
    ]


class _SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    ]


class _STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [("StartupInfo", _STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]


@dataclass
class _WinAPI:
    kernel32: Any
    CreateJobObjectW: Any
    SetInformationJobObject: Any
    InitializeProcThreadAttributeList: Any
    UpdateProcThreadAttribute: Any
    DeleteProcThreadAttributeList: Any
    CreateProcessW: Any
    CloseHandle: Any
    WaitForSingleObject: Any
    GetExitCodeProcess: Any
    QueryInformationJobObject: Any
    TerminateJobObject: Any
    CreateFileW: Any
    OpenProcess: Any
    IsProcessInJob: Any


def _load_api() -> _WinAPI:
    if os.name != "nt":
        raise OSError("Windows Job Object validation containment is unavailable on this platform")
    try:
        kernel32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
    except (AttributeError, OSError) as exc:
        raise OSError("Required Windows Job Object APIs are unavailable; validation is disabled") from exc
    CreateJobObjectW = kernel32.CreateJobObjectW
    CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    CreateJobObjectW.restype = wintypes.HANDLE
    SetInformationJobObject = kernel32.SetInformationJobObject
    SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    SetInformationJobObject.restype = wintypes.BOOL
    InitializeProcThreadAttributeList = kernel32.InitializeProcThreadAttributeList
    InitializeProcThreadAttributeList.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    InitializeProcThreadAttributeList.restype = wintypes.BOOL
    UpdateProcThreadAttribute = kernel32.UpdateProcThreadAttribute
    UpdateProcThreadAttribute.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    UpdateProcThreadAttribute.restype = wintypes.BOOL
    DeleteProcThreadAttributeList = kernel32.DeleteProcThreadAttributeList
    DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
    DeleteProcThreadAttributeList.restype = None
    CreateProcessW = kernel32.CreateProcessW
    CreateProcessW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        ctypes.POINTER(_STARTUPINFOW),
        ctypes.POINTER(_PROCESS_INFORMATION),
    ]
    CreateProcessW.restype = wintypes.BOOL
    CloseHandle = kernel32.CloseHandle
    CloseHandle.argtypes = [wintypes.HANDLE]
    CloseHandle.restype = wintypes.BOOL
    WaitForSingleObject = kernel32.WaitForSingleObject
    WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    WaitForSingleObject.restype = wintypes.DWORD
    GetExitCodeProcess = kernel32.GetExitCodeProcess
    GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    GetExitCodeProcess.restype = wintypes.BOOL
    QueryInformationJobObject = kernel32.QueryInformationJobObject
    QueryInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    QueryInformationJobObject.restype = wintypes.BOOL
    TerminateJobObject = kernel32.TerminateJobObject
    TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    TerminateJobObject.restype = wintypes.BOOL
    CreateFileW = kernel32.CreateFileW
    CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(_SECURITY_ATTRIBUTES),
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    CreateFileW.restype = wintypes.HANDLE
    OpenProcess = kernel32.OpenProcess
    OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    OpenProcess.restype = wintypes.HANDLE
    IsProcessInJob = kernel32.IsProcessInJob
    IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    IsProcessInJob.restype = wintypes.BOOL
    return _WinAPI(
        kernel32,
        CreateJobObjectW,
        SetInformationJobObject,
        InitializeProcThreadAttributeList,
        UpdateProcThreadAttribute,
        DeleteProcThreadAttributeList,
        CreateProcessW,
        CloseHandle,
        WaitForSingleObject,
        GetExitCodeProcess,
        QueryInformationJobObject,
        TerminateJobObject,
        CreateFileW,
        OpenProcess,
        IsProcessInJob,
    )


def _raise_last_error(operation: str) -> OSError:
    try:
        error = getattr(ctypes, "get_last_error")()
    except AttributeError:  # Allows fake-API tests on non-Windows hosts.
        error = 0
    return OSError(error, f"{operation} failed; validation launch/containment is unavailable")


class WindowsJobOwner:
    """Owns one Job and helper process handle; callers must close this owner.

    The thread handle is closed immediately on successful process creation.
    The Job handle is non-inheritable and retained through Job accounting and
    termination. A true `terminate_tree` result means ActiveProcesses reached
    zero before timeout; false means cleanup is unconfirmed.
    """

    def __init__(self, api: _WinAPI, job_handle: int, process_handle: int) -> None:
        self._api = api
        self._job_handle: int | None = job_handle
        self._process_handle: int | None = process_handle
        self._helper_exit_code: int | None = None
        self._helper_exited = False
        self._termination_confirmed = False
        self._closed = False

    @classmethod
    def launch(cls, argv: Sequence[str]) -> "WindowsJobOwner":
        try:
            api = _load_api()
        except (AttributeError, OSError) as exc:
            raise OSError("Required Windows Job Object APIs are unavailable; validation is disabled") from exc
        if not argv:
            raise ValueError("Validation command must not be empty")
        job = api.CreateJobObjectW(None, None)
        if not job:
            raise _raise_last_error("CreateJobObjectW")
        job_value = int(job)
        attr_buffer: ctypes.Array[ctypes.c_char] | None = None
        attributes: ctypes.c_void_p | None = None
        attribute_list_initialized = False
        process_handle: int | None = None
        thread_handle: int | None = None
        stdio_handles: list[int] = []
        try:
            # CreateJobObjectW(NULL, NULL) creates a non-inheritable handle.
            limits = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not api.SetInformationJobObject(
                job, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(limits), ctypes.sizeof(limits)
            ):
                raise _raise_last_error("SetInformationJobObject(KILL_ON_JOB_CLOSE)")

            # CREATE_NO_WINDOW suppresses a console window for console helpers.
            # Use NUL stdio (matching DEVNULL semantics) through a restricted
            # HANDLE_LIST: bInheritHandles=True is safe because only these three
            # inheritable NUL handles are eligible for inheritance. The Job handle
            # itself stays non-inheritable. API contracts:
            # https://learn.microsoft.com/windows/win32/procthread/process-creation-flags
            # https://learn.microsoft.com/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute
            security = _SECURITY_ATTRIBUTES(ctypes.sizeof(_SECURITY_ATTRIBUTES), None, True)
            null_in = api.CreateFileW(
                "NUL",
                _GENERIC_READ,
                _FILE_SHARE_READ | _FILE_SHARE_WRITE,
                ctypes.byref(security),
                _OPEN_EXISTING,
                _FILE_ATTRIBUTE_NORMAL,
                None,
            )
            if not null_in or int(null_in) == ctypes.c_void_p(-1).value:
                raise _raise_last_error("CreateFileW(NUL stdin)")
            stdio_handles.append(int(null_in))
            for stream_name in ("stdout", "stderr"):
                null_out = api.CreateFileW(
                    "NUL",
                    _GENERIC_WRITE,
                    _FILE_SHARE_READ | _FILE_SHARE_WRITE,
                    ctypes.byref(security),
                    _OPEN_EXISTING,
                    _FILE_ATTRIBUTE_NORMAL,
                    None,
                )
                if not null_out or int(null_out) == ctypes.c_void_p(-1).value:
                    raise _raise_last_error(f"CreateFileW(NUL {stream_name})")
                stdio_handles.append(int(null_out))

            required = ctypes.c_size_t(0)
            getattr(ctypes, "set_last_error")(0)
            api.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(required))
            if not required.value:
                error = getattr(ctypes, "get_last_error")()
                if error != _ERROR_INSUFFICIENT_BUFFER:
                    raise OSError(error, "PROC_THREAD_ATTRIBUTE_JOB_LIST is unsupported")
            attr_buffer = ctypes.create_string_buffer(required.value)
            attributes = ctypes.cast(attr_buffer, ctypes.c_void_p)
            if not api.InitializeProcThreadAttributeList(attributes, 2, 0, ctypes.byref(required)):
                raise _raise_last_error("InitializeProcThreadAttributeList")
            attribute_list_initialized = True

            job_array = (wintypes.HANDLE * 1)(wintypes.HANDLE(job_value))
            getattr(ctypes, "set_last_error")(0)
            if not api.UpdateProcThreadAttribute(
                attributes,
                0,
                _PROC_THREAD_ATTRIBUTE_JOB_LIST,
                ctypes.cast(job_array, ctypes.c_void_p),
                ctypes.sizeof(job_array),
                None,
                None,
            ):
                raise _raise_last_error("UpdateProcThreadAttribute(JOB_LIST)")

            handle_list = (wintypes.HANDLE * len(stdio_handles))(*(wintypes.HANDLE(h) for h in stdio_handles))
            if not api.UpdateProcThreadAttribute(
                attributes,
                0,
                _PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                ctypes.cast(handle_list, ctypes.c_void_p),
                ctypes.sizeof(handle_list),
                None,
                None,
            ):
                raise _raise_last_error("UpdateProcThreadAttribute(HANDLE_LIST)")

            startup = _STARTUPINFOEXW()
            startup.StartupInfo.cb = ctypes.sizeof(_STARTUPINFOEXW)
            startup.StartupInfo.dwFlags = _STARTF_USESTDHANDLES
            startup.StartupInfo.hStdInput = stdio_handles[0]
            startup.StartupInfo.hStdOutput = stdio_handles[1]
            startup.StartupInfo.hStdError = stdio_handles[2]
            startup.lpAttributeList = attributes
            command = ctypes.create_unicode_buffer(subprocess.list2cmdline(list(argv)))
            process_info = _PROCESS_INFORMATION()
            created = api.CreateProcessW(
                str(argv[0]),
                command,
                None,
                None,
                True,
                _EXTENDED_STARTUPINFO_PRESENT | _CREATE_NO_WINDOW,
                None,
                None,
                ctypes.cast(ctypes.byref(startup), ctypes.POINTER(_STARTUPINFOW)),
                ctypes.byref(process_info),
            )
            if not created:
                raise _raise_last_error("CreateProcessW with creation-time Job assignment")
            process_handle = int(process_info.hProcess)
            thread_handle = int(process_info.hThread)
            if not api.CloseHandle(thread_handle):
                raise _raise_last_error("CloseHandle(primary thread)")
            thread_handle = None
            while stdio_handles:
                if not api.CloseHandle(stdio_handles[0]):
                    raise _raise_last_error("CloseHandle(parent NUL stdio)")
                stdio_handles.pop(0)
            return cls(api, job_value, process_handle)
        except BaseException:
            if thread_handle:
                api.CloseHandle(thread_handle)
            if process_handle:
                api.CloseHandle(process_handle)
            for handle in stdio_handles:
                api.CloseHandle(handle)
            if job:
                api.CloseHandle(job)
            raise
        finally:
            if attribute_list_initialized and attributes is not None:
                api.DeleteProcThreadAttributeList(attributes)

    def _record_helper_exit(self, timeout_ms: int) -> bool:
        if self._helper_exited:
            return True
        if self._process_handle is None:
            raise OSError("Helper process handle is unavailable before exit observation")
        wait_result = self._api.WaitForSingleObject(self._process_handle, timeout_ms)
        if wait_result == _WAIT_TIMEOUT:
            return False
        if wait_result != _WAIT_OBJECT_0:
            raise _raise_last_error("WaitForSingleObject(helper)")
        code = wintypes.DWORD()
        if not self._api.GetExitCodeProcess(self._process_handle, ctypes.byref(code)):
            raise _raise_last_error("GetExitCodeProcess(helper)")
        if not self._api.CloseHandle(self._process_handle):
            raise _raise_last_error("CloseHandle(helper process)")
        self._helper_exit_code = int(code.value)
        self._helper_exited = True
        self._process_handle = None
        return True

    def poll_helper(self) -> int | None:
        """Nonblocking helper-exit observation; closes its handle when exited."""
        if self._helper_exited:
            return self._helper_exit_code
        if self._process_handle is None:
            raise RuntimeError("Helper process handle is unavailable before exit observation")
        if not self._record_helper_exit(0):
            return None
        return self._helper_exit_code

    def active_processes(self) -> int:
        """Return Job ActiveProcesses or raise; does not infer helper exit."""
        if self._job_handle is None:
            raise RuntimeError("Job handle is closed")
        info = _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
        if not self._api.QueryInformationJobObject(
            self._job_handle, _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION, ctypes.byref(info), ctypes.sizeof(info), None
        ):
            raise _raise_last_error("QueryInformationJobObject")
        return int(info.ActiveProcesses)

    def _wait_helper_until(self, deadline: float) -> bool:
        if self._helper_exited:
            return True
        if self._process_handle is None:
            return False
        remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
        return self._record_helper_exit(remaining_ms)

    def _wait_job_empty_until(self, deadline: float) -> bool:
        if self._job_handle is None or not self._helper_exited:
            return False
        while True:
            try:
                if self.active_processes() == 0:
                    self._termination_confirmed = True
                    return True
            except OSError:
                return False
            if time.monotonic() >= deadline:
                return False
            time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))

    def terminate_job(self, timeout: float = 0.5) -> bool:
        """Terminate Job and confirm helper exit/handle close, without Job query.

        This split phase lets callers release any test/observer process handles
        before querying ActiveProcesses, which can otherwise lag process exit.
        """
        if self._job_handle is None:
            return False
        if not self._api.TerminateJobObject(self._job_handle, 1):
            return False
        return self._wait_helper_until(time.monotonic() + max(0.0, timeout))

    def wait_for_empty(self, timeout: float = 0.5) -> bool:
        """Confirm zero Job members after helper exit and process-handle closure."""
        return self._wait_job_empty_until(time.monotonic() + max(0.0, timeout))

    def terminate_tree(self, timeout: float = 0.5) -> bool:
        """Terminate the Job and confirm helper exit then zero Job members.

        Helper wait and Job accounting share one finite deadline.
        """
        if self._job_handle is None:
            return self._termination_confirmed
        if not self._api.TerminateJobObject(self._job_handle, 1):
            return False
        deadline = time.monotonic() + max(0.0, timeout)
        try:
            if not self._wait_helper_until(deadline):
                return False
        except OSError:
            return False
        return self._wait_job_empty_until(deadline)

    def close(self, timeout: float = 0.5) -> bool:
        """Bounded explicit cleanup; return false when descendant exit is unconfirmed.

        If confirmation times out, closing the last Job handle still invokes
        KILL_ON_JOB_CLOSE, but the returned false accurately records that cleanup
        was not observed to completion before handle closure.
        """
        if self._closed:
            return self._termination_confirmed
        if self._job_handle is None:
            # A prior timeout may have closed the Job to trigger kill-on-close;
            # retain/reap the helper handle finitely but never upgrade to confirmed.
            if self._process_handle is not None:
                try:
                    self._record_helper_exit(max(0, int(max(0.0, timeout) * 1000)))
                except OSError:
                    # Keep the process handle owned for a later bounded retry.
                    return False
            self._closed = self._process_handle is None
            return False
        confirmed = self._termination_confirmed or self.terminate_tree(timeout)
        if self._job_handle is not None:
            if self._api.CloseHandle(self._job_handle):
                self._job_handle = None
            else:
                confirmed = False
        self._closed = self._job_handle is None and self._process_handle is None
        self._termination_confirmed = confirmed
        return confirmed


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]
