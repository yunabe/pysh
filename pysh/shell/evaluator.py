import collections
import glob
import os
import re
import sys
import threading

from pysh.shell.tokenizer import (
  SPACE,
  SINGLE_QUOTED_STRING,
  DOUBLE_QUOTED_STRING,
  SUBSTITUTION,
  REDIRECT,
  PIPE,
  RIGHT_ARROW,
  BOLD_RIGHT_ARROW,
  LITERAL,
  AND_OP,
  OR_OP,
  PARENTHESIS_START,
  PARENTHESIS_END,
  SEMICOLON,
  BACKQUOTE,
  EOF,
)

from pysh.shell.parser import Assign
from pysh.shell.parser import Parser
from pysh.shell.parser import Process
from pysh.shell.parser import BinaryOp
from pysh.shell.tokenizer import Tokenizer


PYVAR_PATTERN = re.compile(r'^[_a-zA-Z][_a-zA-Z0-9]*$')


class NativeToPy(object):
  def __init__(self, ast, input, output):
    self.ast = ast
    self.input = input
    self.output = output


def GetArg0Name(tok, vardict):
  if tok[0] == LITERAL or tok[0] == SINGLE_QUOTED_STRING:
    return tok[1]
  if tok[0] != SUBSTITUTION:
    return None
  value = tok[1]
  if value.startswith('${'):
    value = value[2:-1]
  else:
    value = value[1:]
  if not PYVAR_PATTERN.match(value):
    return None
  value = vardict.get(value, None)
  if isinstance(value, str):
    return value
  if (isinstance(value, tuple) or isinstance(value, list)) and (
    isinstance(value[0], str)):
    return value[0]
  # value can be pycmd itself.
  return value


def IsPyCmd(proc, vardict):
  arg0 = proc.args[0]
  if len(arg0) != 1:
    return False
  name = GetArg0Name(arg0[0], vardict)
  pycmd = get_pycmd(name)
  return not not pycmd


def DiagnoseIOType(ast, vardict):
  DiagnoseIOTypeInternal(ast, vardict)
  if ast.inType == 'ST' and ast.outType == 'ST':
    # should be tested in evaluator_test.py
    return ast
  else:
    return NativeToPy(ast, ast.inType == 'PY', ast.outType == 'PY')


# Maybe, we don't need outType.
def DiagnoseIOTypeInternal(ast, vardict):
  if isinstance(ast, Process):
    is_pycmd = IsPyCmd(ast, vardict)
    if is_pycmd:
      ast.inType = 'PY'
      ast.outType = 'PY'
    else:
      ast.inType = 'ST'
      ast.outType = 'ST'
  elif isinstance(ast, Assign):
    DiagnoseIOTypeInternal(ast.cmd, vardict)
    ast.inType = ast.cmd.inType
    ast.outType = ast.cmd.outType
  else:
    assert isinstance(ast, BinaryOp)
    DiagnoseIOTypeInternal(ast.left, vardict)
    DiagnoseIOTypeInternal(ast.right, vardict)
    if ast.op == '|':
      ast.inType = ast.left.inType
      ast.outType = ast.right.outType
      if ast.left.outType != ast.right.inType:
        if ast.left.outType == 'PY':
          ast.left = NativeToPy(ast.left, False, True)
          ast.left.inType = ast.inType
          ast.left.outType = 'ST'
        else:
          ast.right = NativeToPy(ast.right, True, False)
          ast.right.inType = 'ST'
          ast.right.outType = ast.outType
    else:
      if ast.left.inType != ast.right.inType:
        raise Exception('Can not combile cmd that reads python object and '
                        'cmd that reads file stream.')
      ast.inType = ast.left.inType
      if ast.left.outType == ast.right.outType:
        ast.outType = ast.left.outType
      else:
        ast.outType = 'MIX'
        raise Exception('Not supported.')


class VarDict(dict):
  # VarDict must be a real dict because it is passed to eval as globals.
  def __init__(self, globals, locals):
    for d in (os.environ, globals, locals):
      for key in d:
        self[key] = d[key]


