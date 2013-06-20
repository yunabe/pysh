import atexit
import collections
import functools
import glob
import os
import re
import StringIO
import traceback
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
from pysh.shell.pycmd import get_pycmd
from pysh.shell.pycmd import IOType
from pysh.shell.pycmd import PyCmdOption
from pysh.shell.tokenizer import Tokenizer
from pysh.shell.task_manager import Runner, IdentityTask


PYVAR_PATTERN = re.compile(r'^[_a-zA-Z][_a-zA-Z0-9]*$')


class ProxyPyOutToNative(object):
  """A class that represents convversion from python outputs of child ast
  to native output."""
  def __init__(self, ast):
    self.ast = ast


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


def GetProcIOType(proc, vardict):
  # returns is_pycmd, inType, outType
  arg0 = proc.args[0]
  if len(arg0) != 1:
    return False, 'ST', 'ST'
  name = GetArg0Name(arg0[0], vardict)
  pycmd = get_pycmd(name)
  if not pycmd:
    return False, 'ST', 'ST'

  inType, outType = 'PY', 'PY'
  if hasattr(pycmd, 'inType'):
    if pycmd.inType() == IOType.File:
      inType = 'ST'
    elif pycmd.inType() == IOType.No:
      inType = 'NO'
  if hasattr(pycmd, 'outType'):
    if pycmd.outType() == IOType.File:
      outType = 'ST'
    elif pycmd.outType() == IOType.No:
      outType = 'NO'
  return True, inType, outType


def MergeIOType(x, y):
  if x == y:
    return x
  if x == 'NO' or y == 'NO':
    return x if y == 'NO' else y
  return 'MIX'


def IsFileTypeIO(iotype):
  return iotype == 'ST' or iotype == 'MIX'


def DiagnoseIOType(ast, vardict):
  ast = DiagnoseIOTypeInternal(ast, vardict)
  if IsFileTypeIO(ast.outType):
    return ast
  else:
    return ProxyPyOutToNative(ast)


# Maybe, we don't need outType.
def DiagnoseIOTypeInternal(ast, vardict):
  if isinstance(ast, Process):
    return DiagnoseProcessIOType(ast, vardict)
  elif isinstance(ast, Assign):
    ast.cmd = DiagnoseIOTypeInternal(ast.cmd, vardict)
    ast.inType = ast.cmd.inType
    ast.outType = ast.cmd.outType
    return ast
  else:
    assert isinstance(ast, BinaryOp)
    ast.left = DiagnoseIOTypeInternal(ast.left, vardict)
    ast.right = DiagnoseIOTypeInternal(ast.right, vardict)
    if ast.op == '|':
      ast.inType = ast.left.inType
      ast.outType = ast.right.outType
      if ast.left.outType == 'MIX' and ast.right.inType == 'PY':
        raise Exception('Can not pipe combination of python outputs and '
                        'file outputs to commands that read python data.')
      if not IsFileTypeIO(ast.left.outType) and IsFileTypeIO(ast.right.inType):
        ast.left = ProxyPyOutToNative(ast.left)
        ast.left.inType = ast.inType
        ast.left.outType = 'ST'
    else:
      inMerged = MergeIOType(ast.left.inType, ast.right.inType)
      outMerged = MergeIOType(ast.left.outType, ast.right.outType)
      if inMerged == 'MIX':
        raise Exception('Can not combile cmd that reads python object and '
                        'cmd that reads file stream.')
      ast.inType = inMerged
      ast.outType = outMerged
      if IsFileTypeIO(ast.outType):
        if not IsFileTypeIO(ast.left.outType):
          ast.left = ProxyPyOutToNative(ast.left)
        if not IsFileTypeIO(ast.right.outType):
          ast.right = ProxyPyOutToNative(ast.right)

    return ast


