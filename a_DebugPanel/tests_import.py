import importlib, sys, os

# Ensure a_DebugPanel package is on path
sys.path.insert(0, os.path.join(os.getcwd(), 'a_DebugPanel'))

mods = ['serial_manager', 'runtime_status', 'universal_tip', 'knob', 'panel']
for m in mods:
    try:
        importlib.import_module(m)
        print('OK', m)
    except Exception as e:
        print('ERR', m, repr(e))