__pycmd_map = {}


def register_pycmd(name, pycmd):
  __pycmd_map[name] = pycmd


def get_pycmd(name):
  if isinstance(name, str) and name in __pycmd_map:
    return __pycmd_map[name]
  elif hasattr(name, 'process'):
    return name
  else:
    return None


class PipeFd(object):
  def __init__(self, parent, stdin, stdout):
    self.stdin = None
    self.stdout = None
    if parent:
      self.stdin = parent.stdin
      self.stdout = parent.stdout
    if stdin is not None:
      self.stdin = stdin
    if stdout is not None:
      self.stdout = stdout


class PyPipe(object):
  def __init__(self):
    self.__generators = collections.deque()
    self.__close = False
    self.__cond = threading.Condition()

  def add_generator(self, generator):
    self.__cond.acquire()
    self.__generators.append(generator)
    self.__cond.notify()
    self.__cond.release()

  def close(self):
    self.__cond.acquire()
    self.__close = True
    self.__cond.notify()
    self.__cond.release()

  def __iter__(self):
    while True:
      self.__cond.acquire()
      while not (self.__close or self.__generators):
        self.__cond.wait()
      if self.__generators:
        generator = self.__generators.pop()
      else:
        generator = None
      self.__cond.release()

      if generator:
        for e in generator:
          yield e
      else:
        assert self.__close
        break


class TaskArg(object):
  def __init__(self, rc, pool, pids, wait_thread, callbacks,
               write_done, cond, globals, locals):
    self.rc = rc
    self.pool = pool
    self.pids = []
    self.callbacks = callbacks
    self.wait_thread = wait_thread
    self.all_r = set()
    self.all_w = set()
    self.files = {}
    self.write_done = write_done
    self.condition = cond
    self.globals = globals
    self.locals = locals

  def ospipe(self):
    rw = os.pipe()
    self.all_r.add(rw[0])
    self.all_w.add(rw[1])
    return rw

  def filew(self, path, mode):
    assert mode == 'a' or mode == 'w'
    f = file(path, mode)
    self.files[f.fileno()] = f
    return f

  def tofile(self, fd):
    if fd == sys.stdin.fileno():
      return sys.stdin
    if fd == sys.stdout.fileno():
      return sys.stdout
    if fd in self.all_r:
      mode = 'r'
    elif fd in self.all_w:
      mode = 'w'
    else:
      raise Exception('Unknown file descriptor: ' + str(fd))
    f = os.fdopen(fd, mode)
    self.files[fd] = f
    return f

  def close(self, fd):
    if fd in self.files:
      # We need to close file explicitly. Why?
      self.files[fd].close()
      del self.files[fd]
    else:
      os.close(fd)
    if fd in self.all_w:
      self.all_w.remove(fd)
    if fd in self.all_r:
      self.all_r.remove(fd)

class EvalAstTask(object):
  def __init__(self, arg, pipefd, ast):
    self.__arg = arg
    self.__pipefd = pipefd
    self.__ast = ast

  def start(self, cont):
    ast = self.__ast
    if isinstance(ast, Process):
      cont.call(EvalProcessTask(self.__arg, self.__pipefd, ast), 'wait')
    elif isinstance(ast, BinaryOp):
      op = ast.op
      if op == '&&' or op == '||' or op == ';':
        cont.call(
          SemiAndOrTask(self.__arg, self.__pipefd, op, ast.left, ast.right),
          'wait')
      elif op == '|':
        self.invokePipeTask(cont, ast.left, ast.right)
      else:
        raise Exception('Unknown op:', op)
    elif isinstance(ast, Assign):
      cont.call(AssignTask(
          self.__arg, self.__pipefd, ast.cmd, ast.name), 'wait')
    elif isinstance(ast, NativeToPy):
      cont.call(NativeToPyTask(self.__arg, self.__pipefd, ast), 'wait')
    else:
      raise Exception('Unexpected ast')

  def invokePipeTask(self, cont, left, right):
    assert left.outType == right.inType
    if left.outType == 'PY':
      cont.call(PipePyToPyTask(self.__arg, self.__pipefd, left, right), 'wait')
    else:
      cont.call(PipeNativeToNativeTask(self.__arg, self.__pipefd, left, right),
                'wait')

  def resume(self, cont, state, response):
    assert state == 'wait'
    cont.done(response)