def DiagnoseProcessIOType(proc, vardict):
  is_pycmd, proc.inType, proc.outType = GetProcIOType(proc, vardict)
  for arg in proc.args:
    for i, (tok, ast) in enumerate(arg):
      if tok != 'bquote':
        continue
      ast = DiagnoseIOTypeInternal(ast, vardict)
      merged_intype = MergeIOType(ast.inType,  proc.inType)
      if merged_intype == 'MIX':
        raise Exception('Can not combile cmd that reads python object and '
                        'cmd that reads file stream.')
      proc.inType = merged_intype
      if ast.outType == 'PY':
        arg[i] = (tok, ProxyPyOutToNative(ast))
      else:
        arg[i] = (tok, ast)
  if is_pycmd and proc.outType == 'ST':
    original_proc = proc
    proc = ProxyPyOutToNative(proc)
    proc.inType = original_proc.inType
    proc.outType = original_proc.outType
  return proc


class VarDict(dict):
  # VarDict must be a real dict because it is passed to eval as globals.
  def __init__(self, globals, locals):
    for d in (os.environ, globals, locals):
      for key in d:
        self[key] = d[key]


class PipeFd(object):
  """A class which represents stdin and stdout in a specific AST context."""

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
    # TODO(yunabe): self.stdin and stdout can not be None?


class PyPipe(object):
  """A object that pipes iterators give by add_generator to __iter__."""

  def __init__(self, reader_type):
    self.__reader_type = reader_type
    self.__generators = collections.deque()
    self.__close = False
    self.__cond = threading.Condition()

  def add_generator(self, generator):
    self.__cond.acquire()
    self.__generators.append(generator)
    self.__cond.notify()
    self.__cond.release()

  def reader_type(self):
    return self.__reader_type

  def close(self):
    if self.__close:
      return
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
  """A class which is used to share resources amoung tasks."""

  def __init__(self, rc, pool, write_done, cond,
               after_fork, exec_fail,
               globals, locals):
    self.rc = rc
    self.pool = pool
    self.all_r = set()
    self.all_w = set()
    self.files = {}
    self.write_done = write_done
    self.condition = cond
    self.after_fork = after_fork
    self.exec_fail = exec_fail
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
    if fd in self.files:
      return self.files[fd]
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
  """An entry point of tasks for evaluation of AST of shell command."""
  
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
    elif isinstance(ast, ProxyPyOutToNative):
      cont.call(ProxyPyOutToNativeTask(self.__arg, self.__pipefd, ast), 'wait')
    else:
      raise Exception('Unexpected ast: ', ast)

  def invokePipeTask(self, cont, left, right):
    assert (IsFileTypeIO(left.outType) or not IsFileTypeIO(right.inType))
    if not IsFileTypeIO(left.outType):
      cont.call(PipePyToPyTask(self.__arg, self.__pipefd, left, right), 'wait')
    else:
      cont.call(PipeNativeToNativeTask(self.__arg, self.__pipefd, left, right),
                'wait')

  def resume(self, cont, state, response):
    assert state == 'wait'
    cont.done(response)


class WriteThread(threading.Thread):
  """A thread to write python data to file stream."""
  
  def __init__(self, input, output):
    threading.Thread.__init__(self)
    self.__input = input
    self.__output = output

  def run(self):
    for e in self.__input:
      self.__output.write(str(e))
      self.__output.write('\n')


class WritePyCmdRedirectThread(threading.Thread):
  """A thread to write python data to file stream.

  TODO(yunabe): Integrate this to WriteThread.
  """

  def __init__(self, input, out):
    threading.Thread.__init__(self)
    self.__input = input
    self.__file = out

  def run(self):
    for e in self.__input:
      self.__file.write(str(e))
      self.__file.write('\n')


class WritePyCmdRedirectPyOutThread(threading.Thread):
  """A thread to write python data to python list (redirect to python)."""
  
  def __init__(self, input, output):
    threading.Thread.__init__(self)
    self.__input = input
    self.__output = output

  def run(self):
    for e in self.__input:
      self.__output.append(e)


