"""Small native Accessibility client for the bridge's RUMlogNG controls.

Uses the app's existing Accessibility permission, without spawning System
Events/osascript for every individual attribute read.
"""

import ctypes as C
import subprocess


CF = C.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
AX = C.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
CG = C.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
PTR = C.c_void_p
INDEX = C.c_long
UTF8 = 0x08000100


def signature(library, name, result, arguments):
    function = getattr(library, name)
    function.restype, function.argtypes = result, arguments
    return function


release = signature(CF, "CFRelease", None, [PTR])
retain = signature(CF, "CFRetain", PTR, [PTR])
type_id = signature(CF, "CFGetTypeID", C.c_ulong, [PTR])
string_type = signature(CF, "CFStringGetTypeID", C.c_ulong, [])()
number_type = signature(CF, "CFNumberGetTypeID", C.c_ulong, [])()
boolean_type = signature(CF, "CFBooleanGetTypeID", C.c_ulong, [])()
array_type = signature(CF, "CFArrayGetTypeID", C.c_ulong, [])()
element_type = signature(AX, "AXUIElementGetTypeID", C.c_ulong, [])()
make_string = signature(CF, "CFStringCreateWithCString", PTR, [PTR, C.c_char_p, C.c_uint32])
string_length = signature(CF, "CFStringGetLength", INDEX, [PTR])
copy_string = signature(CF, "CFStringGetCString", C.c_bool, [PTR, PTR, INDEX, C.c_uint32])
get_number = signature(CF, "CFNumberGetValue", C.c_bool, [PTR, C.c_int, PTR])
make_number = signature(CF, "CFNumberCreate", PTR, [PTR, C.c_int, PTR])
get_boolean = signature(CF, "CFBooleanGetValue", C.c_bool, [PTR])
array_count = signature(CF, "CFArrayGetCount", INDEX, [PTR])
array_value = signature(CF, "CFArrayGetValueAtIndex", PTR, [PTR, INDEX])
make_array = signature(CF, "CFArrayCreate", PTR, [PTR, C.POINTER(PTR), INDEX, PTR])
copy_attribute = signature(AX, "AXUIElementCopyAttributeValue", C.c_int, [PTR, PTR, C.POINTER(PTR)])
copy_attributes = signature(AX, "AXUIElementCopyMultipleAttributeValues", C.c_int, [PTR, PTR, C.c_uint32, C.POINTER(PTR)])
ax_value_type = signature(AX, "AXValueGetTypeID", C.c_ulong, [])()
ax_value_kind = signature(AX, "AXValueGetType", C.c_uint32, [PTR])
ax_value_get = signature(AX, "AXValueGetValue", C.c_bool, [PTR, C.c_uint32, PTR])
set_attribute = signature(AX, "AXUIElementSetAttributeValue", C.c_int, [PTR, PTR, PTR])
perform_action = signature(AX, "AXUIElementPerformAction", C.c_int, [PTR, PTR])
create_application = signature(AX, "AXUIElementCreateApplication", PTR, [C.c_int])
create_system = signature(AX, "AXUIElementCreateSystemWide", PTR, [])
set_timeout = signature(AX, "AXUIElementSetMessagingTimeout", C.c_int, [PTR, C.c_float])
is_trusted = signature(AX, "AXIsProcessTrusted", C.c_bool, [])
copy_session = signature(CG,"CGSessionCopyCurrentDictionary",PTR,[])
dictionary_value = signature(CF,"CFDictionaryGetValue",PTR,[PTR,PTR])

_strings = {}


def cf_string(value):
    if value not in _strings:
        _strings[value] = make_string(None, value.encode("utf-8"), UTF8)
    return _strings[value]


class AXError(RuntimeError):
    def __init__(self, code, operation):
        self.code = code
        message = "Enable Satellite Bridge in Privacy & Security > Accessibility" if code == -25211 else f"RUMlogNG control unavailable ({operation}, AX {code})"
        super().__init__(message)