class WriteThread(threading.Thread):
  def __init__(self, input, output):
    threading.Thread.__init__(self)
    self.__input = input
    self.__output = output

  def run(self):
    for e in self.__input:
      self.__output.write(str(e))
      self.__output.write('\n')


class WritePyCmdRedirectThread(threading.Thread):
  def __init__(self, input, out):
    threading.Thread.__init__(self)
    self.__input = input
    self.__file = out

  def run(self):
    for e in self.__input:
      self.__file.write(str(e))
      self.__file.write('\n')


class WritePyCmdRedirectPyOutThread(threading.Thread):
  def __init__(self, input, output):
    threading.Thread.__init__(self)
    self.__input = input
    self.__output = output

  def run(self):
    for e in self.__input:
      self.__output.append(e)


class WriteToPyOutThread(threading.Thread):
  def __init__(self, input, output):
    threading.Thread.__init__(self)
    self.__input = input
    self.__output = output

  def run(self):
    for line in self.__input:
      self.__output.append(line.rstrip('\r\n'))


class WaitChildThread(threading.Thread):
  def __init__(self, pids, pids_cond):
    threading.Thread.__init__(self)
    self.__pids = pids
    self.__pids_cond = pids_cond
    self.__child_count = 0
    self.__child_count_cond = threading.Condition()
    self.__stop = False

  def increuemnt(self):
    self.__child_count_cond.acquire()
    self.__child_count += 1
    if self.__child_count == 1:
      self.__child_count_cond.notify()
    self.__child_count_cond.release()

  def stop(self):
    self.__child_count_cond.acquire()
    self.__stop = True
    self.__child_count_cond.notify()
    self.__child_count_cond.release()

  def run(self):
    while True:
      self.__child_count_cond.acquire()
      while self.__child_count == 0 and not self.__stop:
        self.__child_count_cond.wait()

      if self.__child_count > 0:
        self.__child_count -= 1
        done = False
      else:
        assert(self.__stop)
        done = True

      self.__child_count_cond.release()

      if done:
        break
      pid, rc = os.wait()
      self.__pids_cond.acquire()
      self.__pids.append((pid, rc))
      if len(self.__pids) == 1:
        self.__pids_cond.notify()
      self.__pids_cond.release()


class NativeToPyTask(object):
  def __init__(self, arg, pipefd, ast):
    self.__arg = arg
    self.__pipefd = pipefd
    self.__ast = ast
    self.__new_w = None
    self.__write_th = None

  def start(self, cont):
    new_r = None
    new_w = None
    if self.__ast.input:
      new_r = self.__arg.tofile(self.__pipefd.stdin)
    if self.__ast.output:
      new_w = PyPipe()
      self.__write_th = WriteThread(new_w,
                                    self.__arg.tofile(self.__pipefd.stdout))
      self.__write_th.start()
      self.__new_w = new_w
    cont.call(EvalAstTask(
        self.__arg,
        PipeFd(self.__pipefd, new_r, new_w),
        self.__ast.ast), 'wait')

  def resume(self, cont, state, response):
    if self.__new_w:
      self.__new_w.close()
      self.__write_th.join()
    cont.done(response)


class SemiAndOrTask(object):
  def __init__(self, arg, pipefd, op, left, right):
    self.__arg = arg
    self.__pipefd = pipefd
    self.__op = op
    self.__left = left
    self.__right = right

  def start(self, cont):
    cont.call(EvalAstTask(self.__arg, self.__pipefd, self.__left), 'left')

  def resume(self, cont, state, response):
    if state == 'left':
      ok = response == 0
      if (ok and self.__op == '||') or (not ok and self.__op == '&&'):
        cont.done(response)
        return
      cont.call(EvalAstTask(self.__arg, self.__pipefd, self.__right), 'right')
    else:
      assert state == 'right'
      cont.done(response)