class WriteToPyOutThread(threading.Thread):
  """A thread to write file stream to python list (redirect to python)."""

  def __init__(self, input, output):
    threading.Thread.__init__(self)
    self.__input = input
    self.__output = output

  def run(self):
    for line in self.__input:
      self.__output.append(line.rstrip('\r\n'))


global_wait_thread = None
global_wait_thread_lock = threading.Lock()


class WaitChildThread(threading.Thread):
  """A thread which catches termination of child processes.

  It calls callbacks registered by other threads via register_callback."""
  
  def __init__(self):
    threading.Thread.__init__(self)
    # setDaemon so that Python can exit if the thread is running.
    self.setDaemon(True)
    self.__callbacks = {}
    self.__unhandled = {}  # {pid: rc}
    self.__stop = False
    self.__cond = threading.Condition()

  def register_callback(self, pid, callback):
    """Register callback for the end of process.

    Please note that this method is called by other threads."""
    self.__cond.acquire()
    unhandled_rc = None
    if pid in self.__unhandled:
      unhandled_rc = self.__unhandled[pid]
      del self.__unhandled[pid]
    else:
      assert not pid in self.__callbacks
      self.__callbacks[pid] = callback
      if len(self.__callbacks) == 1:
        self.__cond.notify()  # notify to the wait thread
    self.__cond.release()
    if unhandled_rc is not None:
      callback(unhandled_rc)

  def stop(self):
    self.__cond.acquire()
    self.__stop = True
    self.__cond.notify()
    self.__cond.release()

  def run(self):
    while True:
      self.__cond.acquire()
      while len(self.__callbacks) == 0 and not self.__stop:
        self.__cond.wait()
      done = len(self.__callbacks) == 0
      self.__cond.release()

      if done:
        break
      pid, rc = os.wait()
      callback = None
      self.__cond.acquire()
      if pid in self.__callbacks:
        callback = self.__callbacks[pid]
        del self.__callbacks[pid]
      else:
        self.__unhandled[pid] = rc
      self.__cond.release()
      if callback:
        callback(rc)


