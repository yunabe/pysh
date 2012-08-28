__pycmd_map = {}

def register_pycmd(name, pycmd):
  __pycmd_map[name] = pycmd

def get_pycmd(name):
  if isinstance(name, str) and name in __pycmd_map:
    return __pycmd_map[name]
  elif callable(name):
    return name
  else:
    return None