class PipePyToPyTask(object):
  def __init__(self, arg, pipefd, left, right):
    self.__arg = arg
    self.__pipefd = pipefd
    self.__left = left
    self.__right = right

  def start(self, cont):
    self.__pypipe = PyPipe()
    cont.call(EvalAstTask(self.__arg,
                          PipeFd(self.__pipefd, None, self.__pypipe),
                          self.__left),
              'left')
    cont.call(EvalAstTask(self.__arg,
                          PipeFd(self.__pipefd, self.__pypipe, None),
                          self.__right),
              'right')

  def resume(self, cont, state, response):
    if state == 'left':
      self.__pypipe.close()
    else:
      assert state == 'right'
      # it's okay?
      cont.done(response)


class PipeNativeToNativeTask(object):
  def __init__(self, arg, pipefd, left, right):
    self.__arg = arg
    self.__pipefd = pipefd
    self.__left = left
    self.__right = right

  def start(self, cont):
    r, w = self.__arg.ospipe()
    self.__r = r
    self.__w = w
    cont.call(EvalAstTask(self.__arg, PipeFd(self.__pipefd, None, self.__w),
                          self.__left), 'left')
    cont.call(EvalAstTask(self.__arg, PipeFd(self.__pipefd, self.__r, None),
                          self.__right), 'right')

  def resume(self, cont, state, response):
    if state == 'left':
      self.__arg.close(self.__w)
    else:
      assert state == 'right'
      self.__arg.close(self.__r)
      # it's okay?
      cont.done(response)


class AssignTask(object):
  def __init__(self, arg, pipefd, ast, var):
    self.__arg = arg
    self.__pipefd = pipefd
    self.__ast = ast
    self.__var = var

  def start(self, cont):
    cont.call(EvalAstTask(self.__arg, self.__pipefd, self.__ast), 'wait')

  def resume(self, cont, state, response):
    assert state == 'wait'
    self.__arg.rc[self.__var] = response
    cont.done(response)