class ProxyPyOutToNativeTask(object):
  """A task which writes output of the child ATF (ast) to pipefd.stdout."""
  
  def __init__(self, arg, pipefd, ast):
    self.__arg = arg
    self.__pipefd = pipefd
    self.__ast = ast
    self.__new_w = None
    self.__write_th = None

  def start(self, cont):
    new_w = None
    new_w = PyPipe('ST')
    self.__write_th = WriteThread(new_w,
                                  self.__arg.tofile(self.__pipefd.stdout))
    self.__write_th.start()
    self.__new_w = new_w
    cont.call(EvalAstTask(
        self.__arg,
        PipeFd(self.__pipefd, None, new_w),
        self.__ast.ast), 'wait')

  def resume(self, cont, state, response):
    cont.done(response)

  def dispose(self):
    if self.__new_w:
      self.__new_w.close()
      self.__write_th.join()


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
    self.__pypipe = PyPipe('PY')
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

  def dispose(self):
    # close pypipe even if error occurrs.
    self.__pypipe.close()


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

  def __close_r(self):
    if self.__r is not None:
      self.__arg.close(self.__r)
      self.__r = None

  def __close_w(self):
    if self.__w is not None:
      self.__arg.close(self.__w)
      self.__w = None

  def resume(self, cont, state, response):
    if state == 'left':
      self.__close_w()
    else:
      assert state == 'right'
      self.__close_r()
      # it's okay?
      cont.done(response)

  def dispose(self):
    # close pipe even if error occurrs.
    self.__close_w()
    self.__close_r()


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
    self.__pipe = [None] * len(self.__target)
    self.__thread = [None] * len(self.__target)
    self.__not_ready = set(range(len(self.__target)))

  def start(self, cont):
    self.evalBackquotedCmd(cont, self.__arg.globals, self.__arg.locals)

  def resume(self, cont, state, response):
    i = state[0]
    if len(state) == 1:
      self.__result[i] = response
    else:
      _, out = state
      pipe = self.__pipe[i]
      self.__pipe[i] = None
      th = self.__thread[i]
      self.__thread[i] = None
      self.__arg.close(pipe[1])
      th.join()
      self.__arg.close(pipe[0])
      # backquoted arg is split by white spaces.
      out = ' '.join(out).split()
      self.__result[i] = [(SINGLE_QUOTED_STRING, repr(e)) for e in out]
    self.__not_ready.remove(i)
    if self.__not_ready:
      return

    entry = []
    new_result = [entry]
    for result in self.__result:
      if isinstance(result, list):
        for i, e in enumerate(result):
          if i != 0:
            entry = []
            new_result.append(entry)
          entry.append(e)
      else:
        entry.append(result)
    for i, result in enumerate(new_result):
      new_result[i] = self.evalArg(
        result, self.__arg.globals, self.__arg.locals)
    cont.done(reduce(lambda x, y: x + y, new_result))

  def dispose(self):
    for i, pipe in enumerate(self.__pipe):
      if pipe:
        th = self.__thread[i]
        assert th
        self.__pipe[i] = None
        self.__thread[i] = None
        self.__arg.close(pipe[1])
        # Need stop the thread before close(pipe[0]) to avoid
        # IO operation conflict
        th.join()
        self.__arg.close(pipe[0])

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
    if not arg:
      # e.g. backquoted command has no output
      return []
    if not self.hasGlobPattern(arg):
      return self.evalArgNoGlob(arg, globals, locals)
    else:
      return self.evalArgGlob(arg, globals, locals)

  def evalBackquotedCmd(self, cont, globals, locals):
    for i, tok in enumerate(self.__target):
      if tok[0] == BACKQUOTE:
        ast = tok[1]
        self.__pipe[i] = self.__arg.ospipe()
        r, w = self.__pipe[i]
        out = []
        th = WriteToPyOutThread(self.__arg.tofile(r), out)
        self.__thread[i] = th
        th.start()
        cont.call(EvalAstTask(self.__arg,
                              PipeFd(self.__pipefd, None, w),
                              ast),
                  (i, out))
      else:
        cont.call(IdentityTask(tok), (i,))
  
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
      self.__pycmd_redirect_out = None
    for th in self.__pyout_thread:
      th.join()
    for r in self.__pyout_rs:
      self.__arg.close(r)
    self.__pyout_rs = None
    cont.done(response)

  def disepose(self):
    if self.__pycmd_redirect_out:
      self.__arg.close(self.__pycmd_redirect_out.fileno())
      self.__pycmd_redirect_out = None
    for r in self.__pyout_rs:
      self.__arg.close(r)
    self.__pyout_rs = None

  def processPyCmd(self, cont, pycmd, args, stdin, reader_type):
    if hasattr(pycmd, 'inType') and pycmd.inType() == IOType.No:
      stdin = None
    if type(stdin) is int:
      stdin = self.__arg.tofile(stdin)
    no_output = hasattr(pycmd, 'outType') and pycmd.outType() == IOType.No
    try:
      output = pycmd(args, stdin,
                     PyCmdOption(self.__arg.globals, self.__arg.locals))
      if reader_type == 'ST' and hasattr(output, 'pretty_print'):
        io = StringIO.StringIO()
        output.pretty_print(io)
        yield io.getvalue().rstrip('\r\n')
      else:
        for e in output:
          if no_output:
            raise Exception('A pycmd with [outType= No] outputs something.')
          else:
            yield e
      rc = 0
    except Exception, e:
      traceback.print_exc(file=sys.stderr)
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
        cont.call(IdentityTask((False, 1, 'pyout', redirect[1])),
                  ('putredirect', i))
      elif isinstance(redirect[2], int):
        cont.call(IdentityTask((redirect[0], redirect[1], 'num', redirect[2])),
                  ('putredirect', i))
      else:
        cont.call(EvalArgTask(self.__arg, self.__pipefd, redirect[2]),
                  (('evalredirect', i, redirect)))

  def invokeCmd(self, cont):
    cmd = self.__proc.cmd
    redirects = self.__evaled_redirects
    if cmd.outType == 'PY':
      pass


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
            self.processPyCmd(cont, pycmd, args, self.__pipefd.stdin, 'ST'),
            self.__pycmd_redirect_out)
          self.__pycmd_redirect_th.start()
        else:
          assert redirect[2] == 'pyout'
          pyout_list = []
          self.__arg.rc[redirect[3]] = pyout_list
          self.__pycmd_redirect_th = WritePyCmdRedirectPyOutThread(
            self.processPyCmd(cont, pycmd, args, self.__pipefd.stdin, 'PY'),
            pyout_list)
          self.__pycmd_redirect_th.start()
      else:
        self.__pipefd.stdout.add_generator(
          self.processPyCmd(cont, pycmd, args, self.__pipefd.stdin,
                            self.__pipefd.stdout.reader_type()))
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
      self.__arg.after_fork(pid)
      for pyout_w in pyout_ws:
        self.__arg.close(pyout_w)
      def process_done_callback(rc):
        self.__arg.condition.acquire()
        self.__arg.write_done.append((cont, 'cmd_done', rc))
        self.__arg.condition.notify()
        self.__arg.condition.release()
      global_wait_thread.register_callback(pid, process_done_callback)
    else:
      try:
        self.__arg.after_fork(0)
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
        os.execvp(str_args[0], str_args)
      except Exception, e:
        self.__arg.exec_fail(e)
        print >> sys.stderr, e
        sys.stderr.flush()
        os._exit(1)


