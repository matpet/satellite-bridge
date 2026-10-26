"""Receiver-only CI-V macros executed by RUMlogNG's existing CAT owner.

The three exact payloads contain no frequency, PTT, CW or voice commands.
Existing unrelated manual macros and all automatic mode macros are kept.
"""

FRONTEND_MACROS = {
    "SB RX Off": "FE FE A2 E0 16 02 00 FD",
    "SB RX Int": "FE FE A2 E0 16 02 01 FD",
    "SB RX Ext": "FE FE A2 E0 1A 05 00 94 01 FD FE FE A2 E0 16 02 03 FD",
}


def normalized(value):
    return " ".join(str(value).upper().split())


def plan_macros(values):
    if len(values)!=36:
        raise RuntimeError("Unexpected IC-9700 macro editor layout")
    changes={}
    empty=[i for i in range(16) if not values[2*i].strip() and not values[2*i+1].strip()]
    for name,payload in FRONTEND_MACROS.items():
        matches=[i for i in range(16) if values[2*i]==name]
        if len(matches)>1:
            raise RuntimeError(f"Duplicate receiver macro: {name}")
        if matches:
            if normalized(values[2*matches[0]+1])!=payload:
                raise RuntimeError(f"Receiver macro content differs: {name}")
        else:
            if not empty:
                raise RuntimeError("Three unused IC-9700 manual macro slots are required")
            index=empty.pop(0)
            changes[2*index],changes[2*index+1]=name,payload
    return changes


def ensure_frontend_macros(panel):
    previous=panel.focus_for_menu()
    fields=[];original=[];saved=False
    def sheet():
        return next((c for c in panel.window().children if c.get('AXRole')=='AXSheet'),None)
    try:
        if sheet() is not None:
            raise RuntimeError("Close the existing IC-9700 sheet before applying receiver settings")
        panel.press('IC-9700 Macros','Edit Macros')
        panel.wait(lambda:sheet() is not None,'receiver macro editor')
        editor=sheet()
        def walk(element,depth=0):
            if depth>3:return
            if element.get('AXRole')=='AXTextField':fields.append(element)
            for child in element.children:walk(child,depth+1)
        walk(editor)
        original=[f.get('AXValue') or '' for f in fields]
        changes=plan_macros(original)
        wanted=[changes.get(i,v) for i,v in enumerate(original)]
        for index in range(16):
            if wanted[2*index] in FRONTEND_MACROS:
                # Commit the text editor into Cocoa's bound macro model;
                # an AXValue alone can remain only in the visible field.
                fields[2*index].set_text(wanted[2*index])
                fields[2*index+1].set_text(wanted[2*index+1])
        if [f.get('AXValue') or '' for f in fields]!=wanted:
            raise RuntimeError("Receiver macro fields did not verify")
        save=next(c for g in editor.children for c in ([g]+g.children)
                  if c.get('AXRole')=='AXButton' and c.get('AXTitle')=='Save')
        save.press();panel.wait(lambda:sheet() is None,'save receiver macros')
        saved=True
    finally:
        if not saved and original and len(fields)==len(original):
            # Do not leave partially edited commands in a user's sheet.
            for field,value in zip(fields,original):
                if field.get('AXValue')!=value:field.set_text(value)
            editor=sheet()
            if editor is not None:
                save=next(c for g in editor.children for c in ([g]+g.children)
                          if c.get('AXRole')=='AXButton' and c.get('AXTitle')=='Save')
                save.press()
        panel.restore_menu_focus(previous)