class EvalArgTask(object):
  def __init__(self, arg, pipefd, target):
    self.__arg = arg
    self.__pipefd = pipefd
    self.__target = target
    self.__result = [None] * len(self.__target)
    self.__not_ready = set(range(len(self.__target)))

  def start(self, cont):
    self.evalBackquotedCmd(
      cont, self.__target, self.__arg.globals, self.__arg.locals)

  def resume(self, cont, state, response):
    i = state[0]
    if len(state) == 1:
      self.__result[i] = response
    else:
      _, out, th, pipe = state
      self.__arg.close(pipe[1])
      th.join()
      self.__arg.close(pipe[0])
      self.__result[i] = (SINGLE_QUOTED_STRING, repr('\n'.join(out)))
    self.__not_ready.remove(i)
    if self.__not_ready:
      return
    result = self.evalArg(self.__result, self.__arg.globals, self.__arg.locals)
    cont.done(result)

  def evalSubstitution(self, value, globals, locals):
    if value.startswith('${'):
      # remove ${ and }
      name = value[2:-1]
    else:
      # remove $
      name = value[1:]
    # We need to pass VarDict as globals because free variable in lambda is
    # treated as global variable in eval (http://goo.gl/bfVW9).
    return eval(name,
                VarDict(self.__arg.globals, self.__arg.locals), {})

  def evalArg(self, arg, globals, locals):
    assert arg
    if not self.hasGlobPattern(arg):
      return self.evalArgNoGlob(arg, globals, locals)
    else:
      return self.evalArgGlob(arg, globals, locals)

  def evalBackquotedCmd(self, cont, arg, globals, locals):
    for i, tok in enumerate(arg):
      if tok[0] == BACKQUOTE:
        ast = DiagnoseIOType(
          tok[1], VarDict(self.__arg.globals, self.__arg.locals))
        r, w = self.__arg.ospipe()
        out = []
        th = WriteToPyOutThread(self.__arg.tofile(r), out)
        th.start()
        cont.call(EvalAstTask(self.__arg,
                              PipeFd(self.__pipefd, None, w),
                              ast),
                  (i, out, th, (r, w)))
      else:
        cont.resume((i,), tok)
  
  def evalArgNoGlob(self, arg, globals, locals):
    values = []
    for tok in arg:
      if tok[0] == LITERAL:
        values.append(tok[1])
      elif tok[0] == SINGLE_QUOTED_STRING:
        values.append(eval(tok[1]))
      elif tok[0] == SUBSTITUTION:
        values.append(self.evalSubstitution(tok[1], globals, locals))
      else:
        raise Exception('Unexpected token: %s' % tok[0])
    if len(values) > 1:
      result = ''.join(map(str, values))
    else:
      result = values[0]
    if isinstance(result, str):
      result = os.path.expanduser(result)
    return [result]

  def evalArgGlob(self, arg, globals, locals):
    values = []
    for tok in arg:
      if tok[0] == LITERAL:
        values.append(tok[1])
      elif tok[0] == SINGLE_QUOTED_STRING:
        values.append(eval(tok[1]).replace('*', '[*]').replace('?', '[?]'))
      elif tok[0] == SUBSTITUTION:
        values.append(
          self.evalSubstitution(tok[1], globals, locals).replace(
            '*', '[*]').replace('?', '[?]'))
      else:
        raise Exception('Unexpected token: %s' % tok[0])
    result = ''.join(map(str, values))
    expanded = glob.glob(os.path.expanduser(result))
    # Make order of glob expansion stable.
    expanded.sort()
    return expanded

  def hasGlobPattern(self, arg):
    for tok in arg:
      if tok[0] == LITERAL:
        if '*' in tok[1] or '?' in tok[1]:
          return True
    return False