def decode(reference):
    kind = type_id(reference)
    if kind == string_type:
        buffer = C.create_string_buffer(string_length(reference) * 4 + 1)
        if not copy_string(reference, buffer, len(buffer), UTF8):
            raise RuntimeError("Cannot decode a RUMlogNG control label")
        return buffer.value.decode("utf-8")
    if kind == boolean_type:
        return bool(get_boolean(reference))
    if kind == number_type:
        value = C.c_double()
        if not get_number(reference, 13, C.byref(value)):
            raise RuntimeError("Cannot decode a RUMlogNG control value")
        return value.value
    if kind == array_type:
        return [decode(array_value(reference, i)) for i in range(array_count(reference))]
    if kind == element_type:
        return Element(retain(reference))
    if kind == ax_value_type and ax_value_kind(reference) == 5:
        error = C.c_int()
        ax_value_get(reference, 5, C.byref(error))
        return AXError(error.value, "attribute")
    return None


class Element:
    def __init__(self, reference):
        self.reference = reference
        set_timeout(reference, .8)

    def __del__(self):
        if self.reference:
            release(self.reference)
            self.reference = None

    def get(self, name, default=None):
        value = PTR()
        code = copy_attribute(self.reference, cf_string(name), C.byref(value))
        if code in (-25205, -25212):
            return default
        if code:
            raise AXError(code, name)
        try:
            return decode(value.value)
        finally:
            release(value)

    def press(self):
        code = perform_action(self.reference, cf_string("AXPress"))
        if code:
            raise AXError(code, "press")

    def cancel(self):
        code = perform_action(self.reference, cf_string("AXCancel"))
        if code:
            raise AXError(code, "close menu")

    def attrs(self, *names):
        refs = (PTR * len(names))(*(cf_string(name) for name in names))
        keys = make_array(None, refs, len(names), None)
        values = PTR()
        try:
            code = copy_attributes(self.reference, keys, 0, C.byref(values))
            if code:
                raise AXError(code, "read attributes")
            decoded = decode(values.value)
            return {name: None if isinstance(value, AXError) else value for name, value in zip(names, decoded)}
        finally:
            release(keys)
            if values.value:
                release(values)

    def set_number(self, value):
        number = C.c_double(value)
        reference = make_number(None, 13, C.byref(number))
        try:
            code = set_attribute(self.reference, cf_string("AXValue"), reference)
            if code:
                raise AXError(code, "set value")
        finally:
            release(reference)

    def set_boolean(self, name, value):
        reference = C.c_void_p.in_dll(CF, "kCFBooleanTrue" if value else "kCFBooleanFalse")
        code = set_attribute(self.reference, cf_string(name), reference)
        if code:
            raise AXError(code, name)

    def set_text(self, value):
        self.set_boolean("AXFocused",True)
        code = set_attribute(self.reference,cf_string("AXValue"),cf_string(value))
        if code:
            raise AXError(code,"set text")
        code = perform_action(self.reference,cf_string("AXConfirm"))
        if code:
            raise AXError(code,"confirm text")

    @property
    def children(self):
        return self.get("AXChildren", [])


def application(process_name="RUMlogNG"):
    if session_locked():
        raise RuntimeError("Unlock the Mac to allow IC-9700 panel control")
    if not is_trusted():
        raise AXError(-25211, "permission")
    result = subprocess.run(["/usr/bin/pgrep", "-x", process_name], text=True, capture_output=True, timeout=2)
    if result.returncode or not result.stdout.strip():
        raise RuntimeError("Open RUMlogNG before using the bridge")
    pids = result.stdout.split()
    if len(pids) != 1:
        raise RuntimeError("More than one RUMlogNG process is running")
    return Element(create_application(int(pids[0])))


def focused_application():
    return Element(create_system()).get("AXFocusedApplication")


def session_locked():
    session=copy_session()
    if not session:
        return True
    try:
        value=dictionary_value(session,cf_string("CGSSessionScreenIsLocked"))
        return bool(decode(value)) if value else False
    finally:
        release(session)
