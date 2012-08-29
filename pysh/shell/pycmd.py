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


class PyCmd(object):
    def __init__(self, body, name):
        self.__body = body
        self.__name = name

    def __call__(self, *args, **kwds):
        return self.__body(*args, **kwds)

    def name(self):
        return self.__name


def pycmd(*args, **kwds):
    if args:
        assert len(args) == 1
        assert not kwds
        assert callable(args[0])
        cmd = args[0]
        if not isinstance(cmd, PyCmd):
            cmd = PyCmd(cmd, name=cmd.func_name)
        register_pycmd(cmd.name(), cmd)
        return cmd
    if kwds:
        assert not args
        def register(func):
            if 'name' not in kwds:
                kwds['name'] = func.func_name
            cmd = PyCmd(func, **kwds)
            register_pycmd(cmd.name(), cmd)
        return register
    else:
        raise Exception('Wrong params')