class EvalProcessTask(object):
  def __init__(self, arg, pipefd, proc):
    self.__arg = arg
    self.__pipefd = pipefd
    self.__proc = proc

    self.__pycmd_redirect_out = None
    self.__pycmd_redirect_th = None

    self.__pyout_rs = set()
    self.__pyout_thread = []

    self.__evaled_args = None
    self.__evaled_args_not_ready = None
    self.__evaled_redirects = None
    self.__evaled_redirects_not_ready = None

  def resume(self, cont, state, response):
    invoke_if_ready = False
    if isinstance(state, tuple) and len(state) == 2 and state[0] == 'evalarg':
      self.__evaled_args[state[1]] = response
      self.__evaled_args_not_ready.remove(state[1])
      invoke_if_ready = True

    elif isinstance(state, tuple) and len(state) == 2 and (
      state[0] == 'putredirect'):
      self.__evaled_redirects[state[1]] = response
      self.__evaled_redirects_not_ready.remove(state[1])
      invoke_if_ready = True

    elif isinstance(state, tuple) and len(state) == 3 and (
      state[0] == 'evalredirect'):
      redirect = state[2]
      self.__evaled_redirects[state[1]] = (
        redirect[0], redirect[1], 'file', str(response[0]))
      self.__evaled_redirects_not_ready.remove(state[1])
      invoke_if_ready = True

    if invoke_if_ready:
      if not self.__evaled_args_not_ready and (
        not self.__evaled_redirects_not_ready):
        self.invokeProcess(cont)
      return
    
    assert state == 'pycmd_done' or state == 'cmd_done'
    if self.__pycmd_redirect_th:
      self.__pycmd_redirect_th.join()
    if self.__pycmd_redirect_out:
      self.__arg.close(self.__pycmd_redirect_out.fileno())
    for th in self.__pyout_thread:
      th.join()
    for r in self.__pyout_rs:
      self.__arg.close(r)
    cont.done(response)

  def processPyCmd(self, cont, pycmd, args, stdin):
    try:
      for e in pycmd.process(args, stdin):
        yield e
      rc = 0
    except Exception, e:
      print >> sys.stderr, e
      rc = 1
    self.__arg.condition.acquire()
    self.__arg.write_done.append((cont, 'pycmd_done', rc))
    self.__arg.condition.notify()
    self.__arg.condition.release()

  def convertToCmdArgs(self, arg):
    if isinstance(arg, list):
      return map(str, arg)
    else:
      return [str(arg)]

  def start(self, cont):
    proc = self.__proc
    self.__evaled_args = [None] * len(proc.args)
    self.__evaled_args_not_ready = set(range(len(proc.args)))
    self.__evaled_redirects = [None] * len(proc.redirects)
    self.__evaled_redirects_not_ready = set(range(len(proc.redirects)))
    for i, arg in enumerate(proc.args):
      cont.call(EvalArgTask(self.__arg, self.__pipefd, arg), ('evalarg', i))
    for i, redirect in enumerate(proc.redirects):
      if redirect[0] == '=>':
        cont.resume(('putredirect', i), (False, 1, 'pyout', redirect[1]))
      elif isinstance(redirect[2], int):
        cont.resume(('putredirect', i),
                    (redirect[0], redirect[1], 'num', redirect[2]))
      else:
        cont.call(EvalArgTask(self.__arg, self.__pipefd, redirect[2]),
                  (('evalredirect', i, redirect)))

  def invokeProcess(self, cont):
    proc = self.__proc
    args = []
    for arg in self.__evaled_args:
      args.extend(arg)

    redirects = self.__evaled_redirects
    pycmd = get_pycmd(args[0])
    if pycmd:
      assert len(redirects) < 2
      if redirects:
        redirect = redirects[0]
        assert not redirect[2] == 'num'
        if redirect[2] == 'file':
          assert redirect[1] == 1  # stdout
          if redirect[0]:
            mode = 'a'  # >>
          else:
            mode = 'w'  # >
          self.__pycmd_redirect_out = self.__arg.filew(redirect[3], mode)
          self.__pycmd_redirect_th = WritePyCmdRedirectThread(
            self.processPyCmd(cont, pycmd, args, self.__pipefd.stdin),
            self.__pycmd_redirect_out)
          self.__pycmd_redirect_th.start()
        else:
          assert redirect[2] == 'pyout'
          pyout_list = []
          self.__arg.rc[redirect[3]] = pyout_list
          self.__pycmd_redirect_th = WritePyCmdRedirectPyOutThread(
            self.processPyCmd(cont, pycmd, args, self.__pipefd.stdin),
            pyout_list)
          self.__pycmd_redirect_th.start()
      else:
        if isinstance(self.__pipefd.stdin, int):
          raise Exception('Bug')
        else:
          self.__pipefd.stdout.add_generator(
            self.processPyCmd(cont, pycmd, args, self.__pipefd.stdin))
      return

    pyout_ws = set()
    for i, redirect in enumerate(redirects):
      if redirect[2] != 'pyout':
        continue
      pyout_list = []
      self.__arg.rc[redirect[3]] = pyout_list
      pyout_r, pyout_w = self.__arg.ospipe()
      self.__pyout_rs.add(pyout_r)
      pyout_ws.add(pyout_w)
      redirects[i] = (redirect[0], redirect[1], redirect[2], pyout_w)
      th = WriteToPyOutThread(self.__arg.tofile(pyout_r), pyout_list)
      th.start()
      self.__pyout_thread.append(th)

    pid = os.fork()
    if pid != 0:
      for pyout_w in pyout_ws:
        self.__arg.close(pyout_w)
      self.__arg.wait_thread.increuemnt()
      self.__arg.callbacks[pid] = lambda rc: cont.resume('cmd_done', rc)
    else:
      for fd in self.__arg.all_w:
        if fd != self.__pipefd.stdout and fd not in pyout_ws:
          os.close(fd)
      for fd in self.__arg.all_r:
        if fd != self.__pipefd.stdin:
          os.close(fd)
      if self.__pipefd.stdout:
        # dup2 does nothing args are same.
        os.dup2(self.__pipefd.stdout, sys.stdout.fileno())
      if self.__pipefd.stdin:
        os.dup2(self.__pipefd.stdin, sys.stdin.fileno())
      for redirect in redirects:
        if redirect[2] == 'num':
          os.dup2(redirect[3], redirect[1])
        elif redirect[2] == 'pyout':
          os.dup2(redirect[3], redirect[1])
        else:
          if redirect[0]:
            mode = 'a'  # >>
          else:
            mode = 'w'  # >
          f = file(redirect[3], mode)
          os.dup2(f.fileno(), redirect[1])
      str_args = []
      for arg in args:
        str_args.extend(self.convertToCmdArgs(arg))
      try:
        os.execvp(str_args[0], str_args)
      except Exception, e:
        print >> sys.stderr, e
        sys.stderr.flush()
        os._exit(1)