class Evaluator(object):
  def __init__(self, parser):
    self.__parser = parser
    self.__rc = {}

  def __after_folk(self, pid):
    pass

  def __exec_fail(self, exc):
    # called when exec failed.
    # Don't call any non-asynchronous signal safe method here.
    pass

  def rc(self):
    return self.__rc

  def execute(self, globals, locals):
    ast = self.__parser.parse()
    ast = DiagnoseIOType(ast, VarDict(globals, locals))
    self.executeAst(ast, globals, locals)

  def executeAst(self, ast, globals, locals):
    # TODO: Fix exception handling.
    pool = []
    cond = threading.Condition()
    write_done = []
    arg = TaskArg(self.__rc, pool,
                  write_done, cond,
                  self.__after_folk,
                  self.__exec_fail,
                  globals, locals)
    runner = Runner(
      EvalAstTask(arg,
                  PipeFd(None, sys.stdin.fileno(), sys.stdout.fileno()),
                  ast))
    runner.run()
    while not runner.done:
      cond.acquire()
      while len(write_done) == 0:
        cond.wait()
      cont, state, rc = write_done.pop()
      cond.release()
      cont.call(IdentityTask(rc), state)
      runner.run()


def start_global_wait_thread():
  global global_wait_thread
  if global_wait_thread:
    return
  global_wait_thread_lock.acquire()
  if not global_wait_thread:
    global_wait_thread = WaitChildThread()
    global_wait_thread.start()
    atexit.register(stop_global_wait_thread)
  global_wait_thread_lock.release()


def stop_global_wait_thread():
  assert global_wait_thread
  global_wait_thread.stop()
  global_wait_thread.join()


def run(cmd_str, globals, locals, alias_map=None):
  start_global_wait_thread()
  tok = Tokenizer(cmd_str, alias_map=alias_map)
  parser = Parser(tok)
  evaluator = Evaluator(parser)
  evaluator.execute(globals, locals)
  return evaluator.rc()