class Evaluator(object):
  def __init__(self, parser):
    self.__parser = parser
    self.__rc = {}

  def __after_folk(self, pid):
    # TODO(yunabe): Reimplement __after_folk hook if needed.
    pass

  def rc(self):
    return self.__rc

  def execute(self, globals, locals):
    ast = self.__parser.parse()
    ast = DiagnoseIOType(ast, VarDict(globals, locals))
    self.executeAst(ast, globals, locals)

  def executeAst(self, ast, globals, locals):
    # TODO: Fix exception handling.
    # TODO: Share WaitChildThread in a process.
    pool = []
    cond = threading.Condition()
    pids = []
    wait_thread = WaitChildThread(pids, cond)
    wait_thread.start()
    callbacks = {}
    write_done = []
    arg = TaskArg(self.__rc, pool, pids, wait_thread, callbacks,
                  write_done, cond, globals, locals)
    runner = Runner(
      EvalAstTask(arg,
                  PipeFd(None, sys.stdin.fileno(), sys.stdout.fileno()),
                  ast))
    runner.run()
    while not runner.done:
      cond.acquire()
      while len(pids) == 0 and len(write_done) == 0:
        cond.wait()
      if write_done:
        cont, state, rc = write_done.pop()
        cond.release()
        cont.resume(state, rc)
      else:
        pid, rc = pids.pop()
        cond.release()
        callbacks[pid](rc)
      runner.run()
    wait_thread.stop()
    wait_thread.join()


def run(cmd_str, globals, locals, alias_map=None):
  tok = Tokenizer(cmd_str, alias_map=alias_map)
  parser = Parser(tok)
  evaluator = Evaluator(parser)
  evaluator.execute(globals, locals)
  return evaluator.rc()


class Controller(object):
    def __init__(self, runner, task, callstack):
        self.__runner = runner
        self.__task = task
        self.__stack = callstack

    def call(self, task, state):
        stack = ((self.__task, state), self.__stack)
        self.__runner.push_call(stack, task)

    def done(self, response):
        self.__runner.push_done(self.__stack, response)

    def resume(self, state, response):
        self.__runner.push_done(((self.__task, state), self.__stack), response)


class Runner(object):
    def __init__(self, task):
        # tasks is FIFO to run tasks in DFS way.
        # To run tasks in BFS way, use collections.deque.
        self.__tasks = [('call', None, task)]
        self.response = None
        self.done = False

    def run(self):
        while self.__tasks:
            self.run_internal()

    def __push_task(self, task):
        self.__tasks.append(task)

    def push_call(self, callstack, subtask):
        self.__push_task(('call', callstack, subtask))

    def push_done(self, callstack, response):
        self.__push_task(('done', callstack, response))

    def run_internal(self):
        task = self.__tasks.pop()
        type = task[0]
        stack = task[1]
        if type == 'call':
            f = task[2]
            cont = Controller(self, f, stack)
            f.start(cont)
        else:
            # done
            response = task[2]
            if not stack:
                self.response = response
                self.done = True
            else:
                parent_stack = stack[1]
                task, state = stack[0]
                cont = Controller(self, task, parent_stack)
                task.resume(cont, state, response)
